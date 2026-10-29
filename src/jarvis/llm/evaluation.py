"""Controlled, non-sensitive companion/planner evaluation harness."""

from __future__ import annotations

import json
import os
import statistics
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.contracts import (
    InteractionMode,
    LLMMessage,
    LLMPrivacyClass,
    LLMRequest,
)
from jarvis.llm.base import ProviderError
from jarvis.llm.gateway import LLMGateway

_APPLICATION_ALIASES = {
    "calc": "calculator",
    "calc.exe": "calculator",
    "calculator": "calculator",
    "code": "visual-studio-code",
    "code.exe": "visual-studio-code",
    "notepad": "notepad",
    "notepad.exe": "notepad",
    "visual studio code": "visual-studio-code",
    "visual-studio-code": "visual-studio-code",
    "vs code": "visual-studio-code",
    "vscode": "visual-studio-code",
}


def _canonical_plan_arguments(action: str, arguments: Mapping[str, object]) -> dict[str, object]:
    if action != "app.open" or set(arguments) != {"application"}:
        return dict(arguments)
    application = arguments["application"]
    if not isinstance(application, str):
        return dict(arguments)
    normalized = " ".join(application.casefold().strip().split())
    return {"application": _APPLICATION_ALIASES.get(normalized, normalized)}


class ExpectedPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str = Field(min_length=1)
    arguments: dict[str, str]


class CompanionEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    input_text: str = Field(min_length=1)
    expected_modes: tuple[InteractionMode, ...] = Field(min_length=1)
    context: dict[str, object] = Field(default_factory=dict)
    history: tuple[LLMMessage, ...] = Field(default=(), max_length=12)
    expected_plan: tuple[ExpectedPlanStep, ...] | None = None
    expected_clarification_field: str | None = None
    must_not_plan: bool = False
    required_reply_terms: tuple[str, ...] = ()
    maximum_reply_words: int = Field(default=45, ge=1, le=100)

    @model_validator(mode="after")
    def validate_expectations(self) -> CompanionEvaluationCase:
        if self.history:
            if self.history[0].role != "user" or self.history[-1].role != "assistant":
                raise ValueError("evaluation history must start with user and end with assistant")
            if any(
                current.role == following.role
                for current, following in zip(self.history, self.history[1:], strict=False)
            ):
                raise ValueError("evaluation history roles must alternate")
        if self.must_not_plan and self.expected_plan is not None:
            raise ValueError("no-plan case cannot define an expected plan")
        if self.must_not_plan and set(self.expected_modes).intersection(
            {InteractionMode.PLAN, InteractionMode.MIXED}
        ):
            raise ValueError("no-plan case cannot accept plan or mixed mode")
        if self.expected_plan is not None and not set(self.expected_modes).intersection(
            {InteractionMode.PLAN, InteractionMode.MIXED}
        ):
            raise ValueError("expected plan requires plan or mixed mode")
        if (
            self.expected_clarification_field is not None
            and InteractionMode.CLARIFY not in self.expected_modes
        ):
            raise ValueError("expected clarification field requires clarify mode")
        return self


def load_companion_cases(path: Path) -> list[CompanionEvaluationCase]:
    cases: list[CompanionEvaluationCase] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            cases.append(CompanionEvaluationCase.model_validate_json(raw))
        except ValueError as error:
            raise ValueError(f"invalid evaluation case on line {line_number}") from error
    if not cases:
        raise ValueError("evaluation case pack is empty")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("evaluation case IDs must be unique")
    return cases


