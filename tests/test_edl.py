from __future__ import annotations

import pathlib

import pytest

from engine.contracts import AccountId
from engine.edit.edl import EDL, AudioPlan, Shot, ShotSource


def make_shot(**overrides) -> Shot:
    data = {
        "id": "s01_hook",
        "source": ShotSource.STOCK,
        "path": "clips/a.mp4",
        "duration_seconds": 2.0,
        "why": "opens on a lonely silhouette to trigger recognition",
        "narrative_function": "hook",
    }
    data.update(overrides)
    return Shot(**data)


def make_edl(shots: list[Shot] | None = None) -> EDL:
    return EDL(
        account=AccountId.PSYCHOLOGY,
        title="demo",
        shots=shots or [make_shot(), make_shot(id="s02_turn", duration_seconds=2.4)],
    )


def test_shot_requires_a_real_reason() -> None:
    with pytest.raises(ValueError):
        make_shot(why="nice")


def test_shot_ids_must_be_unique() -> None:
    with pytest.raises(ValueError):
        make_edl([make_shot(), make_shot()])


def test_duration_and_source_mix() -> None:
    edl = make_edl(
        [
            make_shot(id="s01_hook", duration_seconds=3.0),
            make_shot(id="s02_b", source=ShotSource.GENERATED, duration_seconds=1.0),
        ]
    )
    assert edl.duration_seconds() == 4.0
    assert edl.source_mix() == {"stock": 0.75, "generated": 0.25}


def test_resolve_makes_media_paths_absolute(tmp_path: pathlib.Path) -> None:
    edl = make_edl([make_shot(path="clips/a.mp4")])
    edl = edl.model_copy(
        update={"audio": AudioPlan(music_path="audio/music.mp3", sfx_paths=["audio/whoosh.wav"])}
    )
    resolved = edl.resolve(tmp_path)
    assert pathlib.Path(resolved.shots[0].path) == (tmp_path / "clips/a.mp4").resolve()
    assert pathlib.Path(resolved.audio.music_path or "") == (tmp_path / "audio/music.mp3").resolve()
    assert pathlib.Path(resolved.audio.sfx_paths[0]) == (tmp_path / "audio/whoosh.wav").resolve()


def test_shot_duration_is_bounded() -> None:
    with pytest.raises(ValueError):
        make_shot(duration_seconds=30.0)


def test_transition_defaults_to_cut() -> None:
    assert make_shot().transition.value == "cut"
