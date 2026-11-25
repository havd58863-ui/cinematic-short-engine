"""Deterministic score generation.

A generative model (MusicGen) needs a GPU, so the default backend synthesises
the bed from a mood description: key, mode, tempo, brightness and pulse. Every
video therefore gets music that matches its tone, offline and reproducibly.
"""

from __future__ import annotations

import dataclasses
import pathlib
import wave

import numpy as np

SAMPLE_RATE = 48000
SCALES: dict[str, tuple[int, ...]] = {
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "major": (0, 2, 4, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
}
PROGRESSIONS: dict[str, tuple[int, ...]] = {
    "minor": (0, 5, 3, 4),
    "major": (0, 4, 5, 3),
    "dorian": (0, 3, 6, 4),
}


@dataclasses.dataclass(frozen=True)
class Mood:
    name: str
    root: int = 57           # A3
    mode: str = "minor"
    bpm: int = 74
    brightness: float = 0.45
    pulse: float = 0.35
    pad_level: float = 0.55
    sub_level: float = 0.20

    def __post_init__(self) -> None:
        if self.mode not in SCALES:
            raise ValueError(f"unknown mode {self.mode!r}")
        for value in (self.brightness, self.pulse, self.pad_level, self.sub_level):
            if not 0.0 <= value <= 1.0:
                raise ValueError("mood levels must sit in [0, 1]")
        if not 40 <= self.bpm <= 160:
            raise ValueError("bpm must sit between 40 and 160")


def _hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


def _band(signal: np.ndarray, low: float, high: float) -> np.ndarray:
    spectrum = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(signal.size, 1 / SAMPLE_RATE)
    mask = 1 / (1 + np.exp(-(freqs - low) / max(low * 0.25, 1.0)))
    mask *= 1 / (1 + np.exp((freqs - high) / max(high * 0.25, 1.0)))
    return np.fft.irfft(spectrum * mask, n=signal.size)


def _envelope(length: int, attack: float, release: float) -> np.ndarray:
    env = np.ones(length)
    a = max(1, int(attack * SAMPLE_RATE))
    r = max(1, int(release * SAMPLE_RATE))
    a = min(a, length)
    r = min(r, length)
    env[:a] = np.linspace(0.0, 1.0, a) ** 1.6
    env[-r:] *= np.linspace(1.0, 0.0, r) ** 1.3
    return env


def _pad(mood: Mood, degree: int, seconds: float, rng: np.random.Generator) -> np.ndarray:
    scale = SCALES[mood.mode]
    tones = [0, 2, 4, 6]
    length = int(seconds * SAMPLE_RATE)
    out = np.zeros((length, 2))
    cutoff = 380 + mood.brightness * 2400
    for index, step in enumerate(tones):
        midi = mood.root + scale[(degree + step) % 7] + 12 * ((degree + step) // 7)
        for detune, pan in ((-0.06, 0.35), (0.0, 0.0), (0.07, -0.35)):
            freq = _hz(midi + detune)
            phase = rng.random() * 2 * np.pi
            wave_l = np.sin(2 * np.pi * freq * np.arange(length) / SAMPLE_RATE + phase)
            wave_l += 0.28 * np.sin(4 * np.pi * freq * np.arange(length) / SAMPLE_RATE + phase)
            gain = mood.pad_level * (0.32 if index else 0.42) / (1 + index * 0.35)
            out[:, 0] += wave_l * gain * (1 - pan) * 0.5
            out[:, 1] += wave_l * gain * (1 + pan) * 0.5
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.11 * np.arange(length) / SAMPLE_RATE)
    out *= (_envelope(length, 0.9, 0.8) * lfo)[:, None]
    for channel in range(2):
        out[:, channel] = _band(out[:, channel], 90, cutoff)
    return out


def _pluck(mood: Mood, degree: int, seconds: float, rng: np.random.Generator) -> np.ndarray:
    scale = SCALES[mood.mode]
    length = int(seconds * SAMPLE_RATE)
    out = np.zeros((length, 2))
    eighth = seconds / 8
    for step in range(8):
        if rng.random() > mood.pulse:
            continue
        tone = scale[(degree + (step % 3) * 2) % 7] + 12
        freq = _hz(mood.root + tone)
        start = int(step * eighth * SAMPLE_RATE)
        size = min(int(0.42 * SAMPLE_RATE), length - start)
        if size <= 0:
            continue
        decay = np.exp(-np.arange(size) / (SAMPLE_RATE * 0.12))
        body = np.sin(2 * np.pi * freq * np.arange(size) / SAMPLE_RATE)
        body += 0.35 * np.sin(4 * np.pi * freq * np.arange(size) / SAMPLE_RATE)
        body *= decay * 0.16 * mood.pulse
        out[start:start + size, 0] += body
        out[start:start + size, 1] += body * 0.85
    return out


def _sub(mood: Mood, degree: int, seconds: float) -> np.ndarray:
    length = int(seconds * SAMPLE_RATE)
    freq = _hz(mood.root - 12 + SCALES[mood.mode][degree % 7])
    body = np.sin(2 * np.pi * freq * np.arange(length) / SAMPLE_RATE)
    return (body * _envelope(length, 0.6, 0.7) * mood.sub_level)[:, None].repeat(2, axis=1)


def _reverb(signal: np.ndarray, rng: np.random.Generator, seconds: float = 1.1) -> np.ndarray:
    size = int(seconds * SAMPLE_RATE)
    tail = np.exp(-np.arange(size) / (SAMPLE_RATE * seconds * 0.35))
    out = np.zeros_like(signal)
    for channel in range(2):
        ir = rng.standard_normal(size) * tail
        ir /= np.sqrt(np.sum(ir ** 2))
        padded = np.zeros(signal.shape[0] + size)
        padded[: signal.shape[0]] = signal[:, channel]
        wet = np.fft.irfft(np.fft.rfft(padded) * np.fft.rfft(ir, n=padded.size), n=padded.size)
        out[:, channel] = wet[: signal.shape[0]]
    return out


def _write(path: pathlib.Path, stereo: np.ndarray) -> None:
    peak = float(np.max(np.abs(stereo))) or 1.0
    data = np.clip(stereo / peak * 0.82, -1.0, 1.0)
    pcm = (data * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())


def compose(mood: Mood, duration: float, out_path: str | pathlib.Path, *, seed: int = 7) -> str:
    if duration <= 0:
        raise ValueError("duration must be positive")
    rng = np.random.default_rng(seed)
    total = int(duration * SAMPLE_RATE) + SAMPLE_RATE // 2
    bed = np.zeros((total, 2))
    bar = 240.0 / mood.bpm
    progression = PROGRESSIONS[mood.mode]
    cursor = 0.0
    index = 0
    while cursor < duration:
        degree = progression[index % len(progression)]
        for layer in (_pad(mood, degree, bar, rng), _pluck(mood, degree, bar, rng), _sub(mood, degree, bar)):
            start = int(cursor * SAMPLE_RATE)
            stop = min(start + layer.shape[0], total)
            bed[start:stop] += layer[: stop - start]
        cursor += bar
        index += 1
    wet = _reverb(bed, rng)
    mixed = bed * 0.78 + wet * 0.30
    target = pathlib.Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, mixed[: int(duration * SAMPLE_RATE)])
    return str(target)
