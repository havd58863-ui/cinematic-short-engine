"""Deterministic FFmpeg renderer: EDL in, one vertical master out.

Three passes keep the job cheap and debuggable on a 2-core GitHub runner:
  1. normalise each shot (scale/fps/short grade)  -> seamless sources
  2. concat with hard cuts                        -> continuous timeline
  3. master pass (film look + subtitles) + audio  -> delivery file
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from engine.edit.edl import EDL, AudioPlan
from engine.edit.look import LookProfile, master_filter, shot_filter


class RenderError(RuntimeError):
    """Raised when FFmpeg refuses or cannot produce the requested output."""


@dataclass
class RenderResult:
    master: pathlib.Path
    preview: pathlib.Path | None
    manifest: pathlib.Path
    duration_seconds: float
    shots: list[str] = field(default_factory=list)


def _run(args: list[str], *, what: str) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise RenderError(f"{what} failed ({proc.returncode}):\n" + "\n".join(tail))


def ffmpeg_bin() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RenderError("ffmpeg is not installed")
    return binary


def ffprobe_bin() -> str:
    binary = shutil.which("ffprobe")
    if not binary:
        raise RenderError("ffprobe is not installed")
    return binary


def detect_content_crop(path: str | pathlib.Path, seconds: float = 1.0, limit: int = 24) -> str | None:
    """Return 'W:H:X:Y' when the file ships with baked-in black bars.

    Cinema-ratio stock is often delivered as 16:9 with hard bars burned in. Left
    alone, those bars survive the cover-scale and the video reads as a postage
    stamp on a phone screen.
    """
    proc = subprocess.run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-ss", "0", "-t", f"{seconds:.2f}",
            "-i", str(path), "-vf", f"cropdetect=limit={limit}:round=2:reset=0",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    matches = re.findall(r"crop=(\d+:\d+:\d+:\d+)", proc.stderr or "")
    if not matches:
        return None
    width, height, x, y = (int(part) for part in matches[-1].split(":"))
    probe = subprocess.run(
        [
            ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        return None
    source_w, source_h = (int(part) for part in probe.stdout.strip().split(",")[:2])
    if width >= source_w - 8 and height >= source_h - 8:
        return None
    return matches[-1]


def render_shot(
    shot,
    profile: LookProfile,
    out_path: pathlib.Path,
    letterbox: bool = False,
    source_crop: str | None = None,
) -> None:
    chain = shot_filter(
        profile, shot.duration_seconds / max(shot.speed, 0.01),
        letterbox=letterbox, source_crop=source_crop,
    )
    args = [
        ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{shot.start_seconds:.3f}",
        "-t", f"{shot.duration_seconds * shot.speed:.3f}",
        "-i", shot.path,
        "-vf", chain,
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(profile.fps),
        str(out_path),
    ]
    if shot.speed != 1.0:
        args[args.index("-vf") + 1] = chain + f",setpts={1.0 / shot.speed:.6f}*PTS"
    _run(args, what=f"render shot {shot.id}")


def concat_shots(shot_paths: list[pathlib.Path], out_path: pathlib.Path, work: pathlib.Path) -> None:
    listing = work / "concat.txt"
    listing.write_text(
        "".join(f"file '{path.resolve().as_posix()}'\n" for path in shot_paths),
        encoding="utf-8",
    )
    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(out_path),
        ],
        what="concat shots",
    )


def mix_audio(plan: AudioPlan, duration: float, out_path: pathlib.Path) -> None:
    """Voice over music with sidechain ducking, normalised to the platform target."""
    inputs: list[str] = []
    graph: list[str] = []
    labels: list[str] = []
    index = 0

    if plan.voice_path:
        inputs += ["-i", plan.voice_path]
        graph.append(f"[{index}:a]volume=1.0,aformat=channel_layouts=stereo[vo]")
        labels.append("[vo]")
        index += 1

    if plan.music_path:
        inputs += ["-stream_loop", "-1", "-i", plan.music_path]
        graph.append(f"[{index}:a]volume={plan.music_gain_db}dB,aformat=channel_layouts=stereo[mus]")
        labels.append("[mus]")
        index += 1

    for sfx in plan.sfx_paths:
        inputs += ["-i", sfx]
        graph.append(f"[{index}:a]volume={plan.sfx_gain_db}dB,aformat=channel_layouts=stereo[sfx{index}]")
        labels.append(f"[sfx{index}]")
        index += 1

    if not labels:
        args = [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", f"{duration:.3f}", str(out_path),
        ]
        _run(args, what="silent audio bed")
        return

    if plan.voice_path and plan.music_path:
        graph.append(
            "[mus][vo]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[musd]"
        )
        labels = ["[vo]", "[musd]"] + labels[2:]

    mix_inputs = "".join(labels)
    graph.append(
        f"{mix_inputs}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"atrim=0:{duration:.3f},asetpts=N/SR/TB,"
        f"loudnorm=I={plan.target_lufs}:TP={plan.true_peak_db}:LRA=11,"
        "aresample=48000[aout]"
    )

    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", ";".join(graph),
            "-map", "[aout]",
            "-t", f"{duration:.3f}",
            str(out_path),
        ],
        what="audio mix",
    )


def render_master(
    timeline: pathlib.Path,
    audio: pathlib.Path,
    out_path: pathlib.Path,
    profile: LookProfile,
    duration: float,
    subtitle_path: str | None = None,
    letterbox: bool = False,
) -> None:
    chain = master_filter(profile, duration, letterbox=letterbox)
    if subtitle_path:
        escaped = pathlib.Path(subtitle_path).as_posix().replace(":", r"\:").replace("'", r"\'")
        chain += f",ass='{escaped}'"
    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(timeline), "-i", str(audio),
            "-vf", chain,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-maxrate", "14M", "-bufsize", "28M",
            "-profile:v", "high", "-level", "4.2",
            "-pix_fmt", "yuv420p", "-r", str(profile.fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-shortest",
            str(out_path),
        ],
        what="master render",
    )


def render_preview(master: pathlib.Path, out_path: pathlib.Path, width: int = 540) -> None:
    """Phone-sized preview that stays under Telegram's 50MB send limit."""
    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(master),
            "-vf", f"scale={width}:-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", str(out_path),
        ],
        what="preview encode",
    )


