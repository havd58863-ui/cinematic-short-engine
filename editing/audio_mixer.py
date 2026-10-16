"""Audio validation, loudness normalization and segment concatenation using FFmpeg."""
from __future__ import annotations
from pathlib import Path
import json
import shutil
import subprocess
from typing import Any

class AudioMixError(RuntimeError):
    pass


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    if not shutil.which(command[0]):
        raise AudioMixError(f"Required executable not found: {command[0]}")
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode:
        raise AudioMixError(f"Command failed ({proc.returncode}): {' '.join(command)}\n{proc.stderr[-1800:]}")
    return proc


def audio_info(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise AudioMixError(f"Audio file not found: {target}")
    proc = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)])
    data = json.loads(proc.stdout)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not stream:
        raise AudioMixError(f"No audio stream found in {target}")
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    return {"path": str(target), "duration_seconds": duration, "codec": stream.get("codec_name"), "sample_rate": int(stream.get("sample_rate") or 0), "channels": int(stream.get("channels") or 0), "size_bytes": target.stat().st_size}


def normalize_audio(input_path: str | Path, output_path: str | Path, target_lufs: float = -16.0) -> Path:
    target = Path(output_path); target.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_path), "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(target)])
    info = audio_info(target)
    if info["duration_seconds"] <= 0:
        raise AudioMixError("Normalized audio duration is invalid.")
    return target


def concatenate_audio_segments(segment_paths: list[str | Path], output_path: str | Path, pause_seconds: float = 0.18) -> Path:
    """Normalize speech segments, insert actual silence between paragraphs, and concatenate."""
    if not segment_paths:
        raise AudioMixError("No narration segments to concatenate.")
    target = Path(output_path); target.parent.mkdir(parents=True, exist_ok=True)
    work = target.parent / "intermediate"; work.mkdir(exist_ok=True)
    normalized: list[Path] = []
    for i, path in enumerate(segment_paths):
        p = Path(path)
        if not p.exists(): raise AudioMixError(f"Missing narration segment: {p}")
        out = work / f"audio_segment_{i:03d}.wav"
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(p), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out)])
        normalized.append(out)
    sequence: list[Path] = []
    gap = max(0.0, float(pause_seconds))
    if gap > 0:
        for i, segment in enumerate(normalized):
            sequence.append(segment)
            if i != len(normalized) - 1:
                silence = work / f"paragraph_pause_{i:03d}.wav"
                _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{gap:.3f}", "-c:a", "pcm_s16le", str(silence)])
                sequence.append(silence)
    else:
        sequence = normalized
    list_file = work / "audio_concat.txt"
    def quote(path: Path) -> str:
        return path.resolve().as_posix().replace("'", "'\\''")
    list_file.write_text("".join(f"file '{quote(p)}'\n" for p in sequence), encoding="utf-8")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c:a", "pcm_s16le", str(target)])
    info = audio_info(target)
    if info["duration_seconds"] <= 0:
        raise AudioMixError("Concatenated narration has invalid duration.")
    return target


def validate_audio(path: str | Path, min_duration: float = 0.1) -> dict[str, Any]:
    info = audio_info(path)
    if info["duration_seconds"] < min_duration:
        raise AudioMixError(f"Audio is too short ({info['duration_seconds']:.3f}s).")
    return {"status": "success", **info}


