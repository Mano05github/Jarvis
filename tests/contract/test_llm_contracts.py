from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from jarvis.contracts import (
    ClarificationRequest,
    InteractionEnvelope,
    InteractionMode,
    PendingDialogue,
    PlanProposal,
    PlanStepProposal,
)


def test_casual_chat_cannot_smuggle_an_action_plan() -> None:
    with pytest.raises(ValidationError, match="non-plan interaction"):
        InteractionEnvelope(
            request_id=uuid4(),
            mode=InteractionMode.CHAT,
            reply="Pesalam.",
            plan=PlanProposal(
                goal="Open Notepad",
                steps=(PlanStepProposal(step_id="one", action="app.open"),),
            ),
        )


def test_clarification_requires_one_typed_question() -> None:
    request_id = uuid4()
    envelope = InteractionEnvelope(
        request_id=request_id,
        mode=InteractionMode.CLARIFY,
        reply="Endha application?",
        clarification=ClarificationRequest(
            field="application",
            reason="missing target",
            question="Endha application open pannanum?",
        ),
    )

    assert envelope.authority == "none"
    assert envelope.clarification is not None
    assert envelope.clarification.field == "application"


def test_plan_rejects_unknown_or_cyclic_dependencies() -> None:
    with pytest.raises(ValidationError, match="unknown step"):
        PlanProposal(
            goal="Open and inspect",
            steps=(
                PlanStepProposal(step_id="inspect", action="file.inspect", depends_on=("open",)),
            ),
        )

    with pytest.raises(ValidationError, match="cycle"):
        PlanProposal(
            goal="Cyclic fixture",
            steps=(
                PlanStepProposal(step_id="one", action="one", depends_on=("two",)),
                PlanStepProposal(step_id="two", action="two", depends_on=("one",)),
            ),
        )


def test_pending_dialogue_must_expire() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="expire after creation"):
        PendingDialogue(
            request_id=uuid4(),
            kind="approval",
            created_at=now,
            expires_at=now - timedelta(seconds=1),
            payload_digest="digest",
        )
