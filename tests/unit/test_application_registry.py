from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.contracts import Decision, PlanProposal, PlanStepProposal, RiskLevel
from jarvis.runtime import (
    ActionCompiler,
    ApplicationRegistry,
    PlanCompilationError,
    RegisteredApplication,
    SimulatedPolicyGateway,
    SimulationExecutor,
)


def close_plan(application: object) -> PlanProposal:
    return PlanProposal(
        goal="Close the selected application",
        steps=(
            PlanStepProposal(
                step_id="close",
                action="app.close",
                arguments={"application": application},
            ),
        ),
    )


def test_default_registry_compiles_close_to_r2_approval_simulation() -> None:
    compiler = ActionCompiler()
    compiled = compiler.compile(close_plan("  VS   Code "))
    decision = SimulatedPolicyGateway().evaluate(compiled.actions[0].intent)
    record = SimulationExecutor().execute(compiled, (decision,))[0]

    assert compiled.actions[0].intent.action == "windows.application.close"
    assert compiled.actions[0].intent.resource == "application:visual-studio-code"
    assert compiled.actions[0].intent.reversible is False
    assert decision.decision is Decision.ASK
    assert decision.risk is RiskLevel.R2
    assert record.disposition == "approval_required"


def test_available_actions_come_from_reviewed_registry() -> None:
    actions = ActionCompiler().available_actions
    assert actions["app.open"]["registered_applications"] == [
        "calculator",
        "notepad",
        "visual-studio-code",
    ]
    assert actions["app.close"]["requires_approval"] is True


def test_registry_rejects_ambiguous_alias() -> None:
    first = RegisteredApplication(
        application_id="first",
        executable="first.exe",
        aliases=frozenset({"shared"}),
        allowed_actions=frozenset({"app.open"}),
        process_names=frozenset({"first.exe"}),
    )
    second = RegisteredApplication(
        application_id="second",
        executable="second.exe",
        aliases=frozenset({"SHARED"}),
        allowed_actions=frozenset({"app.open"}),
        process_names=frozenset({"second.exe"}),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        ApplicationRegistry((first, second))


def test_registry_enforces_per_application_operations() -> None:
    application = RegisteredApplication(
        application_id="open-only",
        executable="open.exe",
        aliases=frozenset({"open only"}),
        allowed_actions=frozenset({"app.open"}),
        process_names=frozenset({"open.exe"}),
    )
    compiler = ActionCompiler(ApplicationRegistry((application,)))
    with pytest.raises(PlanCompilationError, match="not allowed"):
        compiler.compile(close_plan("open only"))


def test_registry_load_failure_is_bounded(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(ValueError, match="unable to load"):
        ApplicationRegistry.from_toml(missing)

    malformed = tmp_path / "bad.toml"
    malformed.write_text("not = [valid", encoding="utf-8")
    with pytest.raises(ValueError, match="unable to load"):
        ApplicationRegistry.from_toml(malformed)


def test_compiler_rejects_conflicting_registry_inputs() -> None:
    application = RegisteredApplication(
        application_id="fixture",
        executable="fixture.exe",
        aliases=frozenset({"fixture"}),
        allowed_actions=frozenset({"app.open"}),
        process_names=frozenset({"fixture.exe"}),
    )
    registry = ApplicationRegistry((application,))
    with pytest.raises(ValueError, match="not both"):
        ActionCompiler(registry, registry_path=Path("unused"))
