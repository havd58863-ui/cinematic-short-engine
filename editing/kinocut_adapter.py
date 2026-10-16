"""Optional, best-effort Kinocut diagnostics using documented CLI commands.

Kinocut is supplementary: the production path remains FFmpeg and does not break
when Kinocut is not installed or when its diagnostics are unsupported in a runtime.
"""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
from typing import Any


def _run(command: list[str], timeout: int = 180) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {
            "command": command,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-12000:],
            "stderr": (proc.stderr or "")[-12000:],
            "status": "success" if proc.returncode == 0 else "warning",
        }
    except subprocess.TimeoutExpired as exc:
        return {"command": command, "status": "timeout", "error": str(exc)}
    except OSError as exc:
        return {"command": command, "status": "unavailable", "error": str(exc)}


def run_kinocut_qc(video_path: str | Path) -> dict[str, Any]:
    """Run documented `kino doctor` and `kino metric-qc INPUT` when available.

    A missing/unsupported Kinocut CLI is recorded as skipped, never fabricated as
    a passing check. The caller should retain FFmpeg/ffprobe as mandatory QA.
    """
    target = Path(video_path)
    if not target.is_file():
        return {"status": "failed", "reason": "video_not_found", "video_path": str(target)}
    binary = shutil.which("kino")
    if not binary:
        return {
            "status": "not_installed",
            "reason": "kino_executable_not_found",
            "video_path": str(target),
            "required_core_qc": "FFmpeg/ffprobe remains active",
        }
    doctor = _run([binary, "doctor"])
    metric = _run([binary, "metric-qc", str(target)])
    results = [doctor, metric]
    if any(item.get("status") == "success" for item in results):
        status = "success" if all(item.get("status") == "success" for item in results) else "partial_success"
    else:
        status = "warning"
    return {"status": status, "video_path": str(target), "checks": {"doctor": doctor, "metric_qc": metric}}


def write_kinocut_report(video_path: str | Path, report_path: str | Path) -> dict[str, Any]:
    result = run_kinocut_qc(video_path)
    dst = Path(report_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
