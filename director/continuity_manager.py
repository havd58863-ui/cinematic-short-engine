"""Track character/object references and flag continuity gaps before image generation."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .storyboard import Storyboard


def build_continuity_report(board: Storyboard, job_dir: str | Path) -> dict[str, Any]:
    root = Path(job_dir)
    missing_references: list[dict[str, str]] = []
    for shot in board.shots:
        for ref in shot.reference_assets:
            p = Path(ref)
            if not p.is_absolute():
                p = root / p
            if not p.exists():
                missing_references.append({"shot_id": shot.shot_id, "reference": ref})
    ordered = sorted(board.shots, key=lambda item: item.sequence_number)
    notes = []
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.palette != cur.palette:
            notes.append({"severity": "review", "pair": [prev.shot_id, cur.shot_id], "issue": "Palette changed between shots; verify this is an intentional story beat."})
        if not cur.continuity_notes.strip():
            notes.append({"severity": "warning", "shot_id": cur.shot_id, "issue": "No continuity notes supplied."})
    return {
        "visual_identity": board.visual_identity,
        "shots_checked": len(ordered),
        "missing_reference_assets": missing_references,
        "continuity_review_notes": notes,
        "passed": not missing_references,
        "note": "Automated checks verify paths and metadata, not perfect visual identity; inspect generated frames to confirm character consistency.",
    }
