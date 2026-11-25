from __future__ import annotations

import shutil
import subprocess

import pytest

from engine.qa.motion_gate import MotionGateError, analyze, assert_motion, gate_shots

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg is required to build motion fixtures",
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    root = tmp_path_factory.mktemp("motion")
    still = root / "still.png"
    _ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=2160x3840:rate=1", "-frames:v", "1", str(still))

    frozen = root / "frozen.mp4"
    _ffmpeg("-loop", "1", "-i", str(still), "-t", "2", "-vf", "scale=1080:1920",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(frozen))

    ken_burns = root / "ken_burns.mp4"
    _ffmpeg(
        "-loop", "1", "-i", str(still), "-t", "2",
        "-vf", "zoompan=z='1+0.0012*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
               ":d=60:s=1080x1920:fps=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(ken_burns),
    )

    moving = root / "moving.mp4"
    _ffmpeg("-f", "lavfi", "-i", "life=size=540x960:rate=30:mold=10:ratio=0.1"
            ":death_color=#101010:life_color=#f0f0f0", "-t", "2",
            "-vf", "scale=1080:1920", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(moving))

    return {"frozen": str(frozen), "ken_burns": str(ken_burns), "moving": str(moving)}


def test_frozen_shot_fails(clips: dict[str, str]) -> None:
    report = analyze(clips["frozen"])
    assert report.verdict == "failed"
    assert any("frozen" in reason for reason in report.reasons)


def test_moved_still_fails(clips: dict[str, str]) -> None:
    report = analyze(clips["ken_burns"])
    assert report.verdict == "failed"
    assert report.rigid_ratio > 0.5
    assert any("rigid" in reason or "still" in reason for reason in report.reasons)


def test_real_motion_passes(clips: dict[str, str]) -> None:
    report = analyze(clips["moving"])
    assert report.verdict == "passed", report.reasons
    assert report.residual_energy > 0.0055


def test_assert_motion_raises_on_still(clips: dict[str, str]) -> None:
    with pytest.raises(MotionGateError):
        assert_motion(clips["frozen"])


def test_gate_shots_reports_every_clip(clips: dict[str, str]) -> None:
    result = gate_shots([clips["moving"], clips["ken_burns"]])
    assert result["ok"] is False
    assert result["checked"] == 2
    assert len(result["failures"]) == 1


def test_gate_shots_strict_mode_raises(clips: dict[str, str]) -> None:
    with pytest.raises(MotionGateError):
        gate_shots([clips["ken_burns"]], strict=True)
