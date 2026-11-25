"""Subtitles as a design element, not an afterthought.

Vertical video is watched muted more often than not, so the caption carries the
hook. We render ASS with libass (already in the FFmpeg build) which gives real
typography control: safe margins, outline, fade per cue.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from pydantic import Field

from engine.contracts import StrictModel
from engine.edit.edl import EDL


class SubtitleStyle(StrictModel):
    font: str = "DejaVu Serif"
    size: int = Field(default=62, ge=20, le=160)
    primary_colour: str = "&H00FFFFFF"
    outline_colour: str = "&H00101010"
    outline: float = Field(default=3.0, ge=0.0, le=10.0)
    shadow: float = Field(default=1.0, ge=0.0, le=10.0)
    margin_v: int = Field(default=260, ge=0, le=900)
    max_chars_per_line: int = Field(default=26, ge=10, le=60)
    max_lines: int = Field(default=3, ge=1, le=5)
    fade_ms: int = Field(default=180, ge=0, le=1000)
    uppercase: bool = False
    sung_colour: str = "&H00FFFFFF"
    unsung_colour: str = "&H00A8A8A8"


@dataclass
class Cue:
    start: float
    end: float
    text: str
    raw: bool = False


def _timestamp(seconds: float) -> str:
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, rest = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{rest:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\(").replace("}", r"\)")


def wrap(text: str, max_chars: int, max_lines: int) -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        head = lines[: max_lines - 1]
        head.append(" ".join(lines[max_lines - 1:]))
        lines = head
    return r"\N".join(lines)


def cues_from_edl(edl: EDL, spoken: dict[str, str]) -> list[Cue]:
    """One cue per shot, using the beat that shot was allocated for."""
    cues: list[Cue] = []
    cursor = 0.0
    for shot in edl.shots:
        start = cursor
        end = cursor + shot.duration_seconds
        text = spoken.get(shot.narrative_function, "")
        if text:
            cues.append(Cue(start=start, end=end, text=text))
        cursor = end
    return cues


def build_ass(cues: list[Cue], style: SubtitleStyle, play_res: tuple[int, int]) -> str:
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {play_res[0]}",
        f"PlayResY: {play_res[1]}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
        " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
        " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Main,{style.font},{style.size},{style.sung_colour},{style.unsung_colour},"
        f"{style.outline_colour},&H80000000,0,0,0,0,100,100,1,0,1,"
        f"{style.outline:g},{style.shadow:g},2,90,90,{style.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events: list[str] = []
    for cue in cues:
        text = cue.text.upper() if style.uppercase else cue.text
        wrapped = text if cue.raw else wrap(_escape(text), style.max_chars_per_line, style.max_lines)
        effect = f"{{\\fad({style.fade_ms},{style.fade_ms})}}" if style.fade_ms else ""
        events.append(
            f"Dialogue: 0,{_timestamp(cue.start)},{_timestamp(cue.end)},Main,,0,0,0,,{effect}{wrapped}"
        )
    return "\n".join(header + events) + "\n"


def write_ass(
    cues: list[Cue],
    style: SubtitleStyle,
    play_res: tuple[int, int],
    out_path: str | pathlib.Path,
) -> pathlib.Path:
    target = pathlib.Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_ass(cues, style, play_res), encoding="utf-8")
    return target


BREAK_BEFORE = frozenset(
    """
    and but or so because when while that which who whom whose for to of in on at
    from with as if then than until after before into over under through
    """.split()
)
PUNCTUATION = ".!?;:,\u2014\u2013"


def karaoke_cues(
    words: list[tuple[str, float, float]],
    *,
    max_words: int = 4,
    tail: float = 0.18,
) -> list[Cue]:
    """Group timed words into cues that fill word by word as they are spoken.

    Cues break at punctuation, and before a joining word once the line is long
    enough, so a caption never ends mid-phrase ("for someone" / "boats").
    """
    cues: list[Cue] = []
    chunk: list[tuple[str, float, float]] = []
    for position, word in enumerate(words):
        chunk.append(word)
        text = word[0].rstrip("\"')]")
        following = words[position + 1][0].strip("\"'(").lower() if position + 1 < len(words) else ""
        at_punctuation = bool(text) and text[-1] in PUNCTUATION
        joins_next = following in BREAK_BEFORE
        if at_punctuation or len(chunk) >= max_words or (
            len(chunk) >= max_words - 1 and joins_next
        ):
            cues.append(_karaoke_cue(chunk, tail))
            chunk = []
    if chunk:
        cues.append(_karaoke_cue(chunk, tail))
    return cues


def _karaoke_cue(chunk: list[tuple[str, float, float]], tail: float) -> Cue:
    start = chunk[0][1]
    end = chunk[-1][2] + tail
    parts: list[str] = []
    for position, (text, word_start, word_end) in enumerate(chunk):
        centiseconds = max(1, round((word_end - word_start) * 100))
        spacer = "" if position == len(chunk) - 1 else " "
        parts.append(f"{{\\kf{centiseconds}}}{_escape(text.upper())}{spacer}")
    return Cue(start=round(start, 3), end=round(end, 3), text="".join(parts), raw=True)