def select_companion_cases(
    cases: list[CompanionEvaluationCase], case_ids: Sequence[str] | None
) -> list[CompanionEvaluationCase]:
    if not case_ids:
        return cases
    requested = list(case_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("evaluation case IDs must not be repeated")
    by_id = {case.case_id: case for case in cases}
    unknown = sorted(set(requested).difference(by_id))
    if unknown:
        raise ValueError(f"unknown evaluation case IDs: {', '.join(unknown)}")
    return [by_id[case_id] for case_id in requested]


def evaluate_companion_gateway(
    *,
    gateway: LLMGateway,
    cases: list[CompanionEvaluationCase],
    rubric: str,
    output_directory: Path,
) -> dict[str, object]:
    output_directory.mkdir(parents=True, exist_ok=True)
    results_path = output_directory / "results.jsonl"
    results_path.write_text("", encoding="utf-8")
    latencies: list[float] = []
    passed = 0
    mode_passed = 0
    provider_failures = 0
    category_counts: dict[str, int] = {}
    category_passed: dict[str, int] = {}

    def append_result(result: dict[str, object]) -> None:
        with results_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    for case in cases:
        request = LLMRequest(
            purpose="companion",
            system_instructions=rubric,
            messages=(*case.history, LLMMessage(role="user", content=case.input_text)),
            response_schema="InteractionEnvelope-v1",
            context=case.context,
            privacy_class=LLMPrivacyClass.REMOTE_ALLOWED,
            maximum_output_tokens=500,
            deadline_ms=30_000,
        )
        started = perf_counter()
        try:
            envelope, response = gateway.complete_detailed(request)
        except ProviderError as error:
            elapsed_ms = (perf_counter() - started) * 1_000
            latencies.append(elapsed_ms)
            provider_failures += 1
            category_counts[case.category] = category_counts.get(case.category, 0) + 1
            category_passed.setdefault(case.category, 0)
            append_result(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "expected_modes": [mode.value for mode in case.expected_modes],
                    "actual_mode": None,
                    "passed": False,
                    "mode_pass": False,
                    "authority_pass": False,
                    "script_match_pass": False,
                    "brevity_pass": False,
                    "clarification_field_pass": False,
                    "no_plan_pass": False,
                    "plan_pass": False,
                    "required_terms_pass": False,
                    "reply_word_count": None,
                    "latency_ms": elapsed_ms,
                    "provider_error_code": error.code.value,
                    "provider_error": str(error),
                }
            )
            continue
        elapsed_ms = (perf_counter() - started) * 1_000
        latencies.append(elapsed_ms)
        # MIXED is a plan-bearing success when the case expects a plan and the
        # exact proposed steps are validated below. The only semantic difference
        # is that MIXED also contains a conversational reply.
        mode_pass = envelope.mode in case.expected_modes or (
            case.expected_plan is not None
            and InteractionMode.PLAN in case.expected_modes
            and envelope.mode is InteractionMode.MIXED
        )
        mode_passed += int(mode_pass)
        authority_pass = envelope.authority == "none" and response.authority == "none"
        visible_reply = envelope.reply
        if not visible_reply and envelope.clarification is not None:
            visible_reply = envelope.clarification.question
        input_uses_tamil_script = any("\u0b80" <= char <= "\u0bff" for char in case.input_text)
        reply_uses_tamil_script = any("\u0b80" <= char <= "\u0bff" for char in visible_reply)
        script_match_pass = (
            not visible_reply.strip() or input_uses_tamil_script == reply_uses_tamil_script
        )
        reply_word_count = len(visible_reply.split())
        brevity_pass = reply_word_count <= case.maximum_reply_words
        clarification_field_pass = case.expected_clarification_field is None or (
            envelope.clarification is not None
            and envelope.clarification.field == case.expected_clarification_field
        )
        no_plan_pass = not case.must_not_plan or envelope.plan is None
        plan_pass = True
        if case.expected_plan is not None:
            plan_pass = envelope.plan is not None and len(envelope.plan.steps) == len(
                case.expected_plan
            )
            if plan_pass:
                assert envelope.plan is not None
                plan_pass = all(
                    actual.action == expected.action
                    and _canonical_plan_arguments(actual.action, actual.arguments)
                    == _canonical_plan_arguments(expected.action, expected.arguments)
                    for actual, expected in zip(
                        envelope.plan.steps, case.expected_plan, strict=True
                    )
                )
        folded_reply = unicodedata.normalize("NFKC", visible_reply).casefold()
        required_terms_pass = all(
            unicodedata.normalize("NFKC", term).casefold() in folded_reply
            for term in case.required_reply_terms
        )
        case_pass = all(
            (
                mode_pass,
                authority_pass,
                script_match_pass,
                brevity_pass,
                clarification_field_pass,
                no_plan_pass,
                plan_pass,
                required_terms_pass,
            )
        )
        passed += int(case_pass)
        category_counts[case.category] = category_counts.get(case.category, 0) + 1
        category_passed[case.category] = category_passed.get(case.category, 0) + int(case_pass)
        append_result(
            {
                "case_id": case.case_id,
                "category": case.category,
                "expected_modes": [mode.value for mode in case.expected_modes],
                "actual_mode": envelope.mode.value,
                "passed": case_pass,
                "mode_pass": mode_pass,
                "authority_pass": authority_pass,
                "script_match_pass": script_match_pass,
                "brevity_pass": brevity_pass,
                "clarification_field_pass": clarification_field_pass,
                "no_plan_pass": no_plan_pass,
                "plan_pass": plan_pass,
                "required_terms_pass": required_terms_pass,
                "reply_word_count": reply_word_count,
                "latency_ms": elapsed_ms,
                "provider": response.provider.value,
                "profile_id": response.profile_id,
                "model": response.model,
                "usage": response.usage.model_dump(mode="json"),
                "envelope": envelope.model_dump(mode="json"),
            }
        )
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": len(cases),
        "passed": passed,
        "mode_accuracy": mode_passed / len(cases),
        "certified_accuracy": passed / len(cases),
        "provider_failures": provider_failures,
        "latency_p50_ms": statistics.median(latencies),
        "latency_max_ms": max(latencies),
        "categories": {
            category: {
                "cases": count,
                "passed": category_passed[category],
                "certified_accuracy": category_passed[category] / count,
            }
            for category, count in sorted(category_counts.items())
        },
    }
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return summary


__all__ = [
    "CompanionEvaluationCase",
    "ExpectedPlanStep",
    "evaluate_companion_gateway",
    "load_companion_cases",
    "select_companion_cases",
]
