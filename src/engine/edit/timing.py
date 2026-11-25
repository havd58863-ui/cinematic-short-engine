"""Cut to the voice.

Shot length comes from the spoken sentence, not from a pacing template: a line
that takes 3.4 seconds gets a 3.4 second shot. This is the difference between an
edit that follows the narration and footage that merely plays underneath it.
"""

from __future__ import annotations

import dataclasses

from engine.director.allocate import Beat, Clip, SourcePolicy
from engine.edit.edl import Shot

BREATH = 0.22
MAX_SHOT = 8.0
MIN_SHOT = 1.2


@dataclasses.dataclass(frozen=True)
class TimedWord:
    text: str
    start: float
    end: float


@dataclasses.dataclass(frozen=True)
class BeatAudio:
    beat: Beat
    duration: float
    words: tuple[TimedWord, ...] = ()


@dataclasses.dataclass(frozen=True)
class PlannedShot:
    shot: Shot
    timeline_start: float
    words: tuple[TimedWord, ...]


def _score(beat: Beat, clip: Clip, policy: SourcePolicy) -> float:
    overlap = len(set(tag.lower() for tag in beat.tags) & set(tag.lower() for tag in clip.tags))
    score = overlap * 3.0
    if clip.mean_luma is not None:
        if policy.min_luma is not None and clip.mean_luma < policy.min_luma:
            score -= 4.0
        elif clip.mean_luma > 0.72:
            score -= 1.0
    return score


def _in_point(clip: Clip, needed: float, index: int) -> float:
    if clip.duration_seconds <= needed + 0.8:
        return 0.0
    return round(min(0.6 + 0.15 * (index % 4), clip.duration_seconds - needed - 0.4), 3)


def plan_shots(
    beats: list[BeatAudio],
    pool: list[Clip],
    policy: SourcePolicy | None = None,
) -> list[PlannedShot]:
    if not beats:
        raise ValueError("at least one beat is required")
    if not pool:
        raise ValueError("at least one clip is required")
    policy = policy or SourcePolicy()
    used: set[str] = set()
    last_path: str | None = None
    cursor = 0.0
    planned: list[PlannedShot] = []

    for index, entry in enumerate(beats):
        needed = min(MAX_SHOT, max(MIN_SHOT, round(entry.duration + BREATH, 3)))
        candidates = [clip for clip in pool if clip.path not in used] or list(pool)
        if last_path and len({clip.path for clip in candidates}) > 1:
            candidates = [clip for clip in candidates if clip.path != last_path]
        chosen = max(candidates, key=lambda clip: _score(entry.beat, clip, policy))

        speed = 1.0
        available = chosen.duration_seconds - 0.1
        if available < needed:
            speed = max(0.6, round(available / needed, 3))
        start = _in_point(chosen, needed * speed, index)

        shot = Shot(
            id=f"s{index:02d}_{entry.beat.id}"[:40],
            source=chosen.source,
            path=chosen.path,
            start_seconds=start,
            duration_seconds=needed,
            speed=speed,
            why=entry.beat.visual_intent,
            narrative_function=entry.beat.id,
        )
        words = tuple(
            TimedWord(word.text, round(cursor + word.start, 3), round(cursor + word.end, 3))
            for word in entry.words
        )
        planned.append(PlannedShot(shot=shot, timeline_start=round(cursor, 3), words=words))
        cursor += needed
        used.add(chosen.path)
        last_path = chosen.path

    return planned
