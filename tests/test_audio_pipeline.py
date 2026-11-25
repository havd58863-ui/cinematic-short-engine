"""The audio and timing layer: voice timing, score, SFX and karaoke captions."""

from __future__ import annotations

import pathlib
import sys
import wave

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from engine.audio.music import Mood, compose
from engine.audio.sfx import SfxEvent, compose_bed
from engine.director.allocate import Beat, Clip, SourcePolicy
from engine.edit.edl import ShotSource
from engine.edit.subtitles import karaoke_cues
from engine.edit.timing import BeatAudio, TimedWord, plan_shots
from engine.orchestrator.produce import _split


def _frames(path: pathlib.Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes(), handle.getframerate()


def test_split_keeps_short_sentences_intact() -> None:
    pieces = _split("One short line. Another short line.")
    assert pieces == ["One short line.", "Another short line."]


def test_split_capitalises_comma_fragments() -> None:
    text = (
        "When someone leaves without a clean ending your mind is left holding an unfinished story "
        "and it keeps pulling attention back to it, and the messages become the only place where the "
        "ending might still be written, and that is why you keep returning to them every night."
    )
    pieces = _split(text, limit_words=14)
    assert len(pieces) > 1
    assert all(piece[:1].isupper() for piece in pieces)
    assert all(len(piece.split()) <= 20 for piece in pieces)


def test_karaoke_cues_fill_word_by_word() -> None:
    words = [("one", 0.0, 0.4), ("two", 0.4, 0.9), ("three", 0.9, 1.3)]
    cues = karaoke_cues(words, max_words=3)
    assert len(cues) == 1
    cue = cues[0]
    assert cue.raw is True
    assert cue.start == 0.0
    assert cue.text.count(r"\kf") == 3
    assert "ONE" in cue.text and "THREE" in cue.text


def test_plan_shots_uses_sentence_length_and_never_repeats_back_to_back() -> None:
    clips = [
        Clip(path=f"/tmp/clip{i}.mp4", source=ShotSource.STOCK, tags=["waves"], duration_seconds=9.0)
        for i in range(4)
    ]
    beats = [
        BeatAudio(
            beat=Beat(id=f"beat{i}", spoken="line", visual_intent="waves moving on rocks", tags=["waves"]),
            duration=2.0 + i,
            words=(TimedWord("line", 0.0, 0.5),),
        )
        for i in range(3)
    ]
    planned = plan_shots(beats, clips, SourcePolicy())
    durations = [round(item.shot.duration_seconds, 2) for item in planned]
    assert durations == [2.22, 3.22, 4.22]
    assert len({item.shot.path for item in planned}) == 3
    starts = [item.timeline_start for item in planned]
    assert starts == sorted(starts)


def test_compose_writes_a_bed_of_the_requested_length(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "score.wav"
    compose(Mood(name="test", bpm=70), 4.0, target)
    frames, rate = _frames(target)
    assert rate == 48000
    assert abs(frames / rate - 4.0) < 0.05


def test_compose_is_deterministic(tmp_path: pathlib.Path) -> None:
    first = compose(Mood(name="test"), 2.0, tmp_path / "a.wav", seed=5)
    second = compose(Mood(name="test"), 2.0, tmp_path / "b.wav", seed=5)
    assert pathlib.Path(first).read_bytes() == pathlib.Path(second).read_bytes()


def test_sfx_bed_places_events_where_asked(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "sfx.wav"
    compose_bed([SfxEvent("impact", 2.0, -6.0)], 4.0, target)
    with wave.open(str(target), "rb") as handle:
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)
    rate = 48000
    left = data[::2]
    window = left[int(2.0 * rate) : int(2.3 * rate)]
    quiet = left[: int(1.0 * rate)]
    assert np.abs(window).max() > 1000
    assert np.abs(quiet).max() < 50


def test_mood_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        Mood(name="bad", mode="lydian-ish")
