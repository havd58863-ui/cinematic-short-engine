from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, timezone

def write_job_report(job_dir: str | Path, status: str, message: str, checks: list[dict] | None = None) -> Path:
    job=Path(job_dir)
    report={"status":status,"message":message,"checked_at_utc":datetime.now(timezone.utc).isoformat(),"checks":checks or [],"warnings":[]}
    p=job/"quality_report.json"; p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    md=["# Quality report", "", f"**Status:** `{status}`", "", message, "", "## Checks"]
    for check in checks or []: md.append(f"- `{check.get('status','unknown')}` — {check.get('name','check')}: {check.get('detail','')}")
    (job/"quality_report.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    return p
