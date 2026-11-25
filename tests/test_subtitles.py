from __future__ import annotations

from engine.contracts import AccountId
from engine.edit.edl import EDL, Shot, ShotSource
from engine.edit.subtitles import (
    Cue,
    SubtitleStyle,
    build_ass,
    cues_from_edl,
    wrap,
    write_ass,
)


def shot(index: int, seconds: float, beat: str) -> Shot:
    return Shot(
        id=f"s{index:02d}_x",
        source=ShotSource.STOCK,
        path="clips/a.mp4",
        duration_seconds=seconds,
        why="carries the line without competing with it",
        narrative_function=beat,
    )


def test_wrap_respects_width_and_line_count() -> None:
    text = "You are not lazy your brain is protecting you from a threat it imagined"
    wrapped = wrap(text, max_chars=24, max_lines=3)
    lines = wrapped.split(r"\N")
    assert len(lines) <= 3
    assert all(len(line) <= 24 for line in lines[:-1])
    assert all(word in " ".join(lines) for word in text.split())


def test_cues_follow_the_timeline() -> None:
    edl = EDL(
        account=AccountId.PSYCHOLOGY,
        title="t",
        shots=[shot(0, 2.0, "hook"), shot(1, 2.5, "payoff")],
    )
    cues = cues_from_edl(edl, {"hook": "first line", "payoff": "second line"})
    assert [round(cue.start, 2) for cue in cues] == [0.0, 2.0]
    assert round(cues[1].end, 2) == 4.5


def test_cues_skip_shots_without_text() -> None:
    edl = EDL(
        account=AccountId.PSYCHOLOGY,
        title="t",
        shots=[shot(0, 1.5, "hook"), shot(1, 1.5, "silent")],
    )
    cues = cues_from_edl(edl, {"hook": "line"})
    assert len(cues) == 1


def test_ass_contains_style_and_events() -> None:
    ass = build_ass(
        [Cue(0.0, 2.0, "You are not lazy")],
        SubtitleStyle(font="DejaVu Serif", size=60),
        (1080, 1920),
    )
    assert "PlayResY: 1920" in ass
    assert "Style: Main,DejaVu Serif,60" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Main" in ass
    assert "{\\fad(180,180)}" in ass


def test_ass_escapes_braces() -> None:
    ass = build_ass([Cue(0, 1, "a {tag} b")], SubtitleStyle(), (1080, 1920))
    assert "{tag}" not in ass.split("[Events]")[1]
    assert r"\(tag\)" in ass


def test_uppercase_style_is_applied() -> None:
    ass = build_ass([Cue(0, 1, "quiet line")], SubtitleStyle(uppercase=True), (1080, 1920))
    assert "QUIET LINE" in ass


def test_write_ass_creates_file(tmp_path) -> None:
    out = write_ass([Cue(0, 1, "x")], SubtitleStyle(), (1080, 1920), tmp_path / "subs.ass")
    assert out.read_text(encoding="utf-8").startswith("[Script Info]")
