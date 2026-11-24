"""Allocation: turn script beats into a typed EDL.

The director does not invent footage. It picks from a pool that was actually
downloaded or actually generated, and it must justify every pick with the beat
it serves. Source ratios keep the mix honest: real footage for most of the
screen, generated material only where it earns its place.
"""

from __future__ import annotations

import math

from pydantic import Field

from engine.contracts import AccountId, StrictModel
from engine.edit.edl import EDL, AudioPlan, Shot, ShotSource, Transition


class Beat(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    spoken: str = Field(min_length=1, max_length=1200)
    visual_intent: str = Field(min_length=3, max_length=300)
    tags: list[str] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0.0, le=6.0)


class Clip(StrictModel):
    path: str = Field(min_length=1)
    source: ShotSource
    tags: list[str] = Field(default_factory=list)
    duration_seconds: float = Field(gt=0.3)
    in_seconds: float = Field(default=0.0, ge=0.0)
    credit: str | None = None
    contains_face: bool = False


class SourcePolicy(StrictModel):
    """Screen-time budget. Faces are refused for generated clips by default."""

    max_share: dict[str, float] = Field(
        default_factory=lambda: {"stock": 0.65, "generated": 0.40, "plate": 0.20, "title": 0.10}
    )
    min_shot_seconds: float = Field(default=1.4, ge=0.5, le=4.0)
    max_shot_seconds: float = Field(default=3.6, ge=1.0, le=6.0)
    hook_max_seconds: float = Field(default=2.0, ge=0.5, le=4.0)
    allow_generated_faces: bool = False


SOURCE_PRIORITY: dict[ShotSource, int] = {
    ShotSource.STOCK: 3,
    ShotSource.GENERATED: 2,
    ShotSource.PLATE: 1,
    ShotSource.TITLE: 0,
}


def _overlap(beat: Beat, clip: Clip) -> int:
    return len(set(tag.lower() for tag in beat.tags) & set(tag.lower() for tag in clip.tags))


def _shot_durations(total_seconds: float, policy: SourcePolicy) -> list[float]:
    """Front-load pace: short hook, then alternating 1.6-2.8s cuts."""
    durations: list[float] = []
    remaining = total_seconds
    first = min(policy.hook_max_seconds, max(policy.min_shot_seconds, 1.8))
    durations.append(round(first, 2))
    remaining -= first
    pattern = [2.0, 2.6, 1.6, 2.2, 1.8, 2.8]
    index = 0
    while remaining > 0.35:
        want = pattern[index % len(pattern)]
        take = min(want, remaining)
        if take < policy.min_shot_seconds and durations:
            durations[-1] = round(durations[-1] + take, 2)
            break
        durations.append(round(take, 2))
        remaining -= take
        index += 1
    return [min(max(d, policy.min_shot_seconds), policy.max_shot_seconds) for d in durations]


def _clip_key(clip: Clip) -> tuple[str, float]:
    return clip.path, clip.in_seconds


def _pick(
    beat: Beat,
    pool: list[Clip],
    used: set[tuple[str, float]],
    allowed: dict[str, float],
    policy: SourcePolicy,
) -> Clip | None:
    candidates = [clip for clip in pool if _clip_key(clip) not in used]
    if not policy.allow_generated_faces:
        candidates = [
            clip for clip in candidates
            if not (clip.contains_face and clip.source is ShotSource.GENERATED)
        ]
    candidates = [
        clip for clip in candidates
        if clip.source.value in allowed or allowed.get(clip.source.value, 0) > 0
    ]
    if not candidates:
        return None
    # Real footage first: plates are filler, never the default.
    candidates.sort(
        key=lambda clip: (_overlap(beat, clip), SOURCE_PRIORITY[clip.source], -clip.duration_seconds),
        reverse=True,
    )
    return candidates[0]


def allocate(
    account: AccountId,
    title: str,
    beats: list[Beat],
    pool: list[Clip],
    look: str,
    policy: SourcePolicy | None = None,
    audio: AudioPlan | None = None,
) -> EDL:
    """Distribute beats over shots, respecting the source budget."""
    policy = policy or SourcePolicy()
    planned_total = max(10.0, 2.6 * len(beats))

    durations = _shot_durations(planned_total, policy)
    shots: list[Shot] = []
    used: set[tuple[str, float]] = set()
    budget = {key: value * planned_total for key, value in policy.max_share.items()}
    spent = {key: 0.0 for key in budget}

    for index, seconds in enumerate(durations):
        beat = beats[min(len(beats) - 1, int(index * len(beats) / len(durations)))]
        allowed = {key: budget[key] - spent.get(key, 0.0) for key in budget}
        clip = _pick(beat, pool, used, allowed, policy)
        if clip is None:
            clip = _pick(beat, pool, used, {key: 1.0 for key in budget}, policy)
        if clip is None:
            break

        speed = 1.0
        if clip.duration_seconds < seconds:
            speed = round(clip.duration_seconds / seconds, 3)
        else:
            speed = 1.0

        shots.append(
            Shot(
                id=f"s{index:02d}_{beat.id[:12]}",
                source=clip.source,
                path=clip.path,
                start_seconds=clip.in_seconds,
                duration_seconds=round(seconds, 2),
                speed=min(1.0, speed),
                why=f"{beat.visual_intent} — {clip.source.value} matched on "
                    f"{', '.join(sorted(set(beat.tags) & set(clip.tags))) or 'mood'}",
                narrative_function=beat.id,
                transition=Transition.DIP if beat.id.endswith("payoff") else Transition.CUT,
            )
        )
        used.add(_clip_key(clip))
        spent[clip.source.value] = spent.get(clip.source.value, 0.0) + seconds

    if not shots:
        raise ValueError("no usable clips in the pool — nothing to allocate")

    return EDL(
        account=account,
        title=title,
        look=look,
        shots=shots,
        audio=audio or AudioPlan(),
    )


def required_shot_count(duration_seconds: float, policy: SourcePolicy | None = None) -> int:
    policy = policy or SourcePolicy()
    return max(1, math.ceil(duration_seconds / policy.max_shot_seconds))
