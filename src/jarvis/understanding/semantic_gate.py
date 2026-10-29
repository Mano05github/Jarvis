"""Deterministically expand and validate compact semantic-decoder output."""

from __future__ import annotations

from collections.abc import Mapping

from jarvis.contracts.models import (
    ClarificationCode,
    ClarificationReason,
    CriticalMarker,
    DecoderSource,
    DialogueAct,
    DialogueActCode,
    IntentEnvelope,
    SemanticPacket,
    SemanticStatus,
    SemanticStatusCode,
    TranscriptEvidence,
)


class SemanticGateError(ValueError):
    """The model packet cannot cross the trusted intent boundary."""


_STATUS = {
    SemanticStatusCode.ACCEPTED: SemanticStatus.ACCEPTED,
    SemanticStatusCode.CLARIFY: SemanticStatus.CLARIFY,
    SemanticStatusCode.UNKNOWN: SemanticStatus.UNKNOWN,
}
_ACT = {
    DialogueActCode.COMMAND: DialogueAct.COMMAND,
    DialogueActCode.CORRECTION: DialogueAct.CORRECTION,
    DialogueActCode.CANCELLATION: DialogueAct.CANCELLATION,
    DialogueActCode.CONFIRMATION: DialogueAct.CONFIRMATION,
    DialogueActCode.QUERY: DialogueAct.QUERY,
    DialogueActCode.STATUS: DialogueAct.STATUS,
}
_CLARIFICATION = {
    ClarificationCode.UNCLEAR_SPEECH: ClarificationReason.UNCLEAR_SPEECH,
    ClarificationCode.MISSING_TARGET: ClarificationReason.MISSING_TARGET,
    ClarificationCode.AMBIGUOUS_TARGET: ClarificationReason.AMBIGUOUS_TARGET,
    ClarificationCode.MISSING_SCOPE: ClarificationReason.MISSING_SCOPE,
    ClarificationCode.NO_PENDING_OPERATION: ClarificationReason.NO_PENDING_OPERATION,
    ClarificationCode.CONFLICTING_COMMANDS: ClarificationReason.CONFLICTING_COMMANDS,
}
_MARKERS = (
    (1, CriticalMarker.NEGATION),
    (2, CriticalMarker.CORRECTION),
    (4, CriticalMarker.CANCELLATION),
    (8, CriticalMarker.AFFIRMATION),
)


def _critical_markers(bits: int) -> frozenset[CriticalMarker]:
    return frozenset(marker for mask, marker in _MARKERS if bits & mask)


def expand_semantic_packet(
    packet: SemanticPacket,
    evidence: TranscriptEvidence,
    *,
    intent_registry: Mapping[int, str],
    reference_registry: Mapping[int, str],
    required_slots: Mapping[str, frozenset[str]],
    minimum_candidate_score: float,
    pending_operation: bool,
    decoder_source: DecoderSource = DecoderSource.QWEN,
) -> IntentEnvelope:
    """Expand model codes only when every semantic claim has trusted support."""

    if not 0 <= minimum_candidate_score <= 1:
        raise ValueError("minimum candidate score must be between zero and one")

    status = _STATUS[packet.status]
    if status is SemanticStatus.UNKNOWN:
        return IntentEnvelope(
            session_id=evidence.session_id,
            utterance_id=evidence.utterance_id,
            emitted_monotonic_ns=evidence.emitted_monotonic_ns,
            status=status,
            clarification_reason=_CLARIFICATION[packet.clarification],
            decoder_source=decoder_source,
        )

    act = _ACT[packet.dialogue_act]
    intent: str | None = None
    if packet.intent_id is not None:
        intent = intent_registry.get(packet.intent_id)
        if intent is None:
            raise SemanticGateError("semantic packet selected an unknown intent ID")

    candidate_map = {item.candidate_id: item for item in evidence.entity_candidates}
    slots: dict[str, str] = {}
    slot_candidate_ids: dict[str, int] = {}
    for slot, candidate_id in packet.slots.items():
        candidate = candidate_map.get(candidate_id)
        if candidate is None:
            raise SemanticGateError("semantic packet selected an unsupplied entity candidate")
        if candidate.slot != slot:
            raise SemanticGateError("semantic packet selected a candidate for the wrong slot")
        if candidate.score < minimum_candidate_score:
            raise SemanticGateError("semantic packet selected a candidate below the evidence gate")
        slots[slot] = candidate.canonical_value
        slot_candidate_ids[slot] = candidate_id

    references: list[str] = []
    for reference_id in packet.references:
        reference = reference_registry.get(reference_id)
        if reference is None:
            raise SemanticGateError("semantic packet selected an unknown reference ID")
        references.append(reference)

    markers = _critical_markers(packet.marker_bits)
    if act is DialogueAct.CORRECTION and CriticalMarker.CORRECTION not in markers:
        raise SemanticGateError("correction act is missing its correction marker")
    if act is DialogueAct.CANCELLATION and CriticalMarker.CANCELLATION not in markers:
        raise SemanticGateError("cancellation act is missing its cancellation marker")
    if act is DialogueAct.CONFIRMATION:
        if CriticalMarker.AFFIRMATION not in markers:
            raise SemanticGateError("confirmation act is missing its affirmation marker")
        if status is SemanticStatus.ACCEPTED and not pending_operation:
            raise SemanticGateError("confirmation has no trusted pending operation")

    if status is SemanticStatus.ACCEPTED:
        assert intent is not None  # Enforced by SemanticPacket.
        missing = required_slots.get(intent, frozenset()).difference(slots)
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise SemanticGateError(f"accepted intent is missing required slots: {missing_list}")

    clarification = (
        None
        if packet.clarification is ClarificationCode.NONE
        else _CLARIFICATION[packet.clarification]
    )
    return IntentEnvelope(
        session_id=evidence.session_id,
        utterance_id=evidence.utterance_id,
        emitted_monotonic_ns=evidence.emitted_monotonic_ns,
        status=status,
        dialogue_act=act,
        intent=intent,
        slots=slots,
        slot_candidate_ids=slot_candidate_ids,
        references=tuple(references),
        critical_markers=markers,
        clarification_reason=clarification,
        decoder_source=decoder_source,
    )
