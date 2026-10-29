from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from jarvis.contracts import (
    ClarificationRequest,
    InteractionEnvelope,
    InteractionMode,
    LLMRequest,
    PlanProposal,
    PlanStepProposal,
)
from jarvis.runtime import (
    ActionCompiler,
    ApprovalError,
    ConversationSession,
    PlanCompilationError,
    SimulatedPolicyGateway,
    SimulationExecutor,
)


class QueuedGateway:
    def __init__(self, responses: list[InteractionEnvelope]) -> None:
        self.responses = responses
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> InteractionEnvelope:
        self.requests.append(request)
        response = self.responses.pop(0)
        return response.model_copy(update={"request_id": request.request_id})


def envelope(mode: InteractionMode, **updates: object) -> InteractionEnvelope:
    return InteractionEnvelope(request_id=uuid4(), mode=mode, **updates)


def open_notepad_plan() -> PlanProposal:
    return PlanProposal(
        goal="Open Notepad",
        steps=(
            PlanStepProposal(
                step_id="s1",
                action="app.open",
                arguments={"application": "Notepad"},
            ),
        ),
    )


def close_notepad_plan() -> PlanProposal:
    return PlanProposal(
        goal="Close Notepad",
        steps=(
            PlanStepProposal(
                step_id="s1",
                action="app.close",
                arguments={"application": "Notepad"},
            ),
        ),
    )


def test_registered_plan_compiles_to_canonical_simulation() -> None:
    compiler = ActionCompiler()
    compiled = compiler.compile(open_notepad_plan())
    decision = SimulatedPolicyGateway().evaluate(compiled.actions[0].intent)
    records = SimulationExecutor().execute(compiled, (decision,))

    assert compiled.actions[0].intent.action == "windows.application.open"
    assert compiled.actions[0].intent.resource == "application:notepad"
    assert compiled.actions[0].intent.verification["executable"] == "notepad.exe"
    assert records[0].disposition == "would_execute"
    assert records[0].simulated is True


@pytest.mark.parametrize(
    ("action", "arguments", "message"),
    [
        ("shell.run", {"command": "whoami"}, "action is not registered"),
        ("app.open", {"application": "unknown.exe"}, "application is not registered"),
        (
            "app.open",
            {"application": "Notepad", "arguments": "secret.txt"},
            "accepts exactly one",
        ),
    ],
)
def test_compiler_rejects_unregistered_proposals(
    action: str, arguments: dict[str, str], message: str
) -> None:
    proposal = PlanProposal(
        goal="unsafe",
        steps=(PlanStepProposal(step_id="s1", action=action, arguments=arguments),),
    )

    with pytest.raises(PlanCompilationError, match=message):
        ActionCompiler().compile(proposal)


