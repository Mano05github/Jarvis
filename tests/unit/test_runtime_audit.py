from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from jarvis.contracts import (
    InteractionEnvelope,
    InteractionMode,
    LLMRequest,
    PlanProposal,
    PlanStepProposal,
)
from jarvis.runtime import AuditIntegrityError, ConversationSession, JsonlSessionAuditLog


class SingleResponseGateway:
    def __init__(self, response: InteractionEnvelope) -> None:
        self.response = response

    def complete(self, request: LLMRequest) -> InteractionEnvelope:
        return self.response.model_copy(update={"request_id": request.request_id})


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_audit_log_is_hash_chained_and_detects_tampering(tmp_path: Path) -> None:
    session_id = uuid4()
    path = tmp_path / "session.jsonl"
    audit = JsonlSessionAuditLog(path, session_id)

    audit.record_session_started()
    audit.record_turn_started(uuid4())

    events = read_events(path)
    assert events[0]["previous_digest"] is None
    assert events[1]["previous_digest"] == events[0]["digest"]
    assert all(len(str(event["digest"])) == 64 for event in events)
    assert JsonlSessionAuditLog(path, session_id).event_count == 2

    tampered = path.read_text(encoding="utf-8").replace(
        "content_retained=false", "content_retained=true", 1
    )
    path.write_text(tampered, encoding="utf-8")

    with pytest.raises(AuditIntegrityError, match="digest mismatch"):
        JsonlSessionAuditLog(path, session_id)


def test_conversation_audit_never_persists_prompt_reply_or_secret_text(
    tmp_path: Path,
) -> None:
    prompt_marker = "raw-user-secret-4471"
    reply_marker = "raw-model-secret-9924"
    session_id = uuid4()
    path = tmp_path / "session.jsonl"
    audit = JsonlSessionAuditLog(path, session_id)
    gateway = SingleResponseGateway(
        InteractionEnvelope(
            request_id=uuid4(),
            mode=InteractionMode.CHAT,
            reply=f"Reply containing {reply_marker}",
        )
    )
    session = ConversationSession(
        gateway=gateway,
        rubric="Return JSON.",
        audit=audit,
        session_id=session_id,
    )

    session.process(f"Prompt containing {prompt_marker} and api-key=fixture-secret")
    session.close()

    persisted = path.read_text(encoding="utf-8")
    assert prompt_marker not in persisted
    assert reply_marker not in persisted
    assert "fixture-secret" not in persisted
    assert [event["event_type"] for event in read_events(path)] == [
        "conversation.session.started",
        "conversation.turn.started",
        "conversation.turn.completed",
        "conversation.session.closed",
    ]


def test_simulated_action_audit_uses_canonical_metadata_only(tmp_path: Path) -> None:
    raw_goal_marker = "private-goal-1842"
    session_id = uuid4()
    path = tmp_path / "session.jsonl"
    audit = JsonlSessionAuditLog(path, session_id)
    plan = PlanProposal(
        goal=f"Open Calculator for {raw_goal_marker}",
        steps=(
            PlanStepProposal(
                step_id="s1",
                action="app.open",
                arguments={"application": "Calculator"},
            ),
        ),
    )
    gateway = SingleResponseGateway(
        InteractionEnvelope(
            request_id=uuid4(),
            mode=InteractionMode.PLAN,
            plan=plan,
        )
    )
    session = ConversationSession(
        gateway=gateway,
        rubric="Return JSON.",
        audit=audit,
        session_id=session_id,
    )

    session.process(f"Open calculator because {raw_goal_marker}")
    session.close()

    persisted = path.read_text(encoding="utf-8")
    events = read_events(path)
    simulated = next(event for event in events if event["event_type"] == "action.simulated")
    assert raw_goal_marker not in persisted
    assert "action=windows.application.open" in str(simulated["summary"])
    assert "resource=application:calculator" in str(simulated["summary"])
    assert simulated["task_id"] is not None


def test_gateway_failure_audit_omits_exception_detail(tmp_path: Path) -> None:
    error_marker = "provider-secret-error-5512"

    class FailingGateway:
        def complete(self, _request: LLMRequest) -> InteractionEnvelope:
            raise RuntimeError(error_marker)

    session_id = uuid4()
    path = tmp_path / "session.jsonl"
    audit = JsonlSessionAuditLog(path, session_id)
    session = ConversationSession(
        gateway=FailingGateway(),
        rubric="Return JSON.",
        audit=audit,
        session_id=session_id,
    )

    with pytest.raises(RuntimeError, match=error_marker):
        session.process("private failed prompt")

    persisted = path.read_text(encoding="utf-8")
    assert error_marker not in persisted
    assert "private failed prompt" not in persisted
    assert read_events(path)[-1]["event_type"] == "conversation.turn.failed"
