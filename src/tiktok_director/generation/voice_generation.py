from __future__ import annotations
from pathlib import Path
import numpy as np

class VoiceGenerationUnavailable(RuntimeError): pass

def generate_kokoro(text: str, output_path: str | Path, voice: str = "af_heart", language_code: str = "a", speed: float = 1.0) -> Path:
    try:
        import soundfile as sf
        from kokoro import KPipeline
    except Exception as exc:
        raise VoiceGenerationUnavailable("Kokoro/soundfile is unavailable. Install voice dependencies.") from exc
    try:
        pipeline = KPipeline(lang_code=language_code)
        chunks = []
        for _gs, _ps, audio in pipeline(text, voice=voice, speed=speed):
            if audio is not None:
                chunks.append(audio.cpu().numpy() if hasattr(audio, "cpu") else np.asarray(audio))
        if not chunks:
            raise VoiceGenerationUnavailable("Kokoro returned no audio segments.")
        audio = np.concatenate(chunks).astype(np.float32)
        path = Path(output_path); path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, audio, 24000)
        return path
    except VoiceGenerationUnavailable:
        raise
    except Exception as exc:
        raise VoiceGenerationUnavailable(f"Kokoro TTS failed: {type(exc).__name__}: {exc}") from exc