def render_edl(
    edl: EDL,
    profile: LookProfile,
    out_dir: str | pathlib.Path,
    letterbox: bool = False,
    keep_intermediates: bool = True,
) -> RenderResult:
    root = pathlib.Path(out_dir)
    shots_dir = root / "shots"
    work = root / "work"
    shots_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    crops: dict[str, str | None] = {}
    rendered: list[pathlib.Path] = []
    for position, shot in enumerate(edl.shots):
        if shot.path not in crops:
            crops[shot.path] = detect_content_crop(shot.path)
        target = shots_dir / f"{position:02d}_{shot.id}.mp4"
        render_shot(
            shot, profile, target,
            letterbox=letterbox, source_crop=crops[shot.path],
        )
        rendered.append(target)

    timeline = work / "timeline.mp4"
    concat_shots(rendered, timeline, work)

    duration = edl.duration_seconds()
    audio = work / "mix.wav"
    mix_audio(edl.audio, duration, audio)

    master = root / "master.mp4"
    render_master(
        timeline, audio, master, profile, duration,
        subtitle_path=edl.subtitle_path, letterbox=letterbox,
    )

    preview = root / "preview.mp4"
    render_preview(master, preview)

    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "account": edl.account.value,
                "title": edl.title,
                "look": profile.name,
                "duration_seconds": duration,
                "shot_count": len(edl.shots),
                "source_mix": edl.source_mix(),
                "shots": [
                    {
                        "id": shot.id,
                        "source": shot.source.value,
                        "duration": shot.duration_seconds,
                        "why": shot.why,
                        "narrative_function": shot.narrative_function,
                    }
                    for shot in edl.shots
                ],
                "files": {"master": str(master), "preview": str(preview)},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if not keep_intermediates:
        shutil.rmtree(shots_dir, ignore_errors=True)

    return RenderResult(
        master=master,
        preview=preview,
        manifest=manifest,
        duration_seconds=duration,
        shots=[path.name for path in rendered],
    )
