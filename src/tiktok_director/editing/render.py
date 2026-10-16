from __future__ import annotations
from pathlib import Path
import json, shutil, subprocess

class RenderError(RuntimeError): pass

def _run(command: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode:
        raise RenderError(f"Command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr[-3000:]}")
    return proc

def render_video(shot_media: list[tuple[str, float]], narration_path: str | None, output_path: str | Path, subtitles_path: str | None = None, music_path: str | None = None, width: int = 1080, height: int = 1920, fps: int = 30) -> Path:
    """Render ordered clips; still-image paths get FFmpeg pan/zoom; supplied video clips are cropped to portrait."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RenderError("Both ffmpeg and ffprobe must be installed.")
    if not shot_media:
        raise RenderError("No shot media supplied.")
    out = Path(output_path); out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / "intermediate"; work.mkdir(exist_ok=True)
    clip_paths: list[Path] = []
    for idx, (asset, duration) in enumerate(shot_media):
        src = Path(asset)
        if not src.exists(): raise RenderError(f"Missing shot asset: {src}")
        clip = work / f"shot_{idx:03d}.mp4"
        if src.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
            vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps},format=yuv420p"
            _run(["ffmpeg","-y","-i",str(src),"-vf",vf,"-t",str(duration),"-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p","-an",str(clip)])
        else:
            frames = max(1, round(duration * fps))
            vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},zoompan=z='min(zoom+0.0006,1.06)':d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
            _run(["ffmpeg","-y","-loop","1","-i",str(src),"-vf",vf,"-t",str(duration),"-an","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p",str(clip)])
        clip_paths.append(clip)
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in clip_paths), encoding="utf-8")
    joined = work / "joined.mp4"
    _run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(joined)])
    inputs = ["-i", str(joined)]
    if narration_path:
        if not Path(narration_path).exists(): raise RenderError(f"Missing narration audio: {narration_path}")
        inputs += ["-i",str(narration_path)]
    if music_path:
        if not Path(music_path).exists(): raise RenderError(f"Missing music audio: {music_path}")
        inputs += ["-i",str(music_path)]
    command = ["ffmpeg","-y",*inputs]
    video_filter = "[0:v]"
    if subtitles_path:
        srt = Path(subtitles_path)
        if not srt.exists(): raise RenderError(f"Missing subtitle file: {srt}")
        safe = str(srt.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        command += ["-vf",f"subtitles='{safe}':force_style='FontName=Arial,FontSize=16,Outline=2,Shadow=0,MarginV=250,Alignment=2'"]
    audio_inputs = []
    if narration_path: audio_inputs.append("1:a")
    if music_path: audio_inputs.append("2:a" if narration_path else "1:a")
    if audio_inputs:
        if len(audio_inputs) == 1:
            command += ["-map","0:v:0","-map",f"{audio_inputs[0]}","-c:a","aac","-b:a","192k"]
        else:
            # narration is clear foreground; music is ducked with a low gain.
            command += ["-filter_complex",f"[{audio_inputs[0]}]volume=1.0[narr];[{audio_inputs[1]}]volume=0.16[music];[narr][music]amix=inputs=2:duration=first:dropout_transition=2[aout]","-map","0:v:0","-map","[aout]","-c:a","aac","-b:a","192k"]
    else:
        command += ["-map","0:v:0","-an"]
    command += ["-c:v","libx264","-preset","medium","-crf","20","-pix_fmt","yuv420p","-r",str(fps),"-movflags","+faststart",str(out)]
    _run(command)
    validate_video(out, expected_width=width, expected_height=height)
    return out

def validate_video(path: str | Path, expected_width: int = 1080, expected_height: int = 1920) -> dict:
    if not shutil.which("ffprobe"): raise RenderError("ffprobe is not installed.")
    proc = _run(["ffprobe","-v","error","-show_streams","-show_format","-of","json",str(path)])
    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams",[]) if s.get("codec_type") == "video"), None)
    if not video: raise RenderError("Output has no video stream.")
    duration = float(data.get("format",{}).get("duration") or 0)
    if duration <= 0: raise RenderError("Output duration is invalid.")
    if int(video.get("width",0)) != expected_width or int(video.get("height",0)) != expected_height:
        raise RenderError(f"Unexpected dimensions: {video.get('width')}x{video.get('height')}; expected {expected_width}x{expected_height}.")
    return {"status":"success","path":str(path),"duration_seconds":duration,"width":video.get("width"),"height":video.get("height"),"video_codec":video.get("codec_name"),"pixel_format":video.get("pix_fmt"),"has_audio":any(s.get("codec_type")=="audio" for s in data.get("streams",[]))}
