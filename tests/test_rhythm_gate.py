from __future__ import annotations

import pytest

from engine.contracts import AccountId
from engine.edit.edl import EDL, Shot, ShotSource
from engine.qa.rhythm_gate import (
    RhythmGateError,
    RhythmRules,
    analyze_edl,
    assert_rhythm,
    compare_to_profile,
)


def shot(index: int, seconds: float) -> Shot:
    return Shot(
        id=f"s{index:02d}_beat",
        source=ShotSource.STOCK,
        path="clips/a.mp4",
        duration_seconds=seconds,
        why="keeps the eye moving with a matching visual beat",
        narrative_function="beat",
    )


def edl(seconds: list[float]) -> EDL:
    return EDL(
        account=AccountId.PSYCHOLOGY,
        title="rhythm",
        shots=[shot(i, value) for i, value in enumerate(seconds)],
    )


def test_good_pace_passes() -> None:
    report = analyze_edl(edl([1.8, 2.2, 1.6, 2.4, 2.0, 1.8]))
    assert report.passed, report.reasons
    assert report.shot_count == 6


def test_long_shot_is_rejected() -> None:
    report = analyze_edl(edl([1.8, 5.0, 2.0]))
    assert not report.passed
    assert any("holds" in reason for reason in report.reasons)


def test_slow_hook_is_rejected() -> None:
    report = analyze_edl(edl([3.2, 2.0, 1.8, 2.2]))
    assert not report.passed
    assert any("hook" in reason for reason in report.reasons)


def test_machine_gun_editing_is_rejected() -> None:
    report = analyze_edl(edl([0.8] * 9))
    assert not report.passed
    assert any("mean shot" in reason for reason in report.reasons)


def test_streak_of_slow_shots_is_rejected() -> None:
    report = analyze_edl(edl([1.8, 3.8, 3.9, 1.9]))
    assert not report.passed
    assert any("consecutive" in reason for reason in report.reasons)


def test_assert_rhythm_raises_with_named_reason() -> None:
    with pytest.raises(RhythmGateError):
        assert_rhythm(edl([1.5, 9.0]))


def test_compare_to_profile_flags_off_cadence() -> None:
    report = compare_to_profile(edl([1.8, 2.0, 1.9, 2.1, 1.7, 2.0]), target_mean=3.4)
    assert not report.passed
    assert any("cadence" in reason for reason in report.reasons)


def test_custom_rules_are_honoured() -> None:
    relaxed = RhythmRules(max_shot_seconds=6.0, hook_max_seconds=4.0)
    report = analyze_edl(edl([3.2, 2.0, 1.8, 2.2]), relaxed)
    assert report.passed, report.reasons
