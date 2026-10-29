"""Bounded, evidence-linked deterministic Tanglish semantic decoding."""

from __future__ import annotations

import unicodedata
from collections.abc import Collection

from jarvis.contracts.models import (
    ClarificationCode,
    DialogueActCode,
    EntityCandidate,
    SemanticPacket,
    SemanticStatusCode,
    TranscriptEvidence,
)

_VARIANTS = {
    "ama": "aama",
    "aamaa": "aama",
    "aamaam": "aama",
    "vendaam": "vendam",
    "venam": "vendam",
    "ille": "illa",
    "pannidu": "pannu",
    "pannidunga": "pannu",
    "kaatu": "kaattu",
    "ஆம்": "aama",
    "ஆமா": "aama",
    "ஆமாம்": "aama",
    "இல்லை": "illa",
    "வேண்டாம்": "vendam",
    "ஓபன்": "open",
    "ஓப்பன்": "open",
    "திற": "open",
    "திறந்து": "open",
    "க்ளோஸ்": "close",
    "மூடு": "close",
    "பண்ணி": "pannu",
    "பண்ணு": "pannu",
    "முன்னாடி": "munnadi",
    "நோட்பேட்": "notepad",
    "கடைசி": "kadaisiya",
    "டவுன்லோட்": "download",
}
_FILLERS = frozenset({"ah", "aaahh", "uh", "um", "hmm"})
_AFFIRMATIONS = frozenset({"aama", "yes", "okay", "ok", "proceed"})
_NEGATIONS = frozenset({"illa", "vendam", "no"})
_PREVIOUS = frozenset({"munnadi", "previous", "before"})
_LATEST = frozenset({"latest", "kadaisiya", "recent", "newest"})
_PREFIX_VARIANTS = {
    "கடைசி": "kadaisiya",
    "டவுன்லோ": "download",
}

_INTENT_OPEN = 1
_INTENT_CLOSE = 2
_INTENT_FILE_SEARCH = 3
_INTENT_ASSISTANT_CANCEL = 4
_INTENT_APPROVAL_CANCEL = 5
_INTENT_APPROVAL_CONFIRM = 6

_REFERENCE_PREVIOUS_INTENT = 1
_REFERENCE_PREVIOUS_APP = 3
_REFERENCE_PENDING_OPERATION = 5

_MARKER_NEGATION = 1
_MARKER_CORRECTION = 2
_MARKER_CANCELLATION = 4
_MARKER_AFFIRMATION = 8


def normalize_tanglish_tokens(text: str) -> tuple[str, ...]:
    """Normalize scripts and punctuation without translating or inventing content."""

    normalized = unicodedata.normalize("NFKC", text).casefold().replace("_", " ")
    raw_tokens: list[str] = []
    current: list[str] = []
    for character in normalized:
        category = unicodedata.category(character)
        if category[0] in {"L", "M", "N"} or character == "-":
            current.append(character)
        elif current:
            raw_tokens.append("".join(current).strip("-"))
            current.clear()
    if current:
        raw_tokens.append("".join(current).strip("-"))

    tokens: list[str] = []
    for raw_token in raw_tokens:
        token = _VARIANTS.get(raw_token)
        if token is None:
            token = next(
                (
                    canonical
                    for prefix, canonical in _PREFIX_VARIANTS.items()
                    if raw_token.startswith(prefix)
                ),
                raw_token,
            )
        if token in _FILLERS or (tokens and tokens[-1] == token):
            continue
        tokens.append(token)
    return tuple(tokens)


def _has_any(tokens: set[str], options: Collection[str]) -> bool:
    return bool(tokens.intersection(options))


def _candidate_surface_matches(candidate: EntityCandidate, tokens: set[str]) -> bool:
    surface_tokens = set(normalize_tanglish_tokens(candidate.evidence[0].text))
    return bool(surface_tokens) and surface_tokens.issubset(tokens)


def _select_candidates(
    evidence: TranscriptEvidence,
    *,
    slot: str,
    tokens: set[str],
    minimum_candidate_score: float,
) -> list[EntityCandidate]:
    eligible = [
        candidate
        for candidate in evidence.entity_candidates
        if candidate.slot == slot
        and candidate.score >= minimum_candidate_score
        and _candidate_surface_matches(candidate, tokens)
    ]
    return sorted(eligible, key=lambda candidate: (-candidate.score, candidate.candidate_id))


def _clarify(
    *,
    act: DialogueActCode,
    intent_id: int,
    marker_bits: int,
    reason: ClarificationCode,
    references: tuple[int, ...] = (),
) -> SemanticPacket:
    return SemanticPacket(
        s=SemanticStatusCode.CLARIFY,
        a=act,
        i=intent_id,
        p={},
        r=references,
        m=marker_bits,
        q=reason,
    )


