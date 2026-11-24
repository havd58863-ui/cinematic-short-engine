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


@dataclass
class Cue:
    start: float
    end: float
    text: str


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
        f"Style: Main,{style.font},{style.size},{style.primary_colour},&H000000FF,"
        f"{style.outline_colour},&H80000000,0,0,0,0,100,100,1,0,1,"
        f"{style.outline:g},{style.shadow:g},2,90,90,{style.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events: list[str] = []
    for cue in cues:
        text = cue.text.upper() if style.uppercase else cue.text
        wrapped = wrap(_escape(text), style.max_chars_per_line, style.max_lines)
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