def _effect_profile(cue: str, shot_duration: float) -> dict[str, Any] | None:
    text = cue.casefold()
    if not text or text.strip() in {"none", "no sfx", "silence", "intentional silence"}:
        return None
    if any(word in text for word in ("whoosh", "swoosh", "swish", "transition", "sweep")):
        return {"kind": "whoosh", "duration": min(0.75, max(0.35, shot_duration * 0.45)), "volume": 0.16, "placement": "end" if "transition" in text or "end" in text else "start"}
    if any(word in text for word in ("impact", "hit", "boom", "thud", "slam", "crash", "metallic")):
        return {"kind": "impact", "duration": 0.48, "volume": 0.17, "placement": "end" if "end" in text else "start"}
    if any(word in text for word in ("alarm", "alert", "beep", "warning tone")):
        return {"kind": "alarm", "duration": 0.34, "volume": 0.11, "placement": "start"}
    if any(word in text for word in ("tick", "clock", "click", "typing")):
        return {"kind": "tick", "duration": 0.16, "volume": 0.10, "placement": "start"}
    if any(word in text for word in ("heartbeat", "heart beat", "pulse")):
        return {"kind": "heartbeat", "duration": 0.42, "volume": 0.10, "placement": "start"}
    if any(word in text for word in ("static", "glitch", "radio", "interference", "hiss")):
        return {"kind": "static", "duration": min(0.9, max(0.3, shot_duration * 0.4)), "volume": 0.08, "placement": "start"}
    if any(word in text for word in ("drone", "ambience", "ambient", "wind", "rain", "rumble", "tension")):
        return {"kind": "ambience", "duration": min(2.0, max(0.7, shot_duration)), "volume": 0.065, "placement": "start"}
    return None


def _generate_effect(kind: str, duration: float, output: Path) -> None:
    """Create a short procedural, royalty-free synthetic cue with FFmpeg lavfi."""
    output.parent.mkdir(parents=True, exist_ok=True)
    d = max(0.08, float(duration))
    if kind == "whoosh":
        inputs = ["-f", "lavfi", "-i", f"anoisesrc=color=white:sample_rate=48000:duration={d:.3f}"]
        audio = "highpass=f=450,lowpass=f=9500,afade=t=in:st=0:d=0.05,afade=t=out:st=0.10:d=" + f"{max(0.08,d-0.10):.3f},volume=0.22"
        extra: list[str] = ["-af", audio]
    elif kind == "impact":
        low_d = max(0.1, d)
        inputs = ["-f", "lavfi", "-i", f"sine=frequency=58:sample_rate=48000:duration={low_d:.3f}", "-f", "lavfi", "-i", f"anoisesrc=color=pink:sample_rate=48000:duration={low_d:.3f}"]
        graph = f"[0:a]afade=t=out:st=0.025:d={max(0.06,low_d-0.025):.3f},volume=0.24[low];[1:a]highpass=f=900,lowpass=f=8000,afade=t=out:st=0.01:d={max(0.05,low_d-0.01):.3f},volume=0.12[noise];[low][noise]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.9[out]"
        extra = ["-filter_complex", graph, "-map", "[out]"]
    elif kind == "alarm":
        inputs = ["-f", "lavfi", "-i", f"sine=frequency=880:sample_rate=48000:duration={d:.3f}"]
        extra = ["-af", f"afade=t=in:st=0:d=0.02,afade=t=out:st={max(0.02,d-0.08):.3f}:d={min(0.08,d):.3f},volume=0.18"]
    elif kind == "tick":
        inputs = ["-f", "lavfi", "-i", f"sine=frequency=1450:sample_rate=48000:duration={d:.3f}"]
        extra = ["-af", f"highpass=f=800,afade=t=in:st=0:d=0.005,afade=t=out:st={max(0.01,d-0.05):.3f}:d={min(0.05,d):.3f},volume=0.16"]
    elif kind == "heartbeat":
        inputs = ["-f", "lavfi", "-i", f"sine=frequency=55:sample_rate=48000:duration={d:.3f}"]
        extra = ["-af", f"lowpass=f=150,afade=t=out:st={max(0.02,d-0.18):.3f}:d={min(0.18,d):.3f},volume=0.26"]
    elif kind == "static":
        inputs = ["-f", "lavfi", "-i", f"anoisesrc=color=white:sample_rate=48000:duration={d:.3f}"]
        extra = ["-af", f"highpass=f=400,lowpass=f=4300,afade=t=in:st=0:d=0.02,afade=t=out:st={max(0.02,d-0.12):.3f}:d={min(0.12,d):.3f},volume=0.12"]
    else:  # subtle ambience/rumble; kept quiet so it does not mask dialogue.
        inputs = ["-f", "lavfi", "-i", f"anoisesrc=color=pink:sample_rate=48000:duration={d:.3f}"]
        extra = ["-af", f"lowpass=f=850,afade=t=in:st=0:d={min(0.35,d/3):.3f},afade=t=out:st={max(0.01,d-min(0.45,d/3)):.3f}:d={min(0.45,d/3):.3f},volume=0.15"]
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, *extra, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output)]
    _run(command)
    audio_info(output)


