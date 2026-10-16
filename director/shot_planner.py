"""Helpers for mapping storyboards to generation tasks."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from .storyboard import Storyboard


def plan_asset_paths(board: Storyboard, job_dir: str | Path) -> Storyboard:
    root = Path(job_dir)
    for shot in board.shots:
        shot.image_path = str(root / "images" / f"{shot.shot_id}.png")
        shot.video_path = str(root / "video_clips" / f"{shot.shot_id}.mp4")
        # Paths are persisted in the board; the pipeline may replace them with cached assets.
    return board


def generation_tasks(board: Storyboard) -> list[dict[str, Any]]:
    return [{
        "shot_id": shot.shot_id,
        "duration_seconds": shot.duration,
        "image_prompt": shot.visual_prompt,
        "negative_prompt": shot.negative_prompt,
        "image_model": shot.image_model,
        "image_settings": shot.image_settings,
        "video_model": shot.video_model,
        "video_settings": shot.video_settings,
        "reference_assets": shot.reference_assets,
        "purpose": shot.purpose,
        "subject_movement": shot.subject_movement,
        "environmental_movement": shot.environmental_movement,
    } for shot in sorted(board.shots, key=lambda item: item.sequence_number)]
