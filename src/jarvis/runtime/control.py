"""Deterministic task lifecycle and digest-bound approval primitives."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.contracts import PolicyDecision, RiskLevel
from jarvis.runtime.actions import CompiledPlan


class TaskState(StrEnum):
    IDLE = "idle"
    INTERPRETING = "interpreting"
    CLARIFYING = "clarifying"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED})

_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.IDLE: frozenset({TaskState.INTERPRETING, TaskState.CANCELLED}),
    TaskState.INTERPRETING: frozenset(
        {
            TaskState.CLARIFYING,
            TaskState.PLANNING,
            TaskState.COMPLETED,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
    TaskState.CLARIFYING: frozenset(
        {TaskState.INTERPRETING, TaskState.CANCELLED, TaskState.FAILED}
    ),
    TaskState.PLANNING: frozenset(
        {
            TaskState.AWAITING_APPROVAL,
            TaskState.EXECUTING,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
    TaskState.AWAITING_APPROVAL: frozenset(
        {
            TaskState.INTERPRETING,
            TaskState.EXECUTING,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }
    ),
    TaskState.EXECUTING: frozenset({TaskState.VERIFYING, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.VERIFYING: frozenset({TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.CANCELLED: frozenset(),
    TaskState.FAILED: frozenset(),
}


class InvalidTaskTransition(RuntimeError):
    """Raised when trusted control flow attempts an illegal state transition."""


class TaskLifecycle:
    """Small explicit state machine; model output never changes it directly."""

    def __init__(self) -> None:
        self._state = TaskState.IDLE

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def transition(self, target: TaskState) -> TaskState:
        if target not in _TRANSITIONS[self._state]:
            raise InvalidTaskTransition(f"cannot transition {self._state} to {target}")
        self._state = target
        return target

    def cancel(self) -> TaskState:
        return self.transition(TaskState.CANCELLED)


def canonical_plan_payload(plan: CompiledPlan) -> dict[str, Any]:
    """Return only trusted, execution-relevant plan fields in canonical shape."""

    return {
        "schema_version": "1.0",
        "task_id": str(plan.task.task_id),
        "goal": plan.task.goal,
        "actions": [
            {
                "step_id": item.step_id,
                "depends_on": list(item.depends_on),
                "intent": {
                    "intent_id": str(item.intent.intent_id),
                    "task_id": str(item.intent.task_id),
                    "action": item.intent.action,
                    "resource": item.intent.resource,
                    "purpose": item.intent.purpose,
                    "destination": item.intent.destination,
                    "data_classes": sorted(value.value for value in item.intent.data_classes),
                    "reversible": item.intent.reversible,
                    "expected_effect": item.intent.expected_effect,
                    "verification": item.intent.verification,
                },
            }
            for item in plan.actions
        ],
    }


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def plan_digest(plan: CompiledPlan) -> str:
    return hashlib.sha256(canonical_json(canonical_plan_payload(plan))).hexdigest()


_RISK_ORDER = {
    RiskLevel.R0: 0,
    RiskLevel.R1: 1,
    RiskLevel.R2: 2,
    RiskLevel.R3: 3,
    RiskLevel.R4: 4,
}


def maximum_plan_risk(plan: CompiledPlan, decisions: Iterable[PolicyDecision]) -> RiskLevel:
    """Validate decision coverage and apply the deterministic maximum-risk lattice."""

    decision_list = tuple(decisions)
    expected = {action.intent.intent_id for action in plan.actions}
    actual = [decision.intent_id for decision in decision_list]
    if len(set(actual)) != len(actual):
        raise ValueError("policy decisions contain duplicate intent IDs")
    if set(actual) != expected:
        raise ValueError("policy decisions do not exactly cover the compiled plan")
    return max((decision.risk for decision in decision_list), key=_RISK_ORDER.__getitem__)


class PlanApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    approval_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    task_id: UUID
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    risk: RiskLevel
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(min_length=32)
    used_at: datetime | None = None
    invalidated_at: datetime | None = None
    authenticator: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_times(self) -> PlanApproval:
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("approval timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("approval must expire after issue time")
        return self


class ApprovalError(RuntimeError):
    """Fail-closed approval error with a stable machine-readable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ApprovalStore:
    """In-memory atomic approval issuer/consumer for the typed vertical slice."""

    def __init__(
        self,
        key: bytes,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(key) < 32:
            raise ValueError("approval key must contain at least 32 bytes")
        self._key = key
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: dict[UUID, PlanApproval] = {}
        self._lock = threading.Lock()

    def _authenticate(self, fields: dict[str, object]) -> str:
        return hmac.new(self._key, canonical_json(fields), hashlib.sha256).hexdigest()

    @staticmethod
    def _signed_fields(record: PlanApproval) -> dict[str, object]:
        return {
            "schema_version": record.schema_version,
            "approval_id": str(record.approval_id),
            "session_id": str(record.session_id),
            "task_id": str(record.task_id),
            "payload_digest": record.payload_digest,
            "risk": record.risk.value,
            "issued_at": record.issued_at.isoformat(),
            "expires_at": record.expires_at.isoformat(),
            "nonce": record.nonce,
        }

    def issue(
        self,
        *,
        session_id: UUID,
        plan: CompiledPlan,
        decisions: Iterable[PolicyDecision],
        ttl: timedelta = timedelta(seconds=30),
    ) -> PlanApproval:
        if ttl <= timedelta(0):
            raise ValueError("approval TTL must be positive")
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("approval clock must return timezone-aware timestamps")
        unsigned = PlanApproval(
            session_id=session_id,
            task_id=plan.task.task_id,
            payload_digest=plan_digest(plan),
            risk=maximum_plan_risk(plan, decisions),
            issued_at=now,
            expires_at=now + ttl,
            nonce=secrets.token_hex(16),
            authenticator="0" * 64,
        )
        record = unsigned.model_copy(
            update={"authenticator": self._authenticate(self._signed_fields(unsigned))}
        )
        with self._lock:
            self._records[record.approval_id] = record
        return record

    def consume(
        self,
        approval_id: UUID,
        *,
        session_id: UUID,
        plan: CompiledPlan,
    ) -> PlanApproval:
        """Atomically validate and mark one approval used before execution."""

        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                raise ApprovalError("approval_not_found")
            expected_authenticator = self._authenticate(self._signed_fields(record))
            if not hmac.compare_digest(record.authenticator, expected_authenticator):
                raise ApprovalError("approval_authenticator_mismatch")
            if record.invalidated_at is not None:
                raise ApprovalError("approval_invalidated")
            if record.used_at is not None:
                raise ApprovalError("approval_replayed")
            now = self._clock()
            if now.tzinfo is None:
                raise ApprovalError("approval_clock_invalid")
            if now >= record.expires_at:
                raise ApprovalError("approval_expired")
            if record.session_id != session_id:
                raise ApprovalError("approval_session_mismatch")
            if record.task_id != plan.task.task_id:
                raise ApprovalError("approval_task_mismatch")
            if record.payload_digest != plan_digest(plan):
                raise ApprovalError("approval_payload_mismatch")
            used = record.model_copy(update={"used_at": now})
            self._records[approval_id] = used
            return used

    def invalidate(self, approval_id: UUID) -> PlanApproval:
        """Invalidate an unused approval after cancellation or correction."""

        with self._lock:
            record = self._records.get(approval_id)
            if record is None:
                raise ApprovalError("approval_not_found")
            if record.used_at is not None:
                raise ApprovalError("approval_replayed")
            if record.invalidated_at is not None:
                return record
            invalidated = record.model_copy(update={"invalidated_at": self._clock()})
            self._records[approval_id] = invalidated
            return invalidated


__all__ = [
    "ApprovalError",
    "ApprovalStore",
    "InvalidTaskTransition",
    "PlanApproval",
    "TaskLifecycle",
    "TaskState",
    "canonical_json",
    "canonical_plan_payload",
    "maximum_plan_risk",
    "plan_digest",
]