def generate_procedural_sfx_track(shots: list[Any], total_duration: float, output_dir: str | Path) -> dict[str, Any]:
    """Turn storyboard sound cues into synchronized, low-level synthetic effects.

    No online assets or paid APIs are used. Cue text that cannot be mapped safely is
    listed as skipped rather than silently assigned a random effect.
    """
    root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
    effect_items: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for shot in sorted(shots, key=lambda item: int(getattr(item, "sequence_number", 0))):
        cues = getattr(shot, "sound_cues", []) or []
        if isinstance(cues, str):
            cues = [cues]
        for cue_index, raw_cue in enumerate(cues[:2], start=1):
            cue = str(raw_cue).strip()
            profile = _effect_profile(cue, float(getattr(shot, "duration", 1.0)))
            if profile is None:
                if cue and cue.casefold() not in {"none", "no sfx", "silence", "intentional silence"}:
                    skipped.append({"shot_id": str(getattr(shot, "shot_id", "unknown")), "cue": cue, "reason": "No safe procedural mapping; a user-supplied licensed asset can be placed manually."})
                continue
            shot_start = float(getattr(shot, "start_seconds", 0.0))
            shot_end = float(getattr(shot, "end_seconds", shot_start + float(getattr(shot, "duration", 1.0))))
            duration = min(float(profile["duration"]), max(0.08, shot_end - shot_start))
            start = shot_end - duration if profile["placement"] == "end" else shot_start + min(0.05, duration * 0.1)
            start = max(0.0, min(start, max(0.0, float(total_duration) - duration)))
            output = root / f"sfx_{len(effect_items)+1:03d}_{str(getattr(shot, 'shot_id', 'shot'))}_{cue_index}.wav"
            try:
                _generate_effect(str(profile["kind"]), duration, output)
                effect_items.append({
                    "shot_id": str(getattr(shot, "shot_id", "unknown")),
                    "cue": cue,
                    "kind": profile["kind"],
                    "path": str(output),
                    "start_seconds": round(start, 3),
                    "duration_seconds": round(duration, 3),
                    "volume": float(profile["volume"]),
                    "method": "ffmpeg_procedural_sfx",
                    "license_note": "Procedurally synthesized with FFmpeg; no third-party recording downloaded.",
                })
            except Exception as exc:
                errors.append({"shot_id": str(getattr(shot, "shot_id", "unknown")), "cue": cue, "error": f"{type(exc).__name__}: {exc}"})
    track_path = None
    if effect_items:
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for item in effect_items:
            command.extend(["-i", item["path"]])
        filters = []
        labels = []
        for index, item in enumerate(effect_items):
            delay = max(0, round(float(item["start_seconds"]) * 1000))
            label = f"s{index}"
            filters.append(f"[{index}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,adelay={delay}|{delay},volume={item['volume']:.3f}[{label}]")
            labels.append(f"[{label}]")
        graph = ";".join(filters) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0:dropout_transition=0,apad,atrim=duration={max(0.1,float(total_duration)):.3f}[aout]"
        track_path = root / "sfx_timeline.wav"
        command.extend(["-filter_complex", graph, "-map", "[aout]", "-t", f"{max(0.1,float(total_duration)):.3f}", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(track_path)])
        try:
            _run(command)
            audio_info(track_path)
        except Exception as exc:
            errors.append({"shot_id": "timeline", "cue": "mix", "error": f"{type(exc).__name__}: {exc}"})
            track_path = None
    status = "success" if track_path and not errors else ("partial_success" if track_path else ("failed" if errors else "no_supported_cues"))
    result = {"status": status, "track_path": str(track_path) if track_path else None, "total_duration_seconds": round(float(total_duration), 3), "effects": effect_items, "skipped_cues": skipped, "errors": errors, "source": "FFmpeg lavfi procedural sound design", "note": "These are synthesized sound effects, not AI-generated narration or downloaded third-party recordings."}
    (root / "sfx_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
