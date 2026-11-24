"""Build a real 1080x1920 demo from mixed sources and prove the gates.

Run: PYTHONPATH=src python3 scripts/demo_pipeline.py --stock /path/to/clip.mp4

The demo exists to make the pipeline falsifiable on a laptop: it generates the
source pool, allocates an edit, runs both gates, renders the master, and prints
measurements. Any shot that is a moved still makes the run fail.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

from engine.contracts import AccountId
from engine.director.allocate import Beat, Clip, SourcePolicy, allocate
from engine.edit.edl import AudioPlan, ShotSource
from engine.edit.look import load_look
from engine.edit.render import render_edl
from engine.edit.subtitles import SubtitleStyle, cues_from_edl, write_ass
from engine.qa.motion_gate import gate_shots
from engine.qa.rhythm_gate import analyze_edl


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def build_plates(root: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    root.mkdir(parents=True, exist_ok=True)
    plates: list[tuple[pathlib.Path, str]] = []

    embers = root / "plate_embers.mp4"
    ffmpeg(
        "-f", "lavfi", "-i",
        "life=size=540x960:rate=30:mold=10:ratio=0.12:death_color=#05070c:life_color=#f2b06a",
        "-t", "6", "-vf", "scale=1080:1920,gblur=sigma=1.2",
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(embers),
    )
    plates.append((embers, "embers"))

    dust = root / "plate_dust.mp4"
    ffmpeg(
        "-f", "lavfi", "-i",
        "life=size=540x960:rate=30:mold=9:ratio=0.16:death_color=#0a0d14:life_color=#9fb6d4",
        "-t", "6", "-vf", "scale=1080:1920,gblur=sigma=2.0",
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(dust),
    )
    plates.append((dust, "dust"))

    rain = root / "plate_rain.mp4"
    ffmpeg(
        "-f", "lavfi", "-i",
        "life=size=540x960:rate=30:mold=17:ratio=0.18:death_color=#05070c:life_color=#c8d6e5",
        "-t", "6", "-vf", "scale=1080:1920,gblur=sigma=1.0,eq=contrast=0.8",
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(rain),
    )
    plates.append((rain, "rain"))

    return plates


def build_music_bed(path: pathlib.Path, seconds: float) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=55:duration={seconds:.1f}",
        "-f", "lavfi", "-i", f"sine=frequency=82.41:duration={seconds:.1f}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={seconds:.1f}:amplitude=0.06",
        "-filter_complex",
        "[0:a]volume=0.35,lowpass=f=220[a0];"
        "[1:a]volume=0.14,lowpass=f=520[a1];"
        "[2:a]lowpass=f=2600,volume=0.10[a2];"
        "[a0][a1][a2]amix=inputs=3:normalize=0,"
        f"tremolo=f=0.13:d=0.55,afade=t=in:st=0:d=2,"
        f"afade=t=out:st={max(0.0, seconds - 3):.1f}:d=3[a]",
        "-map", "[a]", "-c:a", "pcm_s16le", str(path),
    )
    return path


def build_beats() -> list[Beat]:
    lines = [
        ("hook", "You are not lazy. Your brain is protecting you.", "empty room, single silhouette",
         ["room", "silhouette"]),
        ("curiosity", "There is a mechanism behind the pause.", "slow drift over still water",
         ["water", "fog"]),
        ("mechanism", "It is called learned avoidance.", "closed door, light leaking underneath",
         ["door", "light"]),
        ("evidence", "Every time you wait, the relief teaches your body to wait again.", "rain on glass",
         ["rain", "glass"]),
        ("turn", "The loop is not a flaw. It is a shortcut that stopped working.", "corridor turn",
         ["corridor", "embers"]),
        ("realization", "You do not need more will. You need a smaller first step.", "hand reaching light",
         ["light", "hand"]),
        ("payoff", "Start where the fear is quietest.", "wide misty horizon",
         ["mist", "horizon"]),
        ("after_image", "That is how the loop ends.", "empty room, dawn light",
         ["room", "dawn"]),
    ]
    return [
        Beat(id=f"b{index:02d}_{beat_id}", spoken=spoken, visual_intent=intent, tags=tags)
        for index, (beat_id, spoken, intent, tags) in enumerate(lines)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", type=pathlib.Path, nargs="*", default=[],
                        help="optional real footage files to mix in")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("demo/out"))
    parser.add_argument(
        "--with-plates", action="store_true",
        help="allow synthetic plates as filler when real footage runs out",
    )
    parser.add_argument(
        "--account", choices=["psychology", "storytelling"], default="psychology",
        help="which account look and identity to render",
    )
    args = parser.parse_args()

    sources = pathlib.Path("demo/build/sources")
    pool: list[Clip] = []

    plates = build_plates(sources) if args.with_plates else []
    tag_map = {
        "embers": ["embers", "light", "corridor"],
        "dust": ["fog", "water", "mist", "horizon", "dawn"],
        "rain": ["rain", "glass", "door"],
    }
    for path, name in plates:
        pool.append(
            Clip(
                path=str(path),
                source=ShotSource.PLATE,
                tags=tag_map[name],
                duration_seconds=6.0,
            )
        )

    for stock_file in args.stock:
        if not stock_file.exists():
            continue
        for index in range(4):
            pool.append(
                Clip(
                    path=str(stock_file),
                    source=ShotSource.STOCK,
                    tags=["room", "silhouette", "hand", "door", "horizon"],
                    duration_seconds=4.0,
                    in_seconds=float(index) * 2.2,
                )
            )

    beats = build_beats()
    music = build_music_bed(sources / "music_bed.wav", 30.0)
    account = (
        AccountId.PSYCHOLOGY if args.account == "psychology" else AccountId.STORYTELLING
    )
    edl = allocate(
        account,
        "The Loop",
        beats,
        pool,
        look=f"cinematic_{args.account}",
        policy=SourcePolicy(max_share={"stock": 0.75, "generated": 0.2, "plate": 0.9, "title": 0.1}),
        audio=AudioPlan(music_path=str(music), music_gain_db=-20.0),
    )

    spoken = {beat.id: beat.spoken for beat in beats}
    args.out.mkdir(parents=True, exist_ok=True)
    subtitle_path = write_ass(
        cues_from_edl(edl, spoken),
        SubtitleStyle(size=58, margin_v=300),
        (edl.width, edl.height),
        args.out / "captions.ass",
    )
    edl = edl.model_copy(update={"subtitle_path": str(subtitle_path)})

    rhythm = analyze_edl(edl)
    motion = gate_shots([shot.path for shot in edl.shots], strict=True)

    profile = load_look(f"config/looks/{args.account}.yaml")
    result = render_edl(edl, profile, args.out)

    summary = {
        "shot_count": len(edl.shots),
        "duration_seconds": edl.duration_seconds(),
        "source_mix": edl.source_mix(),
        "rhythm_gate": rhythm.as_dict(),
        "motion_gate": {
            "checked": motion["checked"],
            "failures": len(motion["failures"]),
            "warnings": len(motion["warnings"]),
            "energies": [
                {"path": pathlib.Path(report_dict["path"]).name,
                 "raw": report_dict["motion_energy"],
                 "residual": report_dict["residual_energy"],
                 "verdict": report_dict["verdict"]}
                for report_dict in motion["reports"]
            ],
        },
        "files": {"master": str(result.master), "preview": str(result.preview)},
    }
    (args.out / "demo_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
