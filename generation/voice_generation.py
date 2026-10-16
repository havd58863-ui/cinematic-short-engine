"""Kokoro-82M speech synthesis from text; no user audio upload required."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
from typing import Any

class VoiceGenerationUnavailable(RuntimeError):
    pass


def _synthesize_with_pipeline(text: str, pipeline: Any, output_path: Path, voice: str, speed: float, sample_rate: int) -> Path:
    import numpy as np
    import soundfile as sf
    chunks = []
    for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed):
        if audio is None:
            continue
        chunks.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
    if not chunks:
        raise VoiceGenerationUnavailable("Kokoro returned no audio segments.")
    waveform = np.concatenate(chunks).astype(np.float32)
    if waveform.size == 0 or not np.isfinite(waveform).all():
        raise VoiceGenerationUnavailable("Kokoro output is empty or contains invalid numeric values.")
    fade_n = min(int(sample_rate * 0.015), max(1, waveform.size // 10))
    waveform[:fade_n] *= np.linspace(0, 1, fade_n, dtype=np.float32)
    waveform[-fade_n:] *= np.linspace(1, 0, fade_n, dtype=np.float32)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, waveform, sample_rate, subtype="PCM_16")
    return output_path


def generate_kokoro(text: str, output_path: str | Path, voice: str = "af_heart", language_code: str = "a", speed: float = 1.0, sample_rate: int = 24000) -> Path:
    if not text.strip():
        raise VoiceGenerationUnavailable("Cannot synthesize an empty script.")
    try:
        from kokoro import KPipeline
    except Exception as exc:
        raise VoiceGenerationUnavailable("Kokoro is required. Install requirements-colab.txt, then restart the runtime if needed.") from exc
    try:
        pipeline = KPipeline(lang_code=language_code)
        target = Path(output_path)
        _synthesize_with_pipeline(text, pipeline, target, voice, speed, sample_rate)
        digest = hashlib.sha256(json.dumps({"text": text, "voice": voice, "language": language_code, "speed": speed}, sort_keys=True).encode()).hexdigest()
        target.with_suffix(target.suffix + ".sha256").write_text(digest + "\n", encoding="utf-8")
        return target
    except VoiceGenerationUnavailable:
        raise
    except Exception as exc:
        raise VoiceGenerationUnavailable(f"Kokoro TTS failed: {type(exc).__name__}: {exc}") from exc


def _valid_cached_wav(path: Path) -> bool:
    try:
        import soundfile as sf
        info = sf.info(str(path))
        return path.is_file() and path.stat().st_size > 1024 and info.frames > 0 and info.samplerate > 0 and info.duration > 0
    except Exception:
        return False


def generate_kokoro_paragraphs(paragraphs: list[str], output_dir: str | Path, voice: str = "af_heart", language_code: str = "a", speed: float = 1.0) -> dict[str, Any]:
    """Generate narration paragraphs with one loaded pipeline and resume valid cached WAVs."""
    cleaned = [p.strip() for p in paragraphs if p.strip()]
    if not cleaned:
        raise VoiceGenerationUnavailable("No non-empty narration paragraphs supplied.")
    root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
    planned: list[dict[str, Any]] = []
    for index, paragraph in enumerate(cleaned, start=1):
        path = root / f"narration_{index:03d}.wav"
        digest = hashlib.sha256(json.dumps({"text": paragraph, "voice": voice, "language": language_code, "speed": speed, "model": "Kokoro-82M"}, sort_keys=True).encode()).hexdigest()
        marker = path.with_suffix(path.suffix + ".sha256")
        try:
            marker_matches = marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest
        except OSError:
            marker_matches = False
        cached = marker_matches and _valid_cached_wav(path)
        planned.append({"index": index, "paragraph": paragraph, "path": path, "digest": digest, "marker": marker, "cached": cached})

    pending = [item for item in planned if not item["cached"]]
    pipeline = None
    if pending:
        try:
            import soundfile as sf  # noqa: F401
            from kokoro import KPipeline
            pipeline = KPipeline(lang_code=language_code)
        except Exception as exc:
            raise VoiceGenerationUnavailable("Kokoro and soundfile are required to generate uncached narration. Install requirements-colab.txt.") from exc

    try:
        for item in pending:
            _synthesize_with_pipeline(item["paragraph"], pipeline, item["path"], voice, speed, 24000)
            if not _valid_cached_wav(item["path"]):
                item["path"].unlink(missing_ok=True)
                raise VoiceGenerationUnavailable(f"Kokoro output failed WAV validation: {item['path']}")
            item["marker"].write_text(item["digest"] + "\n", encoding="utf-8")
        return {
            "status": "success",
            "segments": [str(item["path"]) for item in planned],
            "voice": voice,
            "language_code": language_code,
            "paragraph_count": len(planned),
            "cached_segments": sum(bool(item["cached"]) for item in planned),
            "generated_segments": len(pending),
            "model": "Kokoro-82M",
        }
    except VoiceGenerationUnavailable:
        raise
    except Exception as exc:
        raise VoiceGenerationUnavailable(f"Kokoro paragraph synthesis failed: {type(exc).__name__}: {exc}") from exc
