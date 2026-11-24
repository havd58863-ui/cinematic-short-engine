"""Motion gate — enforces the binding rule: real motion, never a moved still.

A still image with a camera push (Ken Burns), a pan, or a slow zoom is fully
explained by one global similarity transform between consecutive frames. Real
footage is not: objects move independently, light flickers, grain crawls.

So the gate estimates a 4-DOF transform (rotation + uniform scale + translation)
per frame pair, warps the previous frame onto the current one, and measures the
residual. Low residual on a frame pair that did move means rigid motion only.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import cv2
import numpy as np

FROZEN_RAW_DIFF = 0.0025
RIGID_RESIDUAL = 0.0055
CUT_RAW_DIFF = 0.1500
MIN_MOTION_ENERGY = 0.0030
MIN_FEATURES = 12
ANTI_ALIAS_SIGMA = 1.2


class MotionGateError(RuntimeError):
    """Raised when footage fails the real-motion requirement."""


@dataclass
class MotionReport:
    path: str
    sampled_pairs: int
    frozen_ratio: float
    rigid_ratio: float
    motion_energy: float
    residual_energy: float
    verdict: str
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sampled_pairs": self.sampled_pairs,
            "frozen_ratio": round(self.frozen_ratio, 4),
            "rigid_ratio": round(self.rigid_ratio, 4),
            "motion_energy": round(self.motion_energy, 5),
            "residual_energy": round(self.residual_energy, 5),
            "verdict": self.verdict,
            "reasons": self.reasons,
        }


def _prepare(frame) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    target_w = 320
    if width > target_w:
        scale = target_w / width
        gray = cv2.resize(gray, (target_w, max(2, int(height * scale))), interpolation=cv2.INTER_AREA)
    return gray


def _pair_metrics(
    prev: np.ndarray, cur: np.ndarray, orb, matcher
) -> tuple[float, float | None]:
    """Return (raw_diff, residual_after_rigid_warp), both normalised 0..1.

    The residual is measured on lightly blurred frames: resampling during a zoom
    produces aliasing that looks like motion, and blur removes it without hiding
    independent object motion.
    """
    raw = float(np.mean(np.abs(cur.astype(np.float32) - prev.astype(np.float32))) / 255.0)
    kp_a, des_a = orb.detectAndCompute(prev, None)
    kp_b, des_b = orb.detectAndCompute(cur, None)
    if des_a is None or des_b is None or len(kp_a) < MIN_FEATURES or len(kp_b) < MIN_FEATURES:
        return raw, None

    matches = matcher.match(des_a, des_b)
    if len(matches) < MIN_FEATURES:
        return raw, None
    matches = sorted(matches, key=lambda m: m.distance)[:200]
    src = np.float32([kp_a[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kp_b[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

    transform, _inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)
    if transform is None:
        return raw, None
    warped = cv2.warpAffine(
        prev, transform, (cur.shape[1], cur.shape[0]),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )
    soft_warped = cv2.GaussianBlur(warped, (5, 5), ANTI_ALIAS_SIGMA)
    soft_current = cv2.GaussianBlur(cur, (5, 5), ANTI_ALIAS_SIGMA)
    residual = float(
        np.mean(np.abs(soft_current.astype(np.float32) - soft_warped.astype(np.float32))) / 255.0
    )
    return raw, residual


def analyze(path: str | pathlib.Path, sample_fps: float = 8.0) -> MotionReport:
    """Decide whether a clip contains real, non-rigid motion."""
    source = pathlib.Path(path)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise MotionGateError(f"cannot open video: {source}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / sample_fps)))
    orb = cv2.ORB_create(nfeatures=600, fastThreshold=7)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    previous: np.ndarray | None = None
    frozen = rigid = moving = 0
    raws: list[float] = []
    residuals: list[float] = []
    frame_index = 0

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index % step:
            frame_index += 1
            continue
        frame_index += 1
        current = _prepare(frame)
        if previous is not None:
            raw, residual = _pair_metrics(previous, current, orb, matcher)
            if raw < CUT_RAW_DIFF:
                raws.append(raw)
                if residual is not None:
                    residuals.append(residual)
                if raw < FROZEN_RAW_DIFF:
                    frozen += 1
                elif residual is not None and residual < RIGID_RESIDUAL:
                    rigid += 1
                else:
                    moving += 1
        previous = current

    capture.release()

    pairs = frozen + rigid + moving
    if pairs == 0:
        return MotionReport(
            str(source), 0, 1.0, 0.0, 0.0, 0.0, "failed", ["no decodable frame pairs"]
        )

    energy = float(np.median(raws))
    # No trackable features means rigidity cannot be claimed: judge on raw motion only.
    residual_energy = float(np.median(residuals)) if residuals else energy
    frozen_ratio = frozen / pairs
    rigid_ratio = rigid / pairs


    reasons: list[str] = []
    if energy < FROZEN_RAW_DIFF * 1.2:
        reasons.append(f"frozen: median frame difference {energy:.4f} — the shot does not move")
    elif residuals and residual_energy < RIGID_RESIDUAL:
        reasons.append(
            f"rigid-only motion: residual {residual_energy:.4f} after removing camera "
            f"pan/zoom — this is a still being moved, which the house rule forbids"
        )
    elif energy < MIN_MOTION_ENERGY:
        reasons.append(f"motion energy too low ({energy:.4f})")

    hard_fail = energy < FROZEN_RAW_DIFF * 1.2 or (
        bool(residuals) and residual_energy < RIGID_RESIDUAL
    )
    verdict = "failed" if hard_fail else ("warning" if reasons else "passed")
    return MotionReport(
        str(source), pairs, frozen_ratio, rigid_ratio, energy, residual_energy, verdict, reasons
    )


def assert_motion(path: str | pathlib.Path, sample_fps: float = 8.0) -> MotionReport:
    report = analyze(path, sample_fps=sample_fps)
    if not report.passed:
        raise MotionGateError(
            f"{pathlib.Path(path).name}: {report.verdict} — " + "; ".join(report.reasons)
        )
    return report


def gate_shots(paths: list[str | pathlib.Path], strict: bool = False) -> dict[str, object]:
    """Check every shot; in strict mode a single failure blocks the render."""
    reports = [analyze(path) for path in paths]
    failures = [report.as_dict() for report in reports if report.verdict == "failed"]
    warnings = [report.as_dict() for report in reports if report.verdict == "warning"]
    if strict and failures:
        raise MotionGateError(f"{len(failures)} shot(s) failed the real-motion gate")
    return {
        "ok": not failures,
        "strict": strict,
        "checked": len(reports),
        "failures": failures,
        "warnings": warnings,
        "reports": [report.as_dict() for report in reports],
    }
