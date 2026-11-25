"""Transition sound design, synthesised so every cut has weight without noise.

Events are placed on a timeline and rendered into one bed, which keeps the
mixer simple: the renderer receives a single timed stem instead of untimed files.
"""

from __future__ import annotations

import dataclasses
import pathlib
import wave

import numpy as np

SAMPLE_RATE = 48000


@dataclasses.dataclass(frozen=True)
class SfxEvent:
    kind: str
    at: float
    gain_db: float = -18.0

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown sfx kind {self.kind!r}")
        if self.at < 0:
            raise ValueError("event time must be non-negative")


KINDS = ("whoosh", "impact", "riser", "sub_drop", "tick")


def _band(signal: np.ndarray, low: float, high: float) -> np.ndarray:
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, 1 / SAMPLE_RATE)
    mask = 1 / (1 + np.exp(-(freqs - low) / max(low * 0.3, 1.0)))
    mask *= 1 / (1 + np.exp((freqs - high) / max(high * 0.3, 1.0)))
    return np.fft.irfft(spectrum * mask, n=signal.size)


def _swept_noise(
    seconds: float, low: float, high: float, rng: np.random.Generator, blocks: int = 28
) -> np.ndarray:
    total = int(seconds * SAMPLE_RATE)
    out = np.zeros(total)
    block = max(1, total // blocks)
    window = np.hanning(block * 2)
    for index in range(blocks):
        position = index / max(blocks - 1, 1)
        centre = low * (high / low) ** position
        start = index * block
        stop = min(start + block * 2, total)
        chunk = rng.standard_normal(stop - start)
        out[start:stop] += _band(chunk, centre * 0.55, centre * 1.8) * window[: stop - start]
    return out


def render_event(kind: str, rng: np.random.Generator) -> np.ndarray:
    if kind == "whoosh":
        seconds = 0.62
        body = _swept_noise(seconds, 320, 2600, rng)
        env = np.sin(np.linspace(0, np.pi, body.size)) ** 1.8
        stereo = np.stack([body * env, np.roll(body * env, 96)], axis=1)
        return stereo / (np.max(np.abs(stereo)) or 1.0)

    if kind == "impact":
        seconds = 0.55
        n = int(seconds * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        thump = np.sin(2 * np.pi * 58 * t) * np.exp(-t / 0.10)
        click = _band(rng.standard_normal(n), 900, 5200) * np.exp(-t / 0.012) * 0.5
        mono = thump + click
        mono /= np.max(np.abs(mono)) or 1.0
        return np.stack([mono, mono], axis=1)

    if kind == "riser":
        seconds = 1.35
        body = _swept_noise(seconds, 260, 5200, rng, blocks=40)
        env = np.linspace(0.02, 1.0, body.size) ** 2.2
        stereo = np.stack([body * env, np.roll(body * env, 240)], axis=1)
        return stereo / (np.max(np.abs(stereo)) or 1.0)

    if kind == "sub_drop":
        seconds = 1.05
        n = int(seconds * SAMPLE_RATE)
        t = np.arange(n) / SAMPLE_RATE
        freq = 92 * np.exp(-t / 0.55) + 32
        mono = np.sin(2 * np.pi * np.cumsum(freq) / SAMPLE_RATE) * np.exp(-t / 0.42)
        mono /= np.max(np.abs(mono)) or 1.0
        return np.stack([mono, mono], axis=1)

    seconds = 0.12
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    mono = np.sin(2 * np.pi * 2400 * t) * np.exp(-t / 0.015)
    mono /= np.max(np.abs(mono)) or 1.0
    return np.stack([mono, mono], axis=1)


def compose_bed(
    events: list[SfxEvent],
    duration: float,
    out_path: str | pathlib.Path,
    *,
    seed: int = 11,
) -> str:
    rng = np.random.default_rng(seed)
    total = int(duration * SAMPLE_RATE) + SAMPLE_RATE // 2
    bed = np.zeros((total, 2))
    for event in events:
        sample = render_event(event.kind, rng) * (10 ** (event.gain_db / 20))
        start = int(event.at * SAMPLE_RATE)
        stop = min(start + sample.shape[0], total)
        if stop > start:
            bed[start:stop] += sample[: stop - start]
    peak = float(np.max(np.abs(bed)))
    if peak > 0.7:
        bed *= 0.7 / peak
    target = pathlib.Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(bed, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return str(target)
