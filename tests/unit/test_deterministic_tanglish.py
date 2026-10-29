from __future__ import annotations

from pathlib import Path

from jarvis.benchmarking.qwen_semantic import evidence_for_case, load_decoder_cases
from jarvis.contracts.models import (
    ClarificationCode,
    SemanticStatusCode,
)
from jarvis.understanding.deterministic_tanglish import (
    decode_deterministic_tanglish,
    normalize_tanglish_tokens,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASE_PACK = PROJECT_ROOT / "config" / "semantic-decoder" / "benchmark-v1.jsonl"


def test_deterministic_decoder_passes_complete_phase1_packet_gate() -> None:
    cases = load_decoder_cases(CASE_PACK)

    actual = [
        decode_deterministic_tanglish(
            evidence_for_case(case),
            pending_operation=case.pending_operation,
            available_reference_ids=case.available_reference_ids,
        ).to_wire()
        for case in cases
    ]

    assert actual == [case.expected.to_wire() for case in cases]


def test_confirmation_without_pending_operation_clarifies() -> None:
    case = next(
        case
        for case in load_decoder_cases(CASE_PACK)
        if case.case_id == "safety_confirmation_without_pending"
    )

    packet = decode_deterministic_tanglish(evidence_for_case(case), pending_operation=False)

    assert packet.status is SemanticStatusCode.CLARIFY
    assert packet.clarification is ClarificationCode.NO_PENDING_OPERATION


def test_ambiguous_app_does_not_select_a_candidate() -> None:
    case = next(
        case for case in load_decoder_cases(CASE_PACK) if case.case_id == "safety_ambiguous_app"
    )

    packet = decode_deterministic_tanglish(evidence_for_case(case), pending_operation=False)

    assert packet.status is SemanticStatusCode.CLARIFY
    assert packet.slots == {}
    assert packet.clarification is ClarificationCode.AMBIGUOUS_TARGET


def test_prompt_injection_without_candidates_cannot_open_an_app() -> None:
    case = next(
        case
        for case in load_decoder_cases(CASE_PACK)
        if case.case_id == "safety_prompt_injection_no_candidate"
    )

    packet = decode_deterministic_tanglish(evidence_for_case(case), pending_operation=False)

    assert packet.status is SemanticStatusCode.CLARIFY
    assert packet.slots == {}
    assert packet.clarification is ClarificationCode.MISSING_TARGET


def test_tamil_and_romanized_tokens_share_control_vocabulary() -> None:
    assert normalize_tanglish_tokens("ஆமா, நோட்பேட் ஓபன் பண்ணு") == (
        "aama",
        "notepad",
        "open",
        "pannu",
    )
