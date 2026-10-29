from uuid import uuid4

import pytest
from pydantic import ValidationError

from jarvis.contracts import (
    CriticalMarker,
    DialogueAct,
    EntityCandidate,
    EvidenceSpan,
    PrivacyMode,
    SemanticPacket,
    SemanticStatus,
    TranscriptEvidence,
    TranscriptHypothesis,
)
from jarvis.understanding import SemanticGateError, expand_semantic_packet


def correction_evidence(score: float = 0.96) -> TranscriptEvidence:
    text = "illa vendam VS Code open pannu"
    start = text.index("VS Code")
    return TranscriptEvidence(
        session_id=uuid4(),
        utterance_id=uuid4(),
        emitted_monotonic_ns=100,
        engine_id="fixture-stt",
        hypotheses=(
            TranscriptHypothesis(
                hypothesis_id="h0",
                rank=0,
                text=text,
                confidence=0.9,
                language="mixed",
            ),
        ),
        entity_candidates=(
            EntityCandidate(
                candidate_id=2,
                slot="app",
                canonical_value="visual_studio_code",
                score=score,
                evidence=(
                    EvidenceSpan(
                        hypothesis_id="h0",
                        start_char=start,
                        end_char=start + len("VS Code"),
                        text="VS Code",
                    ),
                ),
            ),
        ),
        privacy_mode=PrivacyMode.WATCHING,
    )


def correction_packet(candidate_id: int = 2) -> SemanticPacket:
    return SemanticPacket.model_validate(
        {
            "s": 0,
            "a": 1,
            "i": 1,
            "p": {"app": candidate_id},
            "r": [1],
            "m": 3,
            "q": 0,
        }
    )


def expand(packet: SemanticPacket, evidence: TranscriptEvidence):
    return expand_semantic_packet(
        packet,
        evidence,
        intent_registry={1: "app.open"},
        reference_registry={1: "previous_intent"},
        required_slots={"app.open": frozenset({"app"})},
        minimum_candidate_score=0.85,
        pending_operation=False,
    )


def test_expansion_binds_every_slot_to_transcript_evidence() -> None:
    evidence = correction_evidence()
    envelope = expand(correction_packet(), evidence)

    assert envelope.status is SemanticStatus.ACCEPTED
    assert envelope.dialogue_act is DialogueAct.CORRECTION
    assert envelope.intent == "app.open"
    assert envelope.slots == {"app": "visual_studio_code"}
    assert envelope.slot_candidate_ids == {"app": 2}
    assert envelope.references == ("previous_intent",)
    assert envelope.critical_markers == {
        CriticalMarker.NEGATION,
        CriticalMarker.CORRECTION,
    }
    assert envelope.authority == "none"


def test_transcript_evidence_rejects_a_fabricated_span() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        TranscriptEvidence(
            session_id=uuid4(),
            utterance_id=uuid4(),
            emitted_monotonic_ns=100,
            engine_id="fixture-stt",
            hypotheses=(TranscriptHypothesis(hypothesis_id="h0", rank=0, text="open calculator"),),
            entity_candidates=(
                EntityCandidate(
                    candidate_id=1,
                    slot="app",
                    canonical_value="notepad",
                    score=0.99,
                    evidence=(
                        EvidenceSpan(
                            hypothesis_id="h0",
                            start_char=5,
                            end_char=15,
                            text="notepadxxx",
                        ),
                    ),
                ),
            ),
            privacy_mode=PrivacyMode.WATCHING,
        )


def test_gate_rejects_an_unsupplied_candidate() -> None:
    with pytest.raises(SemanticGateError, match="unsupplied"):
        expand(correction_packet(candidate_id=99), correction_evidence())


def test_gate_rejects_low_scoring_critical_evidence() -> None:
    with pytest.raises(SemanticGateError, match="below the evidence gate"):
        expand(correction_packet(), correction_evidence(score=0.5))


def test_gate_rejects_unknown_intent_and_reference_ids() -> None:
    unknown_intent = SemanticPacket.model_validate(
        {"s": 0, "a": 0, "i": 99, "p": {}, "r": [], "m": 0, "q": 0}
    )
    with pytest.raises(SemanticGateError, match="unknown intent"):
        expand(unknown_intent, correction_evidence())

    unknown_reference = SemanticPacket.model_validate(
        {"s": 0, "a": 0, "i": 1, "p": {"app": 2}, "r": [99], "m": 0, "q": 0}
    )
    with pytest.raises(SemanticGateError, match="unknown reference"):
        expand(unknown_reference, correction_evidence())


def test_gate_rejects_candidate_used_for_wrong_slot() -> None:
    packet = SemanticPacket.model_validate(
        {"s": 0, "a": 0, "i": 1, "p": {"target": 2}, "r": [], "m": 0, "q": 0}
    )
    with pytest.raises(SemanticGateError, match="wrong slot"):
        expand(packet, correction_evidence())


@pytest.mark.parametrize(
    ("act", "marker_bits", "message"),
    [
        (1, 1, "correction marker"),
        (2, 0, "cancellation marker"),
        (3, 0, "affirmation marker"),
    ],
)
def test_gate_rejects_dialogue_acts_without_required_markers(
    act: int, marker_bits: int, message: str
) -> None:
    packet = SemanticPacket.model_validate(
        {"s": 0, "a": act, "i": 1, "p": {"app": 2}, "r": [], "m": marker_bits, "q": 0}
    )
    with pytest.raises(SemanticGateError, match=message):
        expand_semantic_packet(
            packet,
            correction_evidence(),
            intent_registry={1: "app.open"},
            reference_registry={},
            required_slots={"app.open": frozenset({"app"})},
            minimum_candidate_score=0.85,
            pending_operation=True,
        )


def test_gate_rejects_accepted_intent_missing_required_slot() -> None:
    packet = SemanticPacket.model_validate(
        {"s": 0, "a": 0, "i": 1, "p": {}, "r": [], "m": 0, "q": 0}
    )
    with pytest.raises(SemanticGateError, match="missing required slots: app"):
        expand(packet, correction_evidence())


def test_confirmation_requires_trusted_pending_operation() -> None:
    packet = SemanticPacket.model_validate(
        {"s": 0, "a": 3, "i": 1, "p": {}, "r": [], "m": 8, "q": 0}
    )
    with pytest.raises(SemanticGateError, match="no trusted pending operation"):
        expand_semantic_packet(
            packet,
            correction_evidence(),
            intent_registry={1: "approval.confirm"},
            reference_registry={},
            required_slots={},
            minimum_candidate_score=0.85,
            pending_operation=False,
        )


def test_confirmation_without_pending_operation_can_request_clarification() -> None:
    packet = SemanticPacket.model_validate(
        {"s": 1, "a": 3, "i": 6, "p": {}, "r": [], "m": 8, "q": 5}
    )
    envelope = expand_semantic_packet(
        packet,
        correction_evidence(),
        intent_registry={6: "approval.confirm"},
        reference_registry={},
        required_slots={},
        minimum_candidate_score=0.85,
        pending_operation=False,
    )

    assert envelope.status is SemanticStatus.CLARIFY
    assert envelope.clarification_reason == "no_pending_operation"


def test_unknown_packet_expands_only_to_clarification() -> None:
    packet = SemanticPacket.model_validate(
        {"s": 2, "a": 4, "i": None, "p": {}, "r": [], "m": 0, "q": 1}
    )
    envelope = expand(packet, correction_evidence())

    assert envelope.status is SemanticStatus.UNKNOWN
    assert envelope.intent is None
    assert envelope.dialogue_act is None
    assert envelope.clarification_reason == "unclear_speech"
