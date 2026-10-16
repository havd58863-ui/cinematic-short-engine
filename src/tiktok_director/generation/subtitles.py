from __future__ import annotations
from pathlib import Path
import json

class SubtitleGenerationUnavailable(RuntimeError): pass

def _srt_timestamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def transcribe_to_srt(audio_path: str | Path, srt_path: str | Path, model_name: str = "base.en", approved_script: str | None = None) -> Path:
    try:
        import whisper
    except Exception as exc:
        raise SubtitleGenerationUnavailable("OpenAI Whisper is not installed. Install subtitle dependencies.") from exc
    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), word_timestamps=True, fp16=False)
        segments = result.get("segments", [])
        out = Path(srt_path); out.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        index = 1
        for seg in segments:
            text = str(seg.get("text", "")).strip()
            if not text: continue
            lines.extend([str(index), f"{_srt_timestamp(float(seg['start']))} --> {_srt_timestamp(float(seg['end']))}", text, ""])
            index += 1
        out.write_text("\n".join(lines), encoding="utf-8")
        # Keep Whisper transcript as separate provenance rather than silently rewriting its timings.
        out.with_suffix(".transcript.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return out
    except Exception as exc:
        raise SubtitleGenerationUnavailable(f"Whisper transcription failed: {type(exc).__name__}: {exc}") from exc
