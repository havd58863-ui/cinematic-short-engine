import pytest
from pydantic import ValidationError

from engine.contracts import AccountId, ElementDecision, RunRequest, StageName, StageResult, StageStatus


def test_run_request_requires_a_valid_account() -> None:
    request = RunRequest(account=AccountId.PSYCHOLOGY, requested_by="owner")
    assert request.account is AccountId.PSYCHOLOGY
    with pytest.raises(ValidationError):
        RunRequest(account="unknown", requested_by="owner")


def test_every_element_must_justify_itself() -> None:
    valid = ElementDecision(
        kind="transition",
        name="soft dissolve",
        why="Moves from uncertainty into the mechanism without breaking the dreamlike mood.",
        narrative_function="bridge hook to mechanism",
    )
    assert valid.kind.value == "transition"

    with pytest.raises(ValidationError):
        ElementDecision(
            kind="transition",
            name="random spin",
            why="looks cool",
            narrative_function="decoration",
        )


def test_failed_stage_cannot_hide_its_error() -> None:
    with pytest.raises(ValidationError):
        StageResult(stage=StageName.GENERATION, status=StageStatus.FAILED)

    named = StageResult(
        stage=StageName.GENERATION,
        status=StageStatus.FAILED,
        error="Reactor smoke returned no video track",
    )
    assert named.error
