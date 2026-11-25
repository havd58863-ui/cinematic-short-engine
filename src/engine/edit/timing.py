"""Cut to the voice.

Shot length comes from the spoken sentence, not from a pacing template: a line
that takes 3.4 seconds gets a 3.4 second shot. This is the difference between an
edit that follows the narration and footage that merely plays underneath it.
"""

from __future__ import annotations

import dataclasses
import math

from engine.director.allocate import Beat, Clip, SourcePolicy
from engine.edit.edl import Shot

BREATH = 0.22
MAX_SHOT = 6.2
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
    usage: dict[str, int] = {}
    last_path: str | None = None
    cursor = 0.0
    planned: list[PlannedShot] = []

    for index, entry in enumerate(beats):
        needed = min(MAX_SHOT, max(MIN_SHOT, round(entry.duration, 3)))
        # A sentence longer than the retention ceiling earns extra cuts inside it,
        # while the narration keeps running across them.
        cuts = max(1, math.ceil(needed / policy.max_shot_seconds))
        piece = round(needed / cuts, 3)
        offset = 0.0
        for cut in range(cuts):
            length = needed - offset if cut == cuts - 1 else piece
            if last_path and len({clip.path for clip in pool}) > 1:
                fresh = [clip for clip in pool if clip.path != last_path]
            else:
                fresh = list(pool)
            # Spread reuse evenly: only clips at the lowest usage count compete on
            # relevance, so a well-tagged clip cannot carry a third of the film.
            floor = min(usage.get(clip.path, 0) for clip in fresh)
            candidates = [clip for clip in fresh if usage.get(clip.path, 0) == floor]
            chosen = max(candidates, key=lambda clip: _score(entry.beat, clip, policy))
            usage[chosen.path] = usage.get(chosen.path, 0) + 1

            speed = 1.0
            available = chosen.duration_seconds - 0.1
            if available < length:
                speed = max(0.6, round(available / length, 3))
            start = _in_point(chosen, length * speed, index + cut)

            shot = Shot(
                id=f"s{index:02d}{chr(97 + cut)}_{entry.beat.id}"[:40],
                source=chosen.source,
                path=chosen.path,
                start_seconds=start,
                duration_seconds=round(length, 3),
                speed=speed,
                why=entry.beat.visual_intent,
                narrative_function=entry.beat.id,
            )
            words = (
                tuple(
                    TimedWord(word.text, round(cursor + word.start, 3), round(cursor + word.end, 3))
                    for word in entry.words
                )
                if cut == 0
                else ()
            )
            planned.append(
                PlannedShot(shot=shot, timeline_start=round(cursor + offset, 3), words=words)
            )
            last_path = chosen.path
            offset += length
        cursor += needed

    return planned
