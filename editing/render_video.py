"""FFmpeg-based vertical rendering, audio mix, subtitles and ffprobe verification."""
from __future__ import annotations
from pathlib import Path
import json
import shutil
import subprocess
from typing import Any

class RenderError(RuntimeError):
    pass


def _run(command: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise RenderError(f"Command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr[-3000:]}")
    return proc


def _escape_filter_path(path: Path) -> str:
    # FFmpeg filter argument escaping for drive colon, apostrophe, backslash and comma.
    value = path.resolve().as_posix()
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def render_video(shot_media: list[tuple[str, float]], narration_path: str | None, output_path: str | Path, subtitles_path: str | None = None, music_path: str | None = None, sfx_path: str | None = None, width: int = 1080, height: int = 1920, fps: int = 30, music_volume: float = 0.14) -> Path:
    """Compose ordered clip files; image assets are animated beforehand by image_to_video fallback."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("Both ffmpeg and ffprobe must be installed.")
    if not shot_media:
        raise RenderError("No shot media supplied.")
    out = Path(output_path); out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / "intermediate"; work.mkdir(exist_ok=True)
    clips: list[Path] = []
    target_duration = 0.0
    for idx, (asset, duration) in enumerate(shot_media):
        src = Path(asset)
        duration = float(duration)
        if duration <= 0:
            raise RenderError(f"Shot {idx} has non-positive duration: {duration}")
        if not src.exists():
            raise RenderError(f"Missing shot asset: {src}")
        clip = work / f"render_shot_{idx:03d}.mp4"
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},setsar=1,format=yuv420p"
        if src.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vf", vf, "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)])
        else:
            frames = max(1, int(round(duration * fps)))
            zoom_vf = f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,crop={width*2}:{height*2},zoompan=z='min(zoom+0.0006,1.06)':d={frames}:s={width}x{height}:fps={fps},setsar=1,format=yuv420p"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(src), "-vf", zoom_vf, "-t", f"{duration:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)])
        clips.append(clip)
        target_duration += duration
    concat_file = work / "video_concat.txt"
    def escape_concat(p: Path) -> str:
        return p.resolve().as_posix().replace("'", "'\\''")
    concat_file.write_text("".join(f"file '{escape_concat(p)}'\n" for p in clips), encoding="utf-8")
    joined = work / "joined_silent.mp4"
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", "-movflags", "+faststart", str(joined)])

    inputs = ["-i", str(joined)]
    audio_tracks: list[dict[str, Any]] = []
    if narration_path:
        narr = Path(narration_path)
        if not narr.exists():
            raise RenderError(f"Missing narration audio: {narr}")
        audio_tracks.append({"role": "narration", "path": narr})
    if music_path:
        music = Path(music_path)
        if not music.exists():
            raise RenderError(f"Missing music audio: {music}")
        audio_tracks.append({"role": "music", "path": music, "loop": True})
    if sfx_path:
        sfx = Path(sfx_path)
        if not sfx.exists():
            raise RenderError(f"Missing sound-effects track: {sfx}")
        audio_tracks.append({"role": "sfx", "path": sfx})

    for track in audio_tracks:
        if track.get("loop"):
            inputs += ["-stream_loop", "-1", "-i", str(track["path"])]
        else:
            inputs += ["-i", str(track["path"])]
        track["input_index"] = len(inputs)  # replaced below with exact media input ordinal
    # Input 0 is the joined video; audio tracks begin at media input index 1.
    for index, track in enumerate(audio_tracks, start=1):
        track["input_index"] = index

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs]
    if subtitles_path:
        subs = Path(subtitles_path)
        if not subs.exists(): raise RenderError(f"Subtitle file does not exist: {subs}")
        escaped = _escape_filter_path(subs)
        if subs.suffix.lower() == ".ass":
            video_filter = f"ass='{escaped}'"
        else:
            video_filter = f"subtitles='{escaped}':force_style='FontName=Arial,FontSize=18,Outline=3,Shadow=1,MarginV=300,MarginL=90,MarginR=90,Alignment=2'"
        command += ["-vf", video_filter]

    if audio_tracks:
        filter_parts = []
        labels = []
        for index, track in enumerate(audio_tracks):
            input_index = track["input_index"]
            label = f"track{index}"
            role = track["role"]
            if role == "music":
                gain = max(0.0, min(float(music_volume), 0.4))
                filter_parts.append(f"[{input_index}:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume={gain:.3f},apad,atrim=duration={target_duration:.3f}[{label}]")
            elif role == "sfx":
                filter_parts.append(f"[{input_index}:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad,atrim=duration={target_duration:.3f}[{label}]")
            else:
                filter_parts.append(f"[{input_index}:a:0]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,apad,atrim=duration={target_duration:.3f}[{label}]")
            labels.append(f"[{label}]")
        if len(labels) == 1:
            filter_parts.append(f"{labels[0]}alimiter=limit=0.95,atrim=duration={target_duration:.3f}[aout]")
        else:
            filter_parts.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=2:normalize=0,alimiter=limit=0.95,atrim=duration={target_duration:.3f}[aout]")
        command += ["-filter_complex", ";".join(filter_parts), "-map", "0:v:0", "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-map", "0:v:0", "-an"]
    command += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps), "-t", f"{target_duration:.3f}", "-movflags", "+faststart", str(out)]
    _run(command, timeout=3600)
    report = validate_video(out, expected_width=width, expected_height=height, expected_duration=target_duration, require_audio=bool(narration_path))
    (out.parent / "intermediate" / "render_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out


def validate_video(path: str | Path, expected_width: int = 1080, expected_height: int = 1920, expected_duration: float | None = None, require_audio: bool = False) -> dict[str, Any]:
    target = Path(path)
    if not target.exists() or target.stat().st_size < 1024:
        raise RenderError(f"Output video is missing or too small: {target}")
    if not shutil.which("ffprobe"): raise RenderError("ffprobe is not installed.")
    proc = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)])
    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video: raise RenderError("Output has no video stream.")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if duration <= 0: raise RenderError("Output duration is invalid.")
    if int(video.get("width", 0)) != expected_width or int(video.get("height", 0)) != expected_height:
        raise RenderError(f"Unexpected dimensions: {video.get('width')}x{video.get('height')}; expected {expected_width}x{expected_height}.")
    if expected_duration is not None and abs(duration - expected_duration) > max(1.0, expected_duration * 0.04):
        raise RenderError(f"Output duration {duration:.2f}s differs from target {expected_duration:.2f}s.")
    if require_audio and not audio:
        raise RenderError("A narration track was required, but the output has no audio stream.")
    if video.get("codec_name") != "h264":
        raise RenderError(f"Unexpected video codec: {video.get('codec_name')} (expected h264).")
    return {"status": "success", "path": str(target), "size_bytes": target.stat().st_size, "duration_seconds": duration, "width": int(video.get("width", 0)), "height": int(video.get("height", 0)), "video_codec": video.get("codec_name"), "pixel_format": video.get("pix_fmt"), "fps": video.get("r_frame_rate"), "has_audio": bool(audio), "audio_codec": audio.get("codec_name") if audio else None}


def analyze_black_and_silence(path: str | Path) -> dict[str, Any]:
    """Best-effort black-frame and silence diagnostics; warnings never override hard validation."""
    result: dict[str, Any] = {"black_frame_check": "not_run", "silence_check": "not_run", "warnings": []}
    black = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"], capture_output=True, text=True)
    result["black_frame_check"] = "completed"
    if "black_start:" in (black.stderr or ""):
        result["warnings"].append("Black-frame intervals were detected; inspect before publishing.")
    silence = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "silencedetect=n=-45dB:d=1.5", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    result["silence_check"] = "completed"
    if "silence_start:" in (silence.stderr or ""):
        result["warnings"].append("One or more audio silence intervals were detected; confirm they are intentional.")
    return result
