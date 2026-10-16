from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .config import Settings
from .pipeline import run_job
from generation.image_generation import environment_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Open-source TikTok AI Director pipeline")
    parser.add_argument("--topic", help="Topic to research; omit for automatic research and topic selection")
    parser.add_argument("--script-file", help="Use a provided script instead of generating one")
    parser.add_argument("--resume", help="Resume an existing job ID or job directory")
    parser.add_argument("--settings", default=None)
    parser.add_argument("--plan-only", action="store_true", help="Create research/script/storyboard only; do not generate media")
    parser.add_argument("--env-check", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_json(args.settings) if args.settings else Settings.from_env()
    if args.env_check:
        print(json.dumps(environment_report(), indent=2)); return
    script = Path(args.script_file).read_text(encoding="utf-8") if args.script_file else None
    try:
        job = run_job(topic=args.topic, script=script, settings=settings, resume_job=args.resume, run_media=not args.plan_only)
        print(f"Job: {job}")
        print(f"Status: {json.loads((job/'run_manifest.json').read_text(encoding='utf-8')).get('status')}")
        print(f"Report: {job/'quality_report.md'}")
        if (job/'final_video.mp4').exists(): print(f"Final MP4: {job/'final_video.mp4'}")
    except Exception as exc:
        print(f"Job failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise

if __name__ == "__main__": main()
