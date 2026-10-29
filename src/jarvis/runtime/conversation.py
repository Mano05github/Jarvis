"""Text-first companion turn controller with bounded clarification state."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from jarvis.contracts import (
    ConversationTurn,
    DataClass,
    Decision,
    InteractionEnvelope,
    InteractionMode,
    LLMMessage,
    LLMPrivacyClass,
    LLMRequest,
    PendingDialogue,
    PolicyDecision,
)
from jarvis.runtime.actions import (
    ActionCompiler,
    CompiledPlan,
    PlanCompilationError,
    SimulatedPolicyGateway,
    SimulationExecutor,
    SimulationRecord,
)
from jarvis.runtime.audit import ConversationAudit, SessionCloseReason
from jarvis.runtime.control import ApprovalError, ApprovalStore, PlanApproval


class InteractionGateway(Protocol):
    def complete(self, request: LLMRequest) -> InteractionEnvelope: ...


class PendingClarificationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dialogue: PendingDialogue
    field: str
    question: str
    original_input: str


class PendingApprovalState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dialogue: PendingDialogue
    approval: PlanApproval
    compiled_plan: CompiledPlan
    policy_decisions: tuple[PolicyDecision, ...]


class TurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID
    mode: InteractionMode
    reply: str
    envelope: InteractionEnvelope
    compiled_plan: CompiledPlan | None = None
    policy_decisions: tuple[PolicyDecision, ...] = ()
    simulations: tuple[SimulationRecord, ...] = ()
    pending_dialogue: PendingDialogue | None = None
    approval: PlanApproval | None = None
    plan_rejection: str | None = None


class ConversationSession:
    """Own the trusted state transitions surrounding untrusted LLM responses."""

    def __init__(
        self,
        *,
        gateway: InteractionGateway,
        rubric: str,
        compiler: ActionCompiler | None = None,
        policy: SimulatedPolicyGateway | None = None,
        executor: SimulationExecutor | None = None,
        audit: ConversationAudit | None = None,
        session_id: UUID | None = None,
        clock: Callable[[], datetime] | None = None,
        clarification_ttl: timedelta = timedelta(minutes=5),
        approval_ttl: timedelta = timedelta(seconds=30),
        approval_store: ApprovalStore | None = None,
        maximum_history_turns: int = 16,
    ) -> None:
        if maximum_history_turns < 2 or maximum_history_turns > 24:
            raise ValueError("history bound must be between 2 and 24 turns")
        self.gateway = gateway
        self.rubric = rubric
        self.compiler = compiler or ActionCompiler()
        self.policy = policy or SimulatedPolicyGateway()
        self.executor = executor or SimulationExecutor()
        self.session_id = session_id or (audit.session_id if audit is not None else uuid4())
        if audit is not None and audit.session_id != self.session_id:
            raise ValueError("conversation and audit session IDs must match")
        self.audit = audit
        self.clock = clock or (lambda: datetime.now(UTC))
        self.clarification_ttl = clarification_ttl
        self.approval_ttl = approval_ttl
        self.approval_store = approval_store or ApprovalStore(
            secrets.token_bytes(32), clock=self.clock
        )
        self.maximum_history_turns = maximum_history_turns
        self.turns: list[ConversationTurn] = []
        self.pending: PendingClarificationState | None = None
        self.pending_approval: PendingApprovalState | None = None
        self._closed = False
        if self.audit is not None:
            self.audit.record_session_started()

    def _active_pending(self) -> PendingClarificationState | None:
        if self.pending is not None and self.pending.dialogue.expires_at <= self.clock():
            self.pending = None
        return self.pending

    def _messages(self, input_text: str) -> tuple[LLMMessage, ...]:
        recent = self.turns[-(self.maximum_history_turns - 1) :]
        return tuple(
            [LLMMessage(role=turn.role, content=turn.text) for turn in recent]
            + [LLMMessage(role="user", content=input_text)]
        )

    def _pending_dialogue(self) -> PendingDialogue | None:
        approval = self._active_pending_approval()
        if approval is not None:
            return approval.dialogue
        pending = self._active_pending()
        return pending.dialogue if pending is not None else None

    def _active_pending_approval(self) -> PendingApprovalState | None:
        if (
            self.pending_approval is not None
            and self.pending_approval.dialogue.expires_at <= self.clock()
        ):
            self.pending_approval = None
        return self.pending_approval

    def _context(self) -> dict[str, object]:
        pending = self._active_pending()
        approval = self._active_pending_approval()
        return {
            "session_id": str(self.session_id),
            "available_actions": self.compiler.available_actions,
            "pending_clarification": (
                {
                    "dialogue_id": str(pending.dialogue.dialogue_id),
                    "field": pending.field,
                    "question": pending.question,
                    "original_input": pending.original_input,
                    "expires_at": pending.dialogue.expires_at.isoformat(),
                }
                if pending is not None
                else None
            ),
            "pending_approval": (
                {
                    "dialogue_id": str(approval.dialogue.dialogue_id),
                    "approval_id": str(approval.approval.approval_id),
                    "task_id": str(approval.compiled_plan.task.task_id),
                    "risk": approval.approval.risk.value,
                    "expires_at": approval.dialogue.expires_at.isoformat(),
                }
                if approval is not None
                else None
            ),
            "execution_mode": "simulation_only",
        }

    def _remember_turn(self, role: Literal["user", "assistant"], text: str) -> None:
        if not text.strip():
            return
        self.turns.append(ConversationTurn(role=role, text=text))
        if len(self.turns) > self.maximum_history_turns:
            self.turns = self.turns[-self.maximum_history_turns :]

    def _set_pending(self, envelope: InteractionEnvelope, input_text: str) -> None:
        assert envelope.clarification is not None
        now = self.clock()
        digest = hashlib.sha256(
            f"{envelope.request_id}:{envelope.clarification.field}:{input_text}".encode()
        ).hexdigest()
        dialogue = PendingDialogue(
            request_id=envelope.request_id,
            kind="clarification",
            created_at=now,
            expires_at=now + self.clarification_ttl,
            payload_digest=digest,
        )
        self.pending = PendingClarificationState(
            dialogue=dialogue,
            field=envelope.clarification.field,
            question=envelope.clarification.question,
            original_input=input_text,
        )

    def _set_pending_approval(
        self,
        *,
        envelope: InteractionEnvelope,
        compiled: CompiledPlan,
        decisions: tuple[PolicyDecision, ...],
    ) -> PendingApprovalState:
        approval = self.approval_store.issue(
            session_id=self.session_id,
            plan=compiled,
            decisions=decisions,
            ttl=self.approval_ttl,
        )
        dialogue = PendingDialogue(
            request_id=envelope.request_id,
            kind="approval",
            created_at=approval.issued_at,
            expires_at=approval.expires_at,
            payload_digest=approval.payload_digest,
        )
        state = PendingApprovalState(
            dialogue=dialogue,
            approval=approval,
            compiled_plan=compiled,
            policy_decisions=decisions,
        )
        self.pending_approval = state
        return state

    def _invalidate_pending_approval(self) -> None:
        pending = self.pending_approval
        self.pending_approval = None
        if pending is None:
            return
        try:
            self.approval_store.invalidate(pending.approval.approval_id)
        except ApprovalError:
            pass

    def _finish(self, result: TurnResult) -> TurnResult:
        if self.audit is None:
            return result
        task_id = result.compiled_plan.task.task_id if result.compiled_plan else None
        if task_id is not None:
            for record in result.simulations:
                self.audit.record_simulation(
                    task_id=task_id,
                    intent_id=record.intent_id,
                    policy_decision_id=record.policy_decision_id,
                    action=record.action,
                    resource=record.resource,
                    disposition=record.disposition,
                )
        self.audit.record_turn_completed(
            request_id=result.envelope.request_id,
            mode=result.mode,
            pending=result.pending_dialogue is not None,
            compiled_actions=(len(result.compiled_plan.actions) if result.compiled_plan else 0),
            simulations=len(result.simulations),
            plan_rejected=result.plan_rejection is not None,
            task_id=task_id,
        )
        return result

    def close(self, reason: SessionCloseReason = "user_exit") -> None:
        if self._closed:
            return
        self._invalidate_pending_approval()
        if self.audit is not None:
            self.audit.record_session_closed(reason)
        self._closed = True

    def process(self, input_text: str) -> TurnResult:
        if self._closed:
            raise RuntimeError("conversation session is closed")
        if not input_text.strip():
            raise ValueError("turn input must be non-empty")
        request = LLMRequest(
            purpose="companion",
            system_instructions=self.rubric,
            messages=self._messages(input_text),
            response_schema="InteractionEnvelope-v1",
            context=self._context(),
            privacy_class=LLMPrivacyClass.REMOTE_ALLOWED,
            data_classes=frozenset({DataClass.PERSONAL}),
            maximum_output_tokens=500,
            deadline_ms=30_000,
        )
        if self.audit is not None:
            self.audit.record_turn_started(request.request_id)
        try:
            envelope = self.gateway.complete(request)
        except Exception:
            if self.audit is not None:
                self.audit.record_turn_failed(request.request_id)
            raise
        self._remember_turn("user", input_text)

        if envelope.mode is InteractionMode.CLARIFY:
            self._invalidate_pending_approval()
            assert envelope.clarification is not None
            self._set_pending(envelope, input_text)
            reply = envelope.clarification.question
            self._remember_turn("assistant", reply)
            return self._finish(
                TurnResult(
                    session_id=self.session_id,
                    mode=envelope.mode,
                    reply=reply,
                    envelope=envelope,
                    pending_dialogue=self.pending.dialogue if self.pending else None,
                )
            )

        if envelope.mode is InteractionMode.CANCEL:
            cancelled = self.pending is not None or self.pending_approval is not None
            self.pending = None
            self._invalidate_pending_approval()
            reply = (
                "Seri, pending request-ah cancel panniten."
                if cancelled
                else "Cancel panna pending request edhuvum illa."
            )
            self._remember_turn("assistant", reply)
            return self._finish(
                TurnResult(
                    session_id=self.session_id,
                    mode=envelope.mode,
                    reply=reply,
                    envelope=envelope,
                )
            )

        if envelope.mode is InteractionMode.CONFIRM:
            pending_approval = self._active_pending_approval()
            if pending_approval is None:
                reply = "Confirm panna pending approval edhuvum illa."
                self._remember_turn("assistant", reply)
                return self._finish(
                    TurnResult(
                        session_id=self.session_id,
                        mode=InteractionMode.NO_ACTION,
                        reply=reply,
                        envelope=envelope,
                        pending_dialogue=self._pending_dialogue(),
                    )
                )
            try:
                used = self.approval_store.consume(
                    pending_approval.approval.approval_id,
                    session_id=self.session_id,
                    plan=pending_approval.compiled_plan,
                )
            except ApprovalError as error:
                self.pending_approval = None
                reply = f"Approval use panna mudiyala: {error.code}."
                self._remember_turn("assistant", reply)
                return self._finish(
                    TurnResult(
                        session_id=self.session_id,
                        mode=InteractionMode.NO_ACTION,
                        reply=reply,
                        envelope=envelope,
                    )
                )
            approved_ids = frozenset(
                decision.intent_id
                for decision in pending_approval.policy_decisions
                if decision.decision is Decision.ASK
            )
            simulations = self.executor.execute(
                pending_approval.compiled_plan,
                pending_approval.policy_decisions,
                approved_intent_ids=approved_ids,
            )
            self.pending_approval = None
            reply = "Seri, approved action-ah simulation-la verify panniten."
            self._remember_turn("assistant", reply)
            return self._finish(
                TurnResult(
                    session_id=self.session_id,
                    mode=InteractionMode.CONFIRM,
                    reply=reply,
                    envelope=envelope,
                    compiled_plan=pending_approval.compiled_plan,
                    policy_decisions=pending_approval.policy_decisions,
                    simulations=simulations,
                    approval=used,
                )
            )

        if envelope.mode in {InteractionMode.PLAN, InteractionMode.MIXED}:
            self._invalidate_pending_approval()
            assert envelope.plan is not None
            try:
                compiled = self.compiler.compile(envelope.plan)
            except PlanCompilationError as error:
                # A plan response consumes any clarification it was answering even
                # when the trusted compiler rejects the proposed action. Keeping
                # that clarification would let a later cancellation claim that the
                # already-answered request was still pending.
                self.pending = None
                reply = "Indha action-ah safe-ah bind panna mudiyala; target-ah clarify pannunga."
                self._remember_turn("assistant", reply)
                return self._finish(
                    TurnResult(
                        session_id=self.session_id,
                        mode=InteractionMode.CLARIFY,
                        reply=reply,
                        envelope=envelope,
                        plan_rejection=str(error),
                    )
                )
            decisions = tuple(self.policy.evaluate(action.intent) for action in compiled.actions)
            simulations = self.executor.execute(compiled, decisions)
            self.pending = None
            approval_state = None
            if any(decision.decision is Decision.ASK for decision in decisions) and all(
                decision.decision is not Decision.DENY for decision in decisions
            ):
                approval_state = self._set_pending_approval(
                    envelope=envelope,
                    compiled=compiled,
                    decisions=decisions,
                )
            reply = envelope.reply if envelope.mode is InteractionMode.MIXED else ""
            if approval_state is not None:
                reply = "Indha action-ku approval venum. Confirm or cancel pannunga."
            self._remember_turn("assistant", reply)
            return self._finish(
                TurnResult(
                    session_id=self.session_id,
                    mode=envelope.mode,
                    reply=reply,
                    envelope=envelope,
                    compiled_plan=compiled,
                    policy_decisions=decisions,
                    simulations=simulations,
                    pending_dialogue=(
                        approval_state.dialogue if approval_state is not None else None
                    ),
                    approval=(approval_state.approval if approval_state is not None else None),
                )
            )

        # NO_ACTION is a terminal response to the current request. In particular,
        # it is how the gateway reports that a clarification answer was understood
        # but cannot become a registered plan. CHAT and ANSWER remain non-terminal
        # so an unrelated conversational turn does not consume a clarification.
        if envelope.mode is InteractionMode.NO_ACTION:
            self.pending = None
        reply = envelope.reply or "Seri."
        self._remember_turn("assistant", reply)
        return self._finish(
            TurnResult(
                session_id=self.session_id,
                mode=envelope.mode,
                reply=reply,
                envelope=envelope,
                pending_dialogue=self._pending_dialogue(),
            )
        )

    def snapshot(self) -> dict[str, object]:
        pending = self._active_pending()
        pending_approval = self._active_pending_approval()
        active_dialogue = self._pending_dialogue()
        return {
            "session_id": str(self.session_id),
            "turns": len(self.turns),
            "pending_dialogue_id": (
                str(active_dialogue.dialogue_id) if active_dialogue is not None else None
            ),
            "pending_field": pending.field if pending is not None else None,
            "pending_approval_id": (
                str(pending_approval.approval.approval_id) if pending_approval is not None else None
            ),
            "execution_mode": "simulation_only",
            "audit_persistence": self.audit is not None,
            "closed": self._closed,
        }


__all__ = [
    "ConversationSession",
    "InteractionGateway",
    "PendingApprovalState",
    "PendingClarificationState",
    "TurnResult",
]
