"""Edit Decision List: the typed contract between direction and the renderer.

Every shot carries `why` and `narrative_function`. The renderer refuses an EDL
that violates the house rule, so a shot cannot enter a video by accident.
"""

from __future__ import annotations

import pathlib
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from engine.contracts import AccountId, StrictModel


class ShotSource(StrEnum):
    STOCK = "stock"          # licensed real footage (Pexels/Pixabay)
    GENERATED = "generated"  # AI video (Wan/LTX/API) — real motion, not stills
    PLATE = "plate"          # abstract/atmospheric generated plate
    TITLE = "title"          # typographic beat


class Transition(StrEnum):
    CUT = "cut"
    DIP = "dip"
    CROSSFADE = "crossfade"


class Shot(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    source: ShotSource
    path: str = Field(min_length=1)
    start_seconds: float = Field(default=0.0, ge=0.0)
    duration_seconds: float = Field(gt=0.0, le=12.0)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    why: str = Field(min_length=12, max_length=1000)
    narrative_function: str = Field(min_length=3, max_length=300)
    transition: Transition = Transition.CUT

    @field_validator("why")
    @classmethod
    def why_must_explain(cls, value: str) -> str:
        if len(value.split()) < 3:
            raise ValueError("why must be a real explanation of at least three words")
        return value


class AudioPlan(StrictModel):
    voice_path: str | None = None
    music_path: str | None = None
    music_gain_db: float = Field(default=-26.0, ge=-60.0, le=6.0)
    sfx_paths: list[str] = Field(default_factory=list)
    sfx_gain_db: float = Field(default=-14.0, ge=-60.0, le=6.0)
    target_lufs: float = Field(default=-14.0, ge=-30.0, le=-6.0)
    true_peak_db: float = Field(default=-1.5, ge=-6.0, le=0.0)


class EDL(StrictModel):
    account: AccountId
    title: str = Field(min_length=1, max_length=120)
    look: str = Field(default="")
    width: int = 1080
    height: int = 1920
    fps: int = 30
    shots: list[Shot] = Field(min_length=1)
    audio: AudioPlan = Field(default_factory=AudioPlan)
    subtitle_path: str | None = None

    @model_validator(mode="after")
    def shot_ids_are_unique(self) -> EDL:
        ids = [shot.id for shot in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError("shot ids must be unique")
        return self

    def duration_seconds(self) -> float:
        return round(sum(shot.duration_seconds for shot in self.shots), 3)

    def source_mix(self) -> dict[str, float]:
        total = self.duration_seconds() or 1.0
        mix: dict[str, float] = {}
        for shot in self.shots:
            mix[shot.source.value] = mix.get(shot.source.value, 0.0) + shot.duration_seconds / total
        return {key: round(value, 3) for key, value in mix.items()}

    def resolve(self, base: pathlib.Path) -> EDL:
        """Return a copy whose media paths are absolute against `base`."""
        def absolute(value: str | None) -> str | None:
            if value is None:
                return None
            path = pathlib.Path(value)
            return str(path if path.is_absolute() else (base / path).resolve())

        data = self.model_dump()
        for shot in data["shots"]:
            shot["path"] = absolute(shot["path"])
        for key in ("voice_path", "music_path"):
            data["audio"][key] = absolute(data["audio"][key])
        data["subtitle_path"] = absolute(data["subtitle_path"])
        data["audio"]["sfx_paths"] = [absolute(item) for item in data["audio"]["sfx_paths"]]
        return EDL(**data)