def test_clarification_answer_resumes_context_and_only_simulates() -> None:
    gateway = QueuedGateway(
        [
            envelope(
                InteractionMode.CLARIFY,
                clarification=ClarificationRequest(
                    field="application",
                    reason="application was missing",
                    question="Endha app-ah open pannanum?",
                ),
            ),
            envelope(InteractionMode.PLAN, plan=open_notepad_plan()),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")

    first = session.process("Oru app open pannu")
    second = session.process("Notepad")

    assert first.mode is InteractionMode.CLARIFY
    assert first.pending_dialogue is not None
    assert second.mode is InteractionMode.PLAN
    assert second.pending_dialogue is None
    assert second.simulations[0].disposition == "would_execute"
    assert second.simulations[0].simulated is True
    assert session.pending is None
    assert gateway.requests[1].context["pending_clarification"] is not None
    assert [message.role for message in gateway.requests[1].messages] == [
        "user",
        "assistant",
        "user",
    ]


def test_unrelated_chat_does_not_consume_pending_clarification() -> None:
    gateway = QueuedGateway(
        [
            envelope(
                InteractionMode.CLARIFY,
                clarification=ClarificationRequest(
                    field="target",
                    reason="target missing",
                    question="Edha close pannanum?",
                ),
            ),
            envelope(InteractionMode.CHAT, reply="Seri, vera vishayam pesalam."),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")

    session.process("Adha close pannu")
    result = session.process("Enaku bore adikudhu")

    assert result.mode is InteractionMode.CHAT
    assert result.pending_dialogue is not None
    assert session.pending is not None


def test_unsupported_clarification_answer_clears_pending_state() -> None:
    gateway = QueuedGateway(
        [
            envelope(
                InteractionMode.CLARIFY,
                clarification=ClarificationRequest(
                    field="application",
                    reason="application was missing",
                    question="Endha app-ah close pannanum?",
                ),
            ),
            envelope(
                InteractionMode.NO_ACTION,
                reply=(
                    "Calculator-ah close panna registered action available illa, "
                    "adhanala execute panna mudiyadhu."
                ),
            ),
            envelope(InteractionMode.CANCEL),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")

    session.process("Oru app-ah close pannu")
    unavailable = session.process("Calculator")
    cancellation = session.process("Illa vendam, cancel pannu")

    assert unavailable.mode is InteractionMode.NO_ACTION
    assert unavailable.pending_dialogue is None
    assert session.pending is None
    assert cancellation.reply == "Cancel panna pending request edhuvum illa."


def test_cancel_clears_pending_with_verified_controller_reply() -> None:
    gateway = QueuedGateway(
        [
            envelope(
                InteractionMode.CLARIFY,
                clarification=ClarificationRequest(
                    field="target",
                    reason="target missing",
                    question="Edha close pannanum?",
                ),
            ),
            envelope(InteractionMode.CANCEL, reply="Maybe cancelled"),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")
    session.process("Adha close pannu")

    result = session.process("Illa vendam, cancel pannu")

    assert result.reply == "Seri, pending request-ah cancel panniten."
    assert result.simulations == ()
    assert session.pending is None


def test_unbound_plan_fails_closed_without_simulation() -> None:
    unsafe = PlanProposal(
        goal="Run a shell",
        steps=(
            PlanStepProposal(step_id="s1", action="shell.run", arguments={"command": "whoami"}),
        ),
    )
    session = ConversationSession(
        gateway=QueuedGateway([envelope(InteractionMode.PLAN, plan=unsafe)]),
        rubric="Return JSON.",
    )

    result = session.process("Run whoami")

    assert result.mode is InteractionMode.CLARIFY
    assert result.plan_rejection == "action is not registered: shell.run"
    assert result.simulations == ()


def test_rejected_plan_consumes_clarification_it_was_answering() -> None:
    unsafe = PlanProposal(
        goal="Close Calculator",
        steps=(
            PlanStepProposal(
                step_id="s1",
                action="app.force_close",
                arguments={"application": "Calculator"},
            ),
        ),
    )
    gateway = QueuedGateway(
        [
            envelope(
                InteractionMode.CLARIFY,
                clarification=ClarificationRequest(
                    field="application",
                    reason="application was missing",
                    question="Endha app-ah close pannanum?",
                ),
            ),
            envelope(InteractionMode.PLAN, plan=unsafe),
            envelope(InteractionMode.CANCEL),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")

    session.process("Oru app-ah close pannu")
    rejected = session.process("Calculator")
    cancellation = session.process("Illa vendam, cancel pannu")

    assert rejected.plan_rejection == "action is not registered: app.force_close"
    assert rejected.pending_dialogue is None
    assert rejected.simulations == ()
    assert session.pending is None
    assert cancellation.reply == "Cancel panna pending request edhuvum illa."


def test_pending_clarification_expires() -> None:
    current = [datetime(2026, 10, 12, tzinfo=UTC)]
    gateway = QueuedGateway(
        [
            envelope(
                InteractionMode.CLARIFY,
                clarification=ClarificationRequest(
                    field="target",
                    reason="target missing",
                    question="Edha close pannanum?",
                ),
            ),
            envelope(InteractionMode.CHAT, reply="Vanakkam."),
        ]
    )
    session = ConversationSession(
        gateway=gateway,
        rubric="Return JSON.",
        clock=lambda: current[0],
        clarification_ttl=timedelta(seconds=30),
    )
    session.process("Adha close pannu")
    current[0] += timedelta(seconds=31)

    result = session.process("Hello")

    assert result.pending_dialogue is None
    assert gateway.requests[1].context["pending_clarification"] is None


def test_close_plan_requires_digest_bound_confirmation() -> None:
    gateway = QueuedGateway(
        [
            envelope(InteractionMode.PLAN, plan=close_notepad_plan()),
            envelope(InteractionMode.CONFIRM),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")

    proposed = session.process("Notepad-ah close pannu")
    confirmed = session.process("Confirm")

    assert proposed.pending_dialogue is not None
    assert proposed.pending_dialogue.kind == "approval"
    assert proposed.approval is not None
    assert proposed.simulations[0].disposition == "approval_required"
    assert confirmed.approval is not None
    assert confirmed.approval.used_at is not None
    assert confirmed.simulations[0].disposition == "would_execute"
    assert session.pending_approval is None
    assert gateway.requests[1].context["pending_approval"] is not None


def test_cancel_invalidates_pending_approval() -> None:
    gateway = QueuedGateway(
        [
            envelope(InteractionMode.PLAN, plan=close_notepad_plan()),
            envelope(InteractionMode.CANCEL),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")
    proposed = session.process("Notepad-ah close pannu")
    assert proposed.approval is not None

    cancelled = session.process("Cancel")

    assert cancelled.reply == "Seri, pending request-ah cancel panniten."
    assert session.pending_approval is None
    with pytest.raises(ApprovalError, match="approval_invalidated"):
        session.approval_store.consume(
            proposed.approval.approval_id,
            session_id=session.session_id,
            plan=proposed.compiled_plan,
        )


def test_corrected_plan_invalidates_old_approval() -> None:
    gateway = QueuedGateway(
        [
            envelope(InteractionMode.PLAN, plan=close_notepad_plan()),
            envelope(InteractionMode.PLAN, plan=open_notepad_plan()),
        ]
    )
    session = ConversationSession(gateway=gateway, rubric="Return JSON.")
    old = session.process("Notepad-ah close pannu")
    assert old.approval is not None
    assert old.compiled_plan is not None

    corrected = session.process("Illa, open pannu")

    assert corrected.simulations[0].disposition == "would_execute"
    with pytest.raises(ApprovalError, match="approval_invalidated"):
        session.approval_store.consume(
            old.approval.approval_id,
            session_id=session.session_id,
            plan=old.compiled_plan,
        )


def test_expired_approval_cannot_be_confirmed() -> None:
    current = [datetime(2026, 10, 18, tzinfo=UTC)]
    gateway = QueuedGateway(
        [
            envelope(InteractionMode.PLAN, plan=close_notepad_plan()),
            envelope(InteractionMode.CONFIRM),
        ]
    )
    session = ConversationSession(
        gateway=gateway,
        rubric="Return JSON.",
        clock=lambda: current[0],
        approval_ttl=timedelta(seconds=10),
    )
    session.process("Notepad-ah close pannu")
    current[0] += timedelta(seconds=10)

    result = session.process("Confirm")

    assert result.mode is InteractionMode.NO_ACTION
    assert result.simulations == ()
    assert result.reply == "Confirm panna pending approval edhuvum illa."
