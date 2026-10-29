from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pytest

from jarvis.contracts import (
    GatewayConfig,
    InteractionEnvelope,
    InteractionMode,
    PlanProposal,
    PlanStepProposal,
    ProviderKind,
    ProviderProfile,
)
from jarvis.llm import (
    FakeLLMProvider,
    LLMGateway,
    ProviderError,
    ProviderErrorCode,
)
from jarvis.llm.evaluation import (
    evaluate_companion_gateway,
    load_companion_cases,
    select_companion_cases,
)


def test_load_companion_smoke_cases() -> None:
    project_root = Path(__file__).resolve().parents[2]
    cases = load_companion_cases(project_root / "config" / "llm" / "companion-eval-smoke-v1.jsonl")

    assert len(cases) == 4
    assert cases[0].expected_modes == (InteractionMode.CHAT,)


def test_load_balanced_heldout_companion_cases() -> None:
    project_root = Path(__file__).resolve().parents[2]
    cases = load_companion_cases(
        project_root / "config" / "llm" / "companion-eval-heldout-v1.jsonl"
    )

    assert len(cases) == 40
    assert Counter(case.category for case in cases) == {
        "companionship": 4,
        "knowledge": 4,
        "correction": 4,
        "anaphora": 4,
        "clarification": 4,
        "cancellation": 4,
        "planning": 4,
        "multi_step_planning": 4,
        "ambiguity": 4,
        "prompt_injection": 4,
    }
    assert sum(case.expected_plan is not None for case in cases) == 14
    assert sum(case.must_not_plan for case in cases) == 17


def test_select_companion_cases_is_explicit_and_ordered() -> None:
    project_root = Path(__file__).resolve().parents[2]
    cases = load_companion_cases(project_root / "config" / "llm" / "companion-eval-smoke-v1.jsonl")

    selected = select_companion_cases(cases, ["plan_notepad", "chat_bored"])

    assert [case.case_id for case in selected] == ["plan_notepad", "chat_bored"]
    with pytest.raises(ValueError, match="unknown evaluation case"):
        select_companion_cases(cases, ["missing"])
    with pytest.raises(ValueError, match="must not be repeated"):
        select_companion_cases(cases, ["chat_bored", "chat_bored"])


def test_evaluation_writes_redacted_structured_results(tmp_path: Path) -> None:
    profile = ProviderProfile(
        profile_id="fixture",
        provider=ProviderKind.FAKE,
        model="fixture",
        remote=False,
    )
    config = GatewayConfig(
        default_profile="fixture",
        profiles={"fixture": profile},
    )
    response = InteractionEnvelope(
        request_id=uuid4(),
        mode=InteractionMode.CHAT,
        reply="Pesalam.",
    )
    gateway = LLMGateway(config, {"fixture": FakeLLMProvider(profile, response)})
    case_path = tmp_path / "cases.jsonl"
    case_path.write_text(
        json.dumps(
            {
                "case_id": "chat",
                "category": "companion",
                "input_text": "enaku bore adikudhu",
                "expected_modes": ["chat"],
                "context": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = evaluate_companion_gateway(
        gateway=gateway,
        cases=load_companion_cases(case_path),
        rubric="Return valid JSON.",
        output_directory=tmp_path / "results",
    )

    assert summary["mode_accuracy"] == 1.0
    assert summary["categories"] == {
        "companion": {"cases": 1, "passed": 1, "certified_accuracy": 1.0}
    }
    result = json.loads((tmp_path / "results" / "results.jsonl").read_text())
    assert result["envelope"]["authority"] == "none"
    assert result["no_plan_pass"] is True
    assert result["required_terms_pass"] is True


def test_evaluation_canonicalizes_registered_application_aliases(
    tmp_path: Path,
) -> None:
    profile = ProviderProfile(
        profile_id="fixture",
        provider=ProviderKind.FAKE,
        model="fixture",
        remote=False,
    )
    config = GatewayConfig(default_profile="fixture", profiles={"fixture": profile})
    response = InteractionEnvelope(
        request_id=uuid4(),
        mode=InteractionMode.MIXED,
        reply="VS Code open panna plan ready.",
        plan=PlanProposal(
            goal="Open the editor",
            steps=(
                PlanStepProposal(
                    step_id="s1",
                    action="app.open",
                    arguments={"application": "VS Code"},
                ),
            ),
        ),
    )
    gateway = LLMGateway(config, {"fixture": FakeLLMProvider(profile, response)})
    case_path = tmp_path / "cases.jsonl"
    case_path.write_text(
        json.dumps(
            {
                "case_id": "plan",
                "category": "planning",
                "input_text": "VS Code open pannu",
                "expected_modes": ["plan"],
                "expected_plan": [
                    {
                        "action": "app.open",
                        "arguments": {"application": "visual-studio-code"},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = evaluate_companion_gateway(
        gateway=gateway,
        cases=load_companion_cases(case_path),
        rubric="Return valid JSON.",
        output_directory=tmp_path / "results",
    )

    result = json.loads((tmp_path / "results" / "results.jsonl").read_text())
    assert summary["certified_accuracy"] == 1.0
    assert result["mode_pass"] is True
    assert result["plan_pass"] is True


def test_evaluation_persists_provider_failure_and_continues(tmp_path: Path) -> None:
    profile = ProviderProfile(
        profile_id="fixture",
        provider=ProviderKind.FAKE,
        model="fixture",
        remote=False,
    )
    config = GatewayConfig(default_profile="fixture", profiles={"fixture": profile})

    class FailingProvider:
        def __init__(self) -> None:
            self.profile = profile

        def complete(self, _request):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                "provider returned HTTP 400 (code=fixture_rejection)",
            )

    gateway = LLMGateway(config, {"fixture": FailingProvider()})
    case_path = tmp_path / "cases.jsonl"
    case_path.write_text(
        json.dumps(
            {
                "case_id": "failure",
                "category": "provider",
                "input_text": "synthetic input",
                "expected_modes": ["chat"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = evaluate_companion_gateway(
        gateway=gateway,
        cases=load_companion_cases(case_path),
        rubric="Return valid JSON.",
        output_directory=tmp_path / "results",
    )

    result = json.loads((tmp_path / "results" / "results.jsonl").read_text())
    assert summary["provider_failures"] == 1
    assert summary["passed"] == 0
    assert result["case_id"] == "failure"
    assert result["provider_error_code"] == "invalid_response"
    assert "HTTP 400" in result["provider_error"]
