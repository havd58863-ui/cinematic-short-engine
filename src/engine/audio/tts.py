"""Voice-over synthesis with word-level timing.

edge-tts streams WordBoundary events next to the audio, which is what makes
word-synced captions possible without a separate forced aligner.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
import subprocess

import edge_tts

from engine.edit.render import ffprobe_bin

DEFAULT_VOICE = "en-US-AndrewNeural"


class TtsError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclasses.dataclass(frozen=True)
class VoClip:
    path: str
    duration: float
    words: tuple[Word, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "duration": self.duration,
            "words": [dataclasses.asdict(word) for word in self.words],
        }


def probe_duration(path: str | pathlib.Path) -> float:
    result = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


async def _stream(
    text: str, voice: str, rate: str, pitch: str, volume: str, out_path: pathlib.Path
) -> list[Word]:
    communicate = edge_tts.Communicate(
        text, voice, rate=rate, pitch=pitch, volume=volume, boundary="WordBoundary"
    )
    marks: list[Word] = []
    with out_path.open("wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                marks.append(Word(chunk["text"], start, start + chunk["duration"] / 10_000_000))
    return marks


def synthesize(
    text: str,
    out_path: str | pathlib.Path,
    *,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
) -> VoClip:
    target = pathlib.Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    marks = asyncio.run(_stream(text, voice, rate, pitch, volume, target))
    if not marks:
        raise TtsError(f"no word boundaries returned for {text[:40]!r}")
    duration = probe_duration(target)
    words: list[Word] = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start if index + 1 < len(marks) else min(duration, mark.start + 0.6)
        words.append(
            Word(
                text=mark.text,
                start=round(min(mark.start, duration), 3),
                end=round(min(max(end, mark.start + 0.05), duration), 3),
            )
        )
    return VoClip(path=str(target), duration=round(duration, 3), words=tuple(words))
