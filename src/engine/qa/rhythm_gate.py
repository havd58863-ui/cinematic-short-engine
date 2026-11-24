"""Rhythm gate — protects retention before the render, not after.

On short-form vertical video the single most expensive mistake is a shot that
overstays. This gate is deterministic and runs on the EDL, so a bad edit is
rejected in milliseconds instead of after a GPU render.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import Field

from engine.contracts import StrictModel
from engine.edit.edl import EDL


class RhythmRules(StrictModel):
    max_shot_seconds: float = Field(default=4.0, gt=0.5, le=12.0)
    hook_max_seconds: float = Field(default=2.5, gt=0.3, le=6.0)
    mean_shot_range: tuple[float, float] = (1.2, 3.5)
    max_long_shot_streak: int = Field(default=1, ge=0, le=5)


class RhythmGateError(RuntimeError):
    """Raised when an edit would break retention rules."""


@dataclass
class RhythmReport:
    passed: bool
    duration: float
    shot_count: int
    mean_shot: float
    longest_shot: float
    hook_seconds: float
    cadence_seconds: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "duration": round(self.duration, 2),
            "shot_count": self.shot_count,
            "mean_shot": round(self.mean_shot, 3),
            "longest_shot": round(self.longest_shot, 3),
            "hook_seconds": round(self.hook_seconds, 3),
            "cadence_seconds": round(self.cadence_seconds, 3),
            "reasons": self.reasons,
        }


def analyze_edl(edl: EDL, rules: RhythmRules | None = None) -> RhythmReport:
    rules = rules or RhythmRules()
    durations = [shot.duration_seconds / shot.speed for shot in edl.shots]
    total = sum(durations)
    reasons: list[str] = []

    for shot, seconds in zip(edl.shots, durations, strict=True):
        if seconds > rules.max_shot_seconds:
            reasons.append(
                f"shot '{shot.id}' holds {seconds:.1f}s (max {rules.max_shot_seconds:.1f}s)"
            )

    low, high = rules.mean_shot_range
    mean_shot = total / len(durations)
    if not low <= mean_shot <= high:
        reasons.append(
            f"mean shot {mean_shot:.2f}s outside the {low:g}-{high:g}s retention band"
        )

    hook = durations[0]
    if hook > rules.hook_max_seconds:
        reasons.append(f"hook shot is {hook:.1f}s (max {rules.hook_max_seconds:.1f}s)")

    streak = longest = 0
    for seconds in durations:
        streak = streak + 1 if seconds > 3.5 else 0
        longest = max(longest, streak)
    if longest > rules.max_long_shot_streak:
        reasons.append(f"{longest} consecutive slow shots — the middle will die")

    return RhythmReport(
        passed=not reasons,
        duration=total,
        shot_count=len(edl.shots),
        mean_shot=mean_shot,
        longest_shot=max(durations),
        hook_seconds=hook,
        cadence_seconds=mean_shot,
        reasons=reasons,
    )


def assert_rhythm(edl: EDL, rules: RhythmRules | None = None) -> RhythmReport:
    report = analyze_edl(edl, rules)
    if not report.passed:
        raise RhythmGateError("; ".join(report.reasons))
    return report


def compare_to_profile(edl: EDL, target_mean: float, tolerance: float = 0.6) -> RhythmReport:
    """Compare an edit against a look-bible cadence taken from winning videos."""
    report = analyze_edl(edl)
    delta = abs(report.mean_shot - target_mean)
    if delta > tolerance:
        report.passed = False
        report.reasons.append(
            f"cadence {report.mean_shot:.2f}s differs from the reference "
            f"{target_mean:.2f}s by {delta:.2f}s (tolerance {tolerance:.2f}s)"
        )
    return report
