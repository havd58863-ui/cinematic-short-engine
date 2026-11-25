"""Exposure gate — catches dead frames before they reach a feed.

A shot that sits at near-black for its whole length reads as a playback error on
a phone in daylight, no matter how deliberate it looked on a monitor. This gate
measures mean luma per shot after the grade and refuses the extremes.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from engine.edit.render import measure_luma

MIN_LUMA = 0.11
MAX_LUMA = 0.92


class ExposureGateError(RuntimeError):
    """Raised when a shot is too dark or too blown out to publish."""


@dataclass
class ExposureReport:
    path: str
    mean_luma: float
    verdict: str
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "mean_luma": round(self.mean_luma, 4),
            "verdict": self.verdict,
            "reasons": self.reasons,
        }


def analyze(
    path: str | pathlib.Path,
    min_luma: float = MIN_LUMA,
    max_luma: float = MAX_LUMA,
) -> ExposureReport:
    source = pathlib.Path(path)
    luma = measure_luma(source)
    if luma is None:
        return ExposureReport(str(source), 0.0, "failed", ["no measurable luma"])
    reasons: list[str] = []
    if luma < min_luma:
        reasons.append(f"mean luma {luma:.3f} is below {min_luma:.2f} — the shot reads as black")
    if luma > max_luma:
        reasons.append(f"mean luma {luma:.3f} is above {max_luma:.2f} — the shot is blown out")
    return ExposureReport(str(source), luma, "failed" if reasons else "passed", reasons)


def gate(
    paths: list[str | pathlib.Path],
    strict: bool = False,
    min_luma: float = MIN_LUMA,
    max_luma: float = MAX_LUMA,
) -> dict[str, object]:
    reports = [analyze(path, min_luma, max_luma) for path in paths]
    failures = [report.as_dict() for report in reports if not report.passed]
    if strict and failures:
        raise ExposureGateError(f"{len(failures)} shot(s) failed the exposure gate")
    return {
        "ok": not failures,
        "checked": len(reports),
        "failures": failures,
        "reports": [report.as_dict() for report in reports],
    }