def decode_deterministic_tanglish(
    evidence: TranscriptEvidence,
    *,
    pending_operation: bool,
    available_reference_ids: Collection[int] = (),
    minimum_candidate_score: float = 0.70,
) -> SemanticPacket:
    """Compile a supported Tanglish command into an evidence-bound packet.

    Unsupported or incomplete input always becomes CLARIFY/UNKNOWN. This decoder has
    no tool authority and cannot create entity values; it can only select candidates.
    """

    if not 0 <= minimum_candidate_score <= 1:
        raise ValueError("minimum candidate score must be between zero and one")
    if not evidence.hypotheses:
        raise ValueError("transcript evidence requires at least one hypothesis")

    text = min(evidence.hypotheses, key=lambda item: item.rank).text
    tokens = set(normalize_tanglish_tokens(text))
    references = set(available_reference_ids)
    affirmation = _has_any(tokens, _AFFIRMATIONS)
    negative = _has_any(tokens, _NEGATIONS)
    has_open = "open" in tokens
    has_close = "close" in tokens

    # Confirmation must win over embedded action words such as "adha close pannu".
    if affirmation:
        pending_reference = (
            (_REFERENCE_PENDING_OPERATION,) if _REFERENCE_PENDING_OPERATION in references else ()
        )
        if pending_operation and pending_reference:
            return SemanticPacket(
                s=SemanticStatusCode.ACCEPTED,
                a=DialogueActCode.CONFIRMATION,
                i=_INTENT_APPROVAL_CONFIRM,
                p={},
                r=pending_reference,
                m=_MARKER_AFFIRMATION,
                q=ClarificationCode.NONE,
            )
        return _clarify(
            act=DialogueActCode.CONFIRMATION,
            intent_id=_INTENT_APPROVAL_CONFIRM,
            marker_bits=_MARKER_AFFIRMATION,
            reason=ClarificationCode.NO_PENDING_OPERATION,
        )

    if has_open and not has_close:
        app_candidates = _select_candidates(
            evidence,
            slot="app",
            tokens=tokens,
            minimum_candidate_score=minimum_candidate_score,
        )
        correction = negative
        marker_bits = _MARKER_NEGATION | _MARKER_CORRECTION if correction else 0
        act = DialogueActCode.CORRECTION if correction else DialogueActCode.COMMAND
        previous_reference = (
            (_REFERENCE_PREVIOUS_INTENT,)
            if correction and _REFERENCE_PREVIOUS_INTENT in references
            else ()
        )
        if len(app_candidates) != 1:
            return _clarify(
                act=act,
                intent_id=_INTENT_OPEN,
                marker_bits=marker_bits,
                references=previous_reference,
                reason=(
                    ClarificationCode.AMBIGUOUS_TARGET
                    if len(app_candidates) > 1
                    else ClarificationCode.MISSING_TARGET
                ),
            )
        return SemanticPacket(
            s=SemanticStatusCode.ACCEPTED,
            a=act,
            i=_INTENT_OPEN,
            p={"app": app_candidates[0].candidate_id},
            r=previous_reference,
            m=marker_bits,
            q=ClarificationCode.NONE,
        )

    if has_close:
        app_candidates = _select_candidates(
            evidence,
            slot="app",
            tokens=tokens,
            minimum_candidate_score=minimum_candidate_score,
        )
        previous_reference = (
            (_REFERENCE_PREVIOUS_APP,)
            if _has_any(tokens, _PREVIOUS) and _REFERENCE_PREVIOUS_APP in references
            else ()
        )
        if len(app_candidates) != 1:
            return _clarify(
                act=DialogueActCode.COMMAND,
                intent_id=_INTENT_CLOSE,
                marker_bits=0,
                references=previous_reference,
                reason=(
                    ClarificationCode.AMBIGUOUS_TARGET
                    if len(app_candidates) > 1
                    else ClarificationCode.MISSING_TARGET
                ),
            )
        return SemanticPacket(
            s=SemanticStatusCode.ACCEPTED,
            a=DialogueActCode.COMMAND,
            i=_INTENT_CLOSE,
            p={"app": app_candidates[0].candidate_id},
            r=previous_reference,
            m=0,
            q=ClarificationCode.NONE,
        )

    has_download = any(token.startswith("download") for token in tokens)
    if has_download and _has_any(tokens, _LATEST):
        locations = _select_candidates(
            evidence,
            slot="location",
            tokens=tokens,
            minimum_candidate_score=minimum_candidate_score,
        )
        sorts = _select_candidates(
            evidence,
            slot="sort",
            tokens=tokens,
            minimum_candidate_score=minimum_candidate_score,
        )
        if len(locations) != 1 or len(sorts) != 1:
            ambiguous = len(locations) > 1 or len(sorts) > 1
            return _clarify(
                act=DialogueActCode.QUERY,
                intent_id=_INTENT_FILE_SEARCH,
                marker_bits=0,
                reason=(
                    ClarificationCode.AMBIGUOUS_TARGET
                    if ambiguous
                    else ClarificationCode.MISSING_TARGET
                ),
            )
        return SemanticPacket(
            s=SemanticStatusCode.ACCEPTED,
            a=DialogueActCode.QUERY,
            i=_INTENT_FILE_SEARCH,
            p={
                "location": locations[0].candidate_id,
                "sort": sorts[0].candidate_id,
            },
            r=(),
            m=0,
            q=ClarificationCode.NONE,
        )

    if negative and "cancel" not in tokens and _REFERENCE_PREVIOUS_INTENT in references:
        return _clarify(
            act=DialogueActCode.CORRECTION,
            intent_id=_INTENT_OPEN,
            marker_bits=_MARKER_NEGATION | _MARKER_CORRECTION,
            references=(_REFERENCE_PREVIOUS_INTENT,),
            reason=ClarificationCode.MISSING_TARGET,
        )

    if "cancel" in tokens or "vendam" in tokens:
        marker_bits = _MARKER_CANCELLATION | (_MARKER_NEGATION if negative else 0)
        return SemanticPacket(
            s=SemanticStatusCode.ACCEPTED,
            a=DialogueActCode.CANCELLATION,
            i=(_INTENT_APPROVAL_CANCEL if pending_operation else _INTENT_ASSISTANT_CANCEL),
            p={},
            r=(),
            m=marker_bits,
            q=ClarificationCode.NONE,
        )

    return SemanticPacket(
        s=SemanticStatusCode.UNKNOWN,
        a=DialogueActCode.QUERY,
        i=None,
        p={},
        r=(),
        m=0,
        q=ClarificationCode.UNCLEAR_SPEECH,
    )


__all__ = ["decode_deterministic_tanglish", "normalize_tanglish_tokens"]
