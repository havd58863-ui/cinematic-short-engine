"""Look bible: measure what winning videos actually do, then copy the pattern.

We copy rhythm and colour, never content. The output is a YAML file the director
reads for cadence targets and the look layer reads for colour fingerprints.
"""

from __future__ import annotations

import pathlib
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np
import yaml

CUT_THRESHOLD = 0.16
MIN_SHOT_SECONDS = 0.3
SAMPLE_FPS = 6.0


@dataclass
class ColourFingerprint:
    luma_mean: float
    luma_contrast: float
    saturation_mean: float
    warmth: float
    shadow_lift: float


@dataclass
class ReferenceAnalysis:
    path: str
    duration_seconds: float
    shot_durations: list[float]
    colour: ColourFingerprint

    def stats(self) -> dict[str, float]:
        durations = np.array(self.shot_durations or [0.0], dtype=np.float32)
        return {
            "duration_seconds": round(self.duration_seconds, 2),
            "shot_count": len(self.shot_durations),
            "mean_shot": round(float(np.mean(durations)), 3),
            "median_shot": round(float(np.median(durations)), 3),
            "p90_shot": round(float(np.percentile(durations, 90)), 3),
            "longest_shot": round(float(np.max(durations)), 3),
        }


@dataclass
class LookBible:
    name: str
    references: list[ReferenceAnalysis] = field(default_factory=list)

    def targets(self) -> dict[str, object]:
        per_video = [ref.stats() for ref in self.references]
        means = [item["mean_shot"] for item in per_video]
        p90s = [item["p90_shot"] for item in per_video]
        fingerprints = [ref.colour for ref in self.references]
        return {
            "cadence": {
                "mean_shot_seconds": round(float(np.median(means)), 3) if means else 2.2,
                "p90_shot_seconds": round(float(np.median(p90s)), 3) if p90s else 3.5,
                "max_shot_seconds": 4.0,
                "tolerance_seconds": 0.6,
            },
            "colour": {
                "luma_mean": round(float(np.median([f.luma_mean for f in fingerprints])), 4),
                "luma_contrast": round(float(np.median([f.luma_contrast for f in fingerprints])), 4),
                "saturation_mean": round(float(np.median([f.saturation_mean for f in fingerprints])), 4),
                "warmth": round(float(np.median([f.warmth for f in fingerprints])), 4),
                "shadow_lift": round(float(np.median([f.shadow_lift for f in fingerprints])), 4),
            },
            "per_video": per_video,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "targets": self.targets(),
            "references": [
                {**asdict(ref), "stats": ref.stats()} for ref in self.references
            ],
        }


def _sample_frames(path: pathlib.Path, sample_fps: float = SAMPLE_FPS):
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"cannot open video: {path}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / sample_fps)))
    index = 0
    frames: list[tuple[float, np.ndarray]] = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step == 0:
            frames.append((index / fps, frame))
        index += 1
    duration = index / fps if fps else len(frames) / sample_fps
    capture.release()
    return frames, duration


def _colour_fingerprint(frames: dict[str, np.ndarray]) -> ColourFingerprint:
    luma: list[float] = []
    contrast: list[float] = []
    saturation: list[float] = []
    warmth: list[float] = []
    shadow: list[float] = []
    for frame in frames.values():
        small = cv2.resize(frame, (160, 284), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        luma.append(float(grey.mean()))
        contrast.append(float(grey.std()))
        saturation.append(float(hsv[:, :, 1].mean() / 255.0))
        b, g, r = [small[:, :, i].astype(np.float32) / 255.0 for i in range(3)]
        warmth.append(float(r.mean() - b.mean()))
        dark = grey < 0.25
        shadow.append(float(grey[dark].mean()) if dark.any() else 0.0)
    return ColourFingerprint(
        luma_mean=float(np.mean(luma)) if luma else 0.0,
        luma_contrast=float(np.mean(contrast)) if contrast else 0.0,
        saturation_mean=float(np.mean(saturation)) if saturation else 0.0,
        warmth=float(np.mean(warmth)) if warmth else 0.0,
        shadow_lift=float(np.mean(shadow)) if shadow else 0.0,
    )


def analyze_reference(path: str | pathlib.Path, sample_fps: float = SAMPLE_FPS) -> ReferenceAnalysis:
    source = pathlib.Path(path)
    frames, duration = _sample_frames(source, sample_fps)
    if not frames:
        raise ValueError(f"no frames decoded from {source}")

    previous = cv2.cvtColor(frames[0][1], cv2.COLOR_BGR2GRAY)
    previous = cv2.resize(previous, (96, 170), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    cuts: list[float] = [0.0]
    for timestamp, frame in frames[1:]:
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        grey = cv2.resize(grey, (96, 170), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        if float(np.mean(np.abs(grey - previous))) > CUT_THRESHOLD:
            if timestamp - cuts[-1] >= MIN_SHOT_SECONDS:
                cuts.append(timestamp)
        previous = grey

    boundaries = cuts + [duration]
    shot_durations = [
        round(boundaries[i + 1] - boundaries[i], 3) for i in range(len(boundaries) - 1)
    ]
    colour = _colour_fingerprint({str(t): frame for t, frame in frames[::2]})
    return ReferenceAnalysis(
        path=str(source),
        duration_seconds=round(duration, 3),
        shot_durations=shot_durations,
        colour=colour,
    )


def build_look_bible(paths: list[str | pathlib.Path], name: str) -> LookBible:
    return LookBible(name=name, references=[analyze_reference(path) for path in paths])


def write_look_bible(bible: LookBible, out_path: str | pathlib.Path) -> pathlib.Path:
    target = pathlib.Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(bible.as_dict(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target
