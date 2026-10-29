from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from jarvis.contracts import Decision, PlanProposal, PlanStepProposal, PolicyDecision, RiskLevel
from jarvis.runtime import (
    ActionCompiler,
    ApprovalError,
    ApprovalStore,
    InvalidTaskTransition,
    TaskLifecycle,
    TaskState,
    maximum_plan_risk,
    plan_digest,
)


def compiled_plan(application: str = "notepad"):
    return ActionCompiler().compile(
        PlanProposal(
            goal=f"Open {application}",
            steps=(
                PlanStepProposal(
                    step_id="open",
                    action="app.open",
                    arguments={"application": application},
                ),
            ),
        )
    )


def decision_for(plan, risk: RiskLevel = RiskLevel.R2) -> PolicyDecision:
    return PolicyDecision(
        intent_id=plan.actions[0].intent.intent_id,
        decision=Decision.ASK,
        risk=risk,
        reasons=("owner approval required",),
        policy_bundle_version="test-v1",
    )


def test_lifecycle_happy_path_and_terminal_guard() -> None:
    lifecycle = TaskLifecycle()
    for state in (
        TaskState.INTERPRETING,
        TaskState.PLANNING,
        TaskState.AWAITING_APPROVAL,
        TaskState.EXECUTING,
        TaskState.VERIFYING,
        TaskState.COMPLETED,
    ):
        assert lifecycle.transition(state) is state

    assert lifecycle.terminal is True
    with pytest.raises(InvalidTaskTransition, match="cannot transition"):
        lifecycle.transition(TaskState.IDLE)


@pytest.mark.parametrize(
    "state",
    [
        state
        for state in TaskState
        if state not in {TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED}
    ],
)
def test_every_active_state_can_cancel(state: TaskState) -> None:
    lifecycle = TaskLifecycle()
    routes = {
        TaskState.IDLE: (),
        TaskState.INTERPRETING: (TaskState.INTERPRETING,),
        TaskState.CLARIFYING: (TaskState.INTERPRETING, TaskState.CLARIFYING),
        TaskState.PLANNING: (TaskState.INTERPRETING, TaskState.PLANNING),
        TaskState.AWAITING_APPROVAL: (
            TaskState.INTERPRETING,
            TaskState.PLANNING,
            TaskState.AWAITING_APPROVAL,
        ),
        TaskState.EXECUTING: (
            TaskState.INTERPRETING,
            TaskState.PLANNING,
            TaskState.EXECUTING,
        ),
        TaskState.VERIFYING: (
            TaskState.INTERPRETING,
            TaskState.PLANNING,
            TaskState.EXECUTING,
            TaskState.VERIFYING,
        ),
    }
    for target in routes[state]:
        lifecycle.transition(target)
    assert lifecycle.cancel() is TaskState.CANCELLED


def test_correction_route_returns_to_interpreting() -> None:
    lifecycle = TaskLifecycle()
    lifecycle.transition(TaskState.INTERPRETING)
    lifecycle.transition(TaskState.PLANNING)
    lifecycle.transition(TaskState.AWAITING_APPROVAL)

    assert lifecycle.transition(TaskState.INTERPRETING) is TaskState.INTERPRETING


def test_plan_digest_is_deterministic_and_action_bound() -> None:
    plan = compiled_plan()
    assert plan_digest(plan) == plan_digest(plan)
    changed = plan.model_copy(
        update={
            "actions": (
                plan.actions[0].model_copy(
                    update={
                        "intent": plan.actions[0].intent.model_copy(
                            update={"resource": "application:calculator"}
                        )
                    }
                ),
            )
        }
    )
    assert plan_digest(changed) != plan_digest(plan)


def test_maximum_risk_requires_exact_decision_coverage() -> None:
    plan = compiled_plan()
    decision = decision_for(plan, RiskLevel.R3)
    assert maximum_plan_risk(plan, (decision,)) is RiskLevel.R3

    with pytest.raises(ValueError, match="duplicate"):
        maximum_plan_risk(plan, (decision, decision))
    with pytest.raises(ValueError, match="exactly cover"):
        maximum_plan_risk(plan, ())


def test_approval_is_single_use_and_bound_to_session_task_and_payload() -> None:
    now = [datetime(2026, 10, 18, 10, tzinfo=UTC)]
    plan = compiled_plan()
    session_id = uuid4()
    store = ApprovalStore(b"a" * 32, clock=lambda: now[0])
    approval = store.issue(
        session_id=session_id,
        plan=plan,
        decisions=(decision_for(plan),),
    )

    used = store.consume(approval.approval_id, session_id=session_id, plan=plan)
    assert used.used_at == now[0]
    with pytest.raises(ApprovalError, match="approval_replayed"):
        store.consume(approval.approval_id, session_id=session_id, plan=plan)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("session", "approval_session_mismatch"),
        ("task", "approval_task_mismatch"),
        ("payload", "approval_payload_mismatch"),
    ],
)
def test_approval_rejects_binding_mismatches(mutation: str, code: str) -> None:
    now = datetime(2026, 10, 18, 10, tzinfo=UTC)
    plan = compiled_plan()
    session_id = uuid4()
    store = ApprovalStore(b"b" * 32, clock=lambda: now)
    approval = store.issue(
        session_id=session_id,
        plan=plan,
        decisions=(decision_for(plan),),
    )
    candidate = plan
    candidate_session = session_id
    if mutation == "session":
        candidate_session = uuid4()
    elif mutation == "task":
        changed_task = plan.task.model_copy(update={"task_id": uuid4()})
        candidate = plan.model_copy(update={"task": changed_task})
    else:
        candidate = plan.model_copy(
            update={"task": plan.task.model_copy(update={"goal": "Changed after approval"})}
        )

    with pytest.raises(ApprovalError, match=code):
        store.consume(
            approval.approval_id,
            session_id=candidate_session,
            plan=candidate,
        )


def test_expired_and_invalidated_approvals_fail_closed() -> None:
    now = [datetime(2026, 10, 18, 10, tzinfo=UTC)]
    plan = compiled_plan()
    session_id = uuid4()
    store = ApprovalStore(b"c" * 32, clock=lambda: now[0])
    expired = store.issue(
        session_id=session_id,
        plan=plan,
        decisions=(decision_for(plan),),
        ttl=timedelta(seconds=1),
    )
    now[0] += timedelta(seconds=1)
    with pytest.raises(ApprovalError, match="approval_expired"):
        store.consume(expired.approval_id, session_id=session_id, plan=plan)

    active = store.issue(
        session_id=session_id,
        plan=plan,
        decisions=(decision_for(plan),),
    )
    store.invalidate(active.approval_id)
    with pytest.raises(ApprovalError, match="approval_invalidated"):
        store.consume(active.approval_id, session_id=session_id, plan=plan)


def test_approval_configuration_fails_closed() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        ApprovalStore(b"short")

    plan = compiled_plan()
    store = ApprovalStore(b"d" * 32)
    with pytest.raises(ValueError, match="TTL"):
        store.issue(
            session_id=uuid4(),
            plan=plan,
            decisions=(decision_for(plan),),
            ttl=timedelta(0),
        )
    with pytest.raises(ApprovalError, match="approval_not_found"):
        store.consume(uuid4(), session_id=uuid4(), plan=plan)
