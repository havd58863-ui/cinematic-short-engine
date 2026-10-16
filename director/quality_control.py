"""Quality report writer used by both the planner and the media pipeline."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


def write_quality_report(job_dir: str | Path, status: str, message: str, checks: list[dict[str, Any]] | None = None, warnings: list[str] | None = None, details: dict[str, Any] | None = None) -> Path:
    if status not in {"success", "partial_success", "failed"}:
        raise ValueError("status must be success, partial_success, or failed")
    root = Path(job_dir)
    root.mkdir(parents=True, exist_ok=True)
    report = {
        "status": status,
        "message": message,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks or [],
        "warnings": warnings or [],
        "details": details or {},
    }
    json_path = root / "quality_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md = ["# TikTok AI Director — Quality Report", "", f"**Status:** `{status}`", "", message, "", "## Checks"]
    for check in checks or []:
        md.append(f"- **{check.get('status','unknown')}** — {check.get('name','check')}: {check.get('detail','')}")
    if warnings:
        md.extend(["", "## Warnings"])
        md.extend(f"- {warning}" for warning in warnings)
    if details:
        md.extend(["", "## Details", "", "```json", json.dumps(details, ensure_ascii=False, indent=2, default=str), "```"])
    (root / "quality_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return json_path
