"""Deterministic compilation, policy and simulation for proposed LLM plans."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.contracts import (
    ActionIntent,
    DataClass,
    Decision,
    PlanProposal,
    PolicyDecision,
    RiskLevel,
    Task,
)


class PlanCompilationError(ValueError):
    """Raised when an untrusted plan cannot bind to the Phase 1 action registry."""


class RegisteredApplication(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    executable: str = Field(min_length=1)
    aliases: frozenset[str] = Field(min_length=1)
    allowed_actions: frozenset[Literal["app.open", "app.close"]] = Field(min_length=1)
    process_names: frozenset[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_strings(self) -> RegisteredApplication:
        values = (self.executable, *self.aliases, *self.process_names)
        if any(not value.strip() or "\x00" in value for value in values):
            raise ValueError("application registry strings must be non-empty and NUL-free")
        return self


class ApplicationRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    applications: tuple[RegisteredApplication, ...] = Field(min_length=1)


class ApplicationRegistry:
    """Reviewed mapping from user-facing aliases to stable application IDs."""

    def __init__(self, applications: tuple[RegisteredApplication, ...]) -> None:
        by_id: dict[str, RegisteredApplication] = {}
        by_alias: dict[str, RegisteredApplication] = {}
        for application in applications:
            if application.application_id in by_id:
                raise ValueError(f"duplicate application ID: {application.application_id}")
            by_id[application.application_id] = application
            aliases = {*application.aliases, application.application_id}
            for alias in aliases:
                normalized = self.normalize_alias(alias)
                existing = by_alias.get(normalized)
                if existing is not None:
                    raise ValueError(
                        f"application alias is ambiguous: {alias} "
                        f"({existing.application_id}, {application.application_id})"
                    )
                by_alias[normalized] = application
        self._by_id = by_id
        self._by_alias = by_alias

    @staticmethod
    def normalize_alias(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PlanCompilationError("application must be a non-empty string")
        return " ".join(value.casefold().strip().split())

    @classmethod
    def from_toml(cls, path: Path) -> ApplicationRegistry:
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise ValueError(f"unable to load application registry: {path}") from error
        document = ApplicationRegistryDocument.model_validate(payload)
        return cls(document.applications)

    def resolve(self, alias: object, action: str) -> RegisteredApplication:
        normalized = self.normalize_alias(alias)
        application = self._by_alias.get(normalized)
        if application is None:
            raise PlanCompilationError("application is not registered")
        if action not in application.allowed_actions:
            raise PlanCompilationError(
                f"{action} is not allowed for application:{application.application_id}"
            )
        return application

    def application_ids_for(self, action: str) -> list[str]:
        return sorted(
            application.application_id
            for application in self._by_id.values()
            if action in application.allowed_actions
        )


class CompiledAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    depends_on: tuple[str, ...]
    intent: ActionIntent


class CompiledPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: Task
    actions: tuple[CompiledAction, ...]


class SimulationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: UUID
    action: str
    resource: str
    policy_decision_id: UUID
    disposition: Literal["would_execute", "approval_required", "denied"]
    simulated: Literal[True] = True


class ActionCompiler:
    """Bind a model proposal only to reviewed actions and canonical resources."""

    def __init__(
        self,
        registry: ApplicationRegistry | None = None,
        *,
        registry_path: Path | None = None,
    ) -> None:
        if registry is not None and registry_path is not None:
            raise ValueError("provide an application registry or registry path, not both")
        if registry is None:
            default_path = Path(__file__).resolve().parents[3] / "config" / "applications.toml"
            registry = ApplicationRegistry.from_toml(registry_path or default_path)
        self.registry = registry

    @property
    def available_actions(self) -> dict[str, object]:
        return {
            "app.open": {
                "required_arguments": ["application"],
                "registered_applications": self.registry.application_ids_for("app.open"),
            },
            "app.close": {
                "required_arguments": ["application"],
                "registered_applications": self.registry.application_ids_for("app.close"),
                "requires_approval": True,
            },
        }

    def compile(self, proposal: PlanProposal) -> CompiledPlan:
        task = Task(goal=proposal.goal, data_classes=frozenset({DataClass.PERSONAL}))
        actions: list[CompiledAction] = []
        for step in proposal.steps:
            if step.action not in {"app.open", "app.close"}:
                raise PlanCompilationError(f"action is not registered: {step.action}")
            if set(step.arguments) != {"application"}:
                raise PlanCompilationError(
                    f"{step.action} accepts exactly one application argument"
                )
            application = self.registry.resolve(step.arguments["application"], step.action)
            operation = "open" if step.action == "app.open" else "close"
            state = "running" if operation == "open" else "not_running"
            intent = ActionIntent(
                task_id=task.task_id,
                action=f"windows.application.{operation}",
                resource=f"application:{application.application_id}",
                purpose=proposal.goal,
                destination="local:interactive-windows-session",
                data_classes=frozenset({DataClass.PERSONAL}),
                reversible=operation == "open",
                expected_effect={
                    "application_id": application.application_id,
                    "state": state,
                },
                verification={
                    "method": "process-and-window-identity",
                    "executable": application.executable,
                    "process_names": sorted(application.process_names),
                },
            )
            actions.append(
                CompiledAction(
                    step_id=step.step_id,
                    depends_on=step.depends_on,
                    intent=intent,
                )
            )
        return CompiledPlan(task=task, actions=tuple(actions))


class SimulatedPolicyGateway:
    """Phase 1 policy stub: it classifies but grants no executable capability."""

    bundle_version = "phase1-simulation-v1"

    def evaluate(self, intent: ActionIntent) -> PolicyDecision:
        if intent.action == "windows.application.open" and intent.resource in {
            "application:notepad",
            "application:calculator",
            "application:visual-studio-code",
        }:
            return PolicyDecision(
                intent_id=intent.intent_id,
                decision=Decision.ALLOW,
                risk=RiskLevel.R1,
                reasons=("registered reversible application launch simulation",),
                policy_bundle_version=self.bundle_version,
            )
        if intent.action == "windows.application.close" and intent.resource in {
            "application:notepad",
            "application:calculator",
            "application:visual-studio-code",
        }:
            return PolicyDecision(
                intent_id=intent.intent_id,
                decision=Decision.ASK,
                risk=RiskLevel.R2,
                reasons=("graceful close may encounter unsaved user work",),
                policy_bundle_version=self.bundle_version,
            )
        return PolicyDecision(
            intent_id=intent.intent_id,
            decision=Decision.DENY,
            risk=RiskLevel.R4,
            reasons=("action is outside the Phase 1 simulation policy",),
            policy_bundle_version=self.bundle_version,
        )


class SimulationExecutor:
    """Record policy outcomes without invoking an operating-system capability."""

    def execute(
        self,
        compiled: CompiledPlan,
        decisions: tuple[PolicyDecision, ...],
        *,
        approved_intent_ids: frozenset[UUID] = frozenset(),
    ) -> tuple[SimulationRecord, ...]:
        by_intent = {decision.intent_id: decision for decision in decisions}
        records: list[SimulationRecord] = []
        for action in compiled.actions:
            decision = by_intent[action.intent.intent_id]
            disposition: Literal["would_execute", "approval_required", "denied"]
            if decision.decision is Decision.ALLOW:
                disposition = "would_execute"
            elif (
                decision.decision is Decision.ASK and action.intent.intent_id in approved_intent_ids
            ):
                disposition = "would_execute"
            elif decision.decision is Decision.ASK:
                disposition = "approval_required"
            else:
                disposition = "denied"
            records.append(
                SimulationRecord(
                    intent_id=action.intent.intent_id,
                    action=action.intent.action,
                    resource=action.intent.resource,
                    policy_decision_id=decision.decision_id,
                    disposition=disposition,
                )
            )
        return tuple(records)


__all__ = [
    "ActionCompiler",
    "ApplicationRegistry",
    "ApplicationRegistryDocument",
    "CompiledAction",
    "CompiledPlan",
    "PlanCompilationError",
    "RegisteredApplication",
    "SimulatedPolicyGateway",
    "SimulationExecutor",
    "SimulationRecord",
]
