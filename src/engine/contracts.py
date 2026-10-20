"""Typed inter-stage contracts.

Every creative element that can enter a video must carry a written reason.
The ElementDecision model enforces that rule before editing or generation.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountId(StrEnum):
    PSYCHOLOGY = "account_01_psychology"
    STORYTELLING = "account_02_storytelling"


class StageName(StrEnum):
    ACCOUNT_LOCK = "00_account_lock"
    SIGNAL_GATHER = "01_signal_gather"
    IDEA_ANALYSIS = "02_idea_analysis"
    IDEA_SELECTION = "03_idea_selection"
    SCRIPT = "04_script"
    DIRECTION = "05_direction"
    GENERATION = "06_generation"
    VOICE = "07_voice"
    EDIT = "08_edit"
    QUALITY = "09_quality"
    DELIVERY = "10_delivery"


class StageStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


class ElementKind(StrEnum):
    SHOT = "shot"
    CAMERA_MOVE = "camera_move"
    TRANSITION = "transition"
    SFX = "sfx"
    MUSIC_CUE = "music_cue"
    SILENCE = "silence"
    TEXT = "text"
    COLOR = "color"


class RunRequest(StrictModel):
    account: AccountId
    requested_by: str = Field(min_length=1, max_length=120)
    brief: str | None = Field(default=None, max_length=4000)
    dry_run: bool = False


class ElementDecision(StrictModel):
    kind: ElementKind
    name: str = Field(min_length=1, max_length=120)
    why: str = Field(min_length=12, max_length=1000)
    narrative_function: str = Field(min_length=3, max_length=300)
    start_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("why")
    @classmethod
    def why_must_explain(cls, value: str) -> str:
        words = value.split()
        if len(words) < 3:
            raise ValueError("why must be a real explanation of at least three words")
        return value


class StageResult(StrictModel):
    stage: StageName
    status: StageStatus
    artifacts: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def failed_stage_must_name_the_error(self) -> StageResult:
        if self.status is StageStatus.FAILED and not self.error:
            raise ValueError("A failed stage must carry a named error; silent downgrade is forbidden")
        if self.status is StageStatus.COMPLETED and self.error:
            raise ValueError("A completed stage cannot also carry an error")
        return self
