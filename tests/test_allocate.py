from __future__ import annotations

import pytest

from engine.contracts import AccountId
from engine.director.allocate import Beat, Clip, SourcePolicy, allocate, required_shot_count
from engine.edit.edl import ShotSource


def beat(index: int, tags: list[str], weight: float = 1.0) -> Beat:
    return Beat(
        id=f"b{index:02d}_beat",
        spoken="a line of narration",
        visual_intent=f"visual idea {index}",
        tags=tags,
        weight=weight,
    )


def pool() -> list[Clip]:
    clips = []
    for index in range(12):
        source = ShotSource.STOCK if index % 2 == 0 else ShotSource.GENERATED
        clips.append(
            Clip(
                path=f"clips/{index}.mp4",
                source=source,
                tags=["fog"] if index % 3 == 0 else ["city"],
                duration_seconds=6.0,
            )
        )
    return clips


def test_allocation_respects_shot_bounds() -> None:
    edl = allocate(
        AccountId.PSYCHOLOGY,
        "demo",
        [beat(i, ["fog"]) for i in range(6)],
        pool(),
        look="cinematic_psychology",
    )
    assert edl.shots
    for shot in edl.shots:
        assert shot.duration_seconds <= 3.6
        assert shot.duration_seconds >= 1.4
    assert edl.shots[0].duration_seconds <= 2.0


def test_allocation_never_reuses_a_clip() -> None:
    edl = allocate(
        AccountId.PSYCHOLOGY, "demo", [beat(i, ["city"]) for i in range(5)], pool(),
        look="cinematic_psychology",
    )
    paths = [shot.path for shot in edl.shots]
    assert len(paths) == len(set(paths))


def test_every_shot_carries_a_reason() -> None:
    edl = allocate(
        AccountId.STORYTELLING, "demo", [beat(i, ["fog"]) for i in range(4)], pool(),
        look="cinematic_storytelling",
    )
    for shot in edl.shots:
        assert len(shot.why.split()) >= 3
        assert shot.narrative_function


def test_generated_faces_are_refused() -> None:
    clips = [
        Clip(path="clips/f.mp4", source=ShotSource.GENERATED, tags=["face"],
             duration_seconds=6.0, contains_face=True),
        Clip(path="clips/s.mp4", source=ShotSource.STOCK, tags=["face"], duration_seconds=6.0),
    ]
    edl = allocate(
        AccountId.STORYTELLING, "demo", [beat(0, ["face"])], clips,
        look="cinematic_storytelling",
    )
    assert edl.shots[0].source is ShotSource.STOCK


def test_generated_faces_allowed_when_policy_says_so() -> None:
    clips = [
        Clip(path="clips/f.mp4", source=ShotSource.GENERATED, tags=["face"],
             duration_seconds=6.0, contains_face=True),
    ]
    edl = allocate(
        AccountId.STORYTELLING, "demo", [beat(0, ["face"])], clips,
        look="cinematic_storytelling", policy=SourcePolicy(allow_generated_faces=True),
    )
    assert edl.shots[0].source is ShotSource.GENERATED


def test_same_source_is_not_used_back_to_back() -> None:
    clips = [
        Clip(path="clips/a.mp4", source=ShotSource.STOCK, tags=["fog"], duration_seconds=6.0),
        Clip(path="clips/a.mp4", source=ShotSource.STOCK, tags=["fog"], duration_seconds=6.0,
             in_seconds=2.0),
        Clip(path="clips/b.mp4", source=ShotSource.STOCK, tags=["fog"], duration_seconds=6.0),
    ]
    edl = allocate(
        AccountId.PSYCHOLOGY, "demo", [beat(0, ["fog"]) for _ in range(3)], clips,
        look="cinematic_psychology",
    )
    paths = [shot.path for shot in edl.shots]
    assert len(paths) >= 2
    assert all(a != b for a, b in zip(paths, paths[1:], strict=False))


def test_dark_clips_are_avoided_when_alternatives_exist() -> None:
    clips = [
        Clip(path="clips/dark.mp4", source=ShotSource.STOCK, tags=["fog"],
             duration_seconds=6.0, mean_luma=0.04),
        Clip(path="clips/lit.mp4", source=ShotSource.STOCK, tags=["fog"],
             duration_seconds=6.0, mean_luma=0.42),
    ]
    edl = allocate(
        AccountId.PSYCHOLOGY, "demo", [beat(0, ["fog"])], clips, look="cinematic_psychology",
    )
    assert edl.shots[0].path == "clips/lit.mp4"


def test_dark_clip_is_used_when_it_is_all_that_exists() -> None:
    clips = [
        Clip(path="clips/dark.mp4", source=ShotSource.STOCK, tags=["fog"],
             duration_seconds=6.0, mean_luma=0.04),
    ]
    edl = allocate(
        AccountId.PSYCHOLOGY, "demo", [beat(0, ["fog"])], clips, look="cinematic_psychology",
    )
    assert edl.shots[0].path == "clips/dark.mp4"


def test_empty_pool_is_an_error() -> None:
    with pytest.raises(ValueError):
        allocate(AccountId.PSYCHOLOGY, "demo", [beat(0, ["fog"])], [], look="x")


def test_required_shot_count_matches_policy() -> None:
    assert required_shot_count(12.0) == 4
    assert required_shot_count(1.0) == 1


def test_slow_clip_is_speed_adjusted() -> None:
    clips = [Clip(path="clips/c.mp4", source=ShotSource.STOCK, tags=["fog"], duration_seconds=1.0)]
    edl = allocate(
        AccountId.PSYCHOLOGY, "demo", [beat(0, ["fog"])], clips, look="cinematic_psychology",
    )
    assert 0.25 <= edl.shots[0].speed <= 1.0
