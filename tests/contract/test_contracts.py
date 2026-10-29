from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jarvis.contracts import (
    Approval,
    ClarificationCode,
    DialogueActCode,
    PrivacyMode,
    SemanticPacket,
    SemanticStatusCode,
    SpeechSegment,
    Task,
)


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Task(goal="test", unexpected=True)


def test_speech_segment_rejects_reversed_timing() -> None:
    with pytest.raises(ValidationError, match="segment end precedes start"):
        SpeechSegment(
            session_id=uuid4(),
            started_monotonic_ns=20,
            ended_monotonic_ns=10,
            sample_rate_hz=16_000,
            duration_ms=1,
            privacy_mode=PrivacyMode.WATCHING,
        )


def test_approval_requires_future_expiry() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="expire after issue"):
        Approval(
            intent_id=uuid4(),
            issued_at=now,
            expires_at=now - timedelta(seconds=1),
            preview_digest="abc",
            nonce="nonce",
            signature="signature",
        )


def test_accepted_semantic_packet_requires_intent() -> None:
    with pytest.raises(ValidationError, match="requires an intent ID"):
        SemanticPacket.model_validate({"s": 0, "a": 0, "i": None, "p": {}, "r": [], "m": 0, "q": 0})


def test_unknown_semantic_packet_cannot_smuggle_interpretation() -> None:
    with pytest.raises(ValidationError, match="cannot contain an interpretation"):
        SemanticPacket(
            status=SemanticStatusCode.UNKNOWN,
            dialogue_act=DialogueActCode.QUERY,
            intent_id=1,
            clarification=ClarificationCode.UNCLEAR_SPEECH,
        )


def test_semantic_packet_wire_format_is_compact() -> None:
    packet = SemanticPacket.model_validate(
        {"s": 0, "a": 0, "i": 1, "p": {}, "r": [], "m": 0, "q": 0}
    )
    assert packet.to_wire() == {
        "s": 0,
        "a": 0,
        "i": 1,
        "p": {},
        "r": [],
        "m": 0,
        "q": 0,
    }
