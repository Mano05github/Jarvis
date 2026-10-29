"""Privacy-filtered, hash-chained persistence for conversation audit metadata."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import ValidationError

from jarvis.contracts import AuditEvent, DataClass, InteractionMode

SessionCloseReason = Literal["user_exit", "input_closed"]
SimulationDisposition = Literal["would_execute", "approval_required", "denied"]

_SIMULATED_ACTIONS = frozenset({"windows.application.open", "windows.application.close"})
_SIMULATED_RESOURCES = frozenset(
    {
        "application:notepad",
        "application:calculator",
        "application:visual-studio-code",
    }
)


class AuditIntegrityError(ValueError):
    """Raised when an existing audit log is malformed or its chain is invalid."""


class ConversationAudit(Protocol):
    """Allowlisted metadata-only event surface used by the turn controller."""

    session_id: UUID

    def record_session_started(self) -> AuditEvent: ...

    def record_turn_started(self, request_id: UUID) -> AuditEvent: ...

    def record_turn_completed(
        self,
        *,
        request_id: UUID,
        mode: InteractionMode,
        pending: bool,
        compiled_actions: int,
        simulations: int,
        plan_rejected: bool,
        task_id: UUID | None,
    ) -> AuditEvent: ...

    def record_turn_failed(self, request_id: UUID) -> AuditEvent: ...

    def record_simulation(
        self,
        *,
        task_id: UUID,
        intent_id: UUID,
        policy_decision_id: UUID,
        action: str,
        resource: str,
        disposition: SimulationDisposition,
    ) -> AuditEvent: ...

    def record_session_closed(self, reason: SessionCloseReason) -> AuditEvent: ...


def _canonical_payload(event: AuditEvent) -> bytes:
    payload = event.model_dump(mode="json", exclude={"digest"})
    payload["data_classes"] = sorted(payload["data_classes"])
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _event_digest(event: AuditEvent) -> str:
    return hashlib.sha256(_canonical_payload(event)).hexdigest()


class JsonlSessionAuditLog:
    """Append durable local events without accepting conversation or secret text."""

    def __init__(
        self,
        path: Path,
        session_id: UUID,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path.resolve(strict=False)
        self.session_id = session_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self._previous_digest: str | None = None
        self._event_count = 0
        self._closed = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    @property
    def event_count(self) -> int:
        return self._event_count

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        if not self.path.is_file():
            raise AuditIntegrityError(f"audit path is not a file: {self.path}")
        previous_digest: str | None = None
        last_event_type: str | None = None
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise AuditIntegrityError(f"blank audit event at line {line_number}")
                try:
                    event = AuditEvent.model_validate_json(line)
                except (ValidationError, ValueError) as error:
                    raise AuditIntegrityError(
                        f"invalid audit event at line {line_number}"
                    ) from error
                if event.session_id != self.session_id:
                    raise AuditIntegrityError(f"audit session mismatch at line {line_number}")
                if event.previous_digest != previous_digest:
                    raise AuditIntegrityError(f"broken audit chain at line {line_number}")
                expected_digest = _event_digest(event)
                if not hmac.compare_digest(event.digest, expected_digest):
                    raise AuditIntegrityError(f"audit digest mismatch at line {line_number}")
                previous_digest = event.digest
                last_event_type = event.event_type
                self._event_count += 1
        self._previous_digest = previous_digest
        self._closed = last_event_type == "conversation.session.closed"

    def _append(
        self,
        event_type: str,
        summary: str,
        *,
        task_id: UUID | None = None,
    ) -> AuditEvent:
        if self._closed:
            raise RuntimeError("cannot append to a closed conversation audit log")
        candidate = AuditEvent(
            session_id=self.session_id,
            task_id=task_id,
            occurred_at=self.clock(),
            event_type=event_type,
            summary=summary,
            data_classes=frozenset({DataClass.PERSONAL}),
            previous_digest=self._previous_digest,
            digest="pending",
        )
        event = candidate.model_copy(update={"digest": _event_digest(candidate)})
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._previous_digest = event.digest
        self._event_count += 1
        return event

    def record_session_started(self) -> AuditEvent:
        return self._append(
            "conversation.session.started",
            "persistence=metadata_only;content_retained=false",
        )

    def record_turn_started(self, request_id: UUID) -> AuditEvent:
        return self._append(
            "conversation.turn.started",
            f"request_id={request_id};content_retained=false",
        )

    def record_turn_completed(
        self,
        *,
        request_id: UUID,
        mode: InteractionMode,
        pending: bool,
        compiled_actions: int,
        simulations: int,
        plan_rejected: bool,
        task_id: UUID | None,
    ) -> AuditEvent:
        if compiled_actions < 0 or simulations < 0:
            raise ValueError("audit counters cannot be negative")
        summary = ";".join(
            (
                f"request_id={request_id}",
                f"mode={mode.value}",
                f"pending={str(pending).lower()}",
                f"compiled_actions={compiled_actions}",
                f"simulations={simulations}",
                f"plan_rejected={str(plan_rejected).lower()}",
                "content_retained=false",
            )
        )
        return self._append(
            "conversation.turn.completed",
            summary,
            task_id=task_id,
        )

    def record_turn_failed(self, request_id: UUID) -> AuditEvent:
        return self._append(
            "conversation.turn.failed",
            f"request_id={request_id};error_detail_retained=false;content_retained=false",
        )

    def record_simulation(
        self,
        *,
        task_id: UUID,
        intent_id: UUID,
        policy_decision_id: UUID,
        action: str,
        resource: str,
        disposition: SimulationDisposition,
    ) -> AuditEvent:
        if action not in _SIMULATED_ACTIONS or resource not in _SIMULATED_RESOURCES:
            raise ValueError("simulation audit fields are outside the registered allowlist")
        if disposition not in {"would_execute", "approval_required", "denied"}:
            raise ValueError("invalid simulation disposition")
        summary = ";".join(
            (
                f"intent_id={intent_id}",
                f"policy_decision_id={policy_decision_id}",
                f"action={action}",
                f"resource={resource}",
                f"disposition={disposition}",
                "simulated=true",
            )
        )
        return self._append("action.simulated", summary, task_id=task_id)

    def record_session_closed(self, reason: SessionCloseReason) -> AuditEvent:
        if reason not in {"user_exit", "input_closed"}:
            raise ValueError("invalid session close reason")
        event = self._append(
            "conversation.session.closed",
            f"reason={reason};content_retained=false",
        )
        self._closed = True
        return event


__all__ = [
    "AuditIntegrityError",
    "ConversationAudit",
    "JsonlSessionAuditLog",
    "SessionCloseReason",
    "SimulationDisposition",
]
