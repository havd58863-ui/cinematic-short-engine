"""Whisper transcription and subtitle timing from the actual generated narration."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import re
import hashlib
from difflib import SequenceMatcher

class SubtitleGenerationUnavailable(RuntimeError):
    pass


def _srt_timestamp(seconds: float) -> str:
    ms = max(0, round(float(seconds) * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ass_timestamp(seconds: float) -> str:
    centis = max(0, round(float(seconds) * 100)); h, centis = divmod(centis, 360000); m, centis = divmod(centis, 6000); s, centis = divmod(centis, 100)
    return f"{h}:{m:02}:{s:02}.{centis:02}"


def _group_words(words: list[dict[str, Any]], max_words: int = 5, max_duration: float = 2.2) -> list[dict[str, Any]]:
    chunks = []
    current: list[dict[str, Any]] = []
    start = None
    for word in words:
        value = str(word.get("word", "")).strip()
        if not value:
            continue
        wstart = float(word.get("start", 0))
        wend = float(word.get("end", wstart + 0.2))
        if current and (len(current) >= max_words or wend - float(start) > max_duration or re.search(r"[.!?]$", str(current[-1].get("word", "")))):
            chunks.append({"start": float(start), "end": float(current[-1].get("end", wend)), "text": "".join(str(item.get("word", "")) for item in current).strip()})
            current = []
            start = None
        if not current:
            start = wstart
        # Preserve Whisper's leading whitespace so words remain separated after concatenation.
        current.append({"word": str(word.get("word", "")), "start": wstart, "end": wend})
    if current:
        chunks.append({"start": float(start or 0), "end": float(current[-1].get("end", 0)), "text": "".join(str(item.get("word", "")) for item in current).strip()})
    return [x for x in chunks if x["text"] and x["end"] >= x["start"]]


def _write_srt(segments: list[dict[str, Any]], path: Path) -> None:
    lines = []
    for index, segment in enumerate(segments, 1):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        lines += [str(index), f"{_srt_timestamp(segment['start'])} --> {_srt_timestamp(segment['end'])}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_ass(segments: list[dict[str, Any]], path: Path, font_name: str = "Arial", font_size: int = 54) -> None:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{font_name},{font_size},&H00FFFFFF,&H0000FFFF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,4,1,2,90,90,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for segment in segments:
        text = str(segment.get("text", "")).strip().replace("\n", " ").replace("{", "\\{").replace("}", "\\}")
        if text:
            lines.append(f"Dialogue: 0,{_ass_timestamp(segment['start'])},{_ass_timestamp(segment['end'])},TikTok,,0,0,0,,{text}\n")
    path.write_text("".join(lines), encoding="utf-8")


def _normalized_word(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", value.casefold())


def _correct_timed_words_from_script(words: list[dict[str, Any]], approved_script: str | None) -> tuple[list[dict[str, Any]], int]:
    """Use the approved narration as a spelling/punctuation guide without moving Whisper timestamps.

    Equal and same-length replacement spans can be aligned one-to-one; insertions/deletions are left
    untouched because inventing a timestamp for an unaligned word would be misleading.
    """
    if not approved_script or not words:
        return words, 0
    script_tokens = re.findall(r"\S+", approved_script.strip())
    audio_tokens = [str(item.get("word", "")).strip() for item in words]
    if not script_tokens or not audio_tokens:
        return words, 0
    corrected = [dict(item) for item in words]
    corrections = 0
    matcher = SequenceMatcher(a=[_normalized_word(x) for x in audio_tokens], b=[_normalized_word(x) for x in script_tokens], autojunk=False)
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and (a2 - a1) == (b2 - b1)):
            for offset, index in enumerate(range(a1, a2)):
                source_token = script_tokens[b1 + offset]
                if audio_tokens[index] != source_token:
                    corrections += 1
                prefix = "" if index == 0 else " "
                corrected[index]["word"] = prefix + source_token
    return corrected, corrections


def transcribe_to_subtitles(audio_path: str | Path, srt_path: str | Path, ass_path: str | Path | None = None, model_name: str = "base.en", approved_script: str | None = None, download_root: str | Path | None = None) -> dict[str, Any]:
    audio = Path(audio_path)
    if not audio.exists() or not audio.is_file():
        raise SubtitleGenerationUnavailable(f"Narration audio does not exist: {audio}")
    srt = Path(srt_path); srt.parent.mkdir(parents=True, exist_ok=True)
    ass = Path(ass_path) if ass_path else srt.with_suffix(".ass")
    transcript = srt.with_suffix(".transcript.json")
    cache_manifest = srt.with_suffix(srt.suffix + ".cache.json")
    try:
        audio_digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    except OSError as exc:
        raise SubtitleGenerationUnavailable(f"Could not read narration audio: {exc}") from exc
    cache_key = {"audio_sha256": audio_digest, "model": model_name, "approved_script_sha256": hashlib.sha256((approved_script or "").encode("utf-8")).hexdigest()}
    try:
        stored_key = json.loads(cache_manifest.read_text(encoding="utf-8")) if cache_manifest.is_file() else {}
        transcript_data = json.loads(transcript.read_text(encoding="utf-8")) if transcript.is_file() else {}
        cached_phrases = transcript_data.get("subtitle_phrases") or []
        if stored_key == cache_key and srt.is_file() and ass.is_file() and srt.stat().st_size > 20 and ass.stat().st_size > 50 and cached_phrases:
            return {"status": "success", "srt": str(srt), "ass": str(ass), "transcript": str(transcript), "phrase_count": len(cached_phrases), "model": model_name, "transcribed_text": str(transcript_data.get("text", "")), "cached": True, "script_corrections": transcript_data.get("script_corrections", 0)}
    except Exception:
        pass
    try:
        import whisper
    except Exception as exc:
        raise SubtitleGenerationUnavailable("OpenAI Whisper is not installed. Install requirements-colab.txt, then retry.") from exc
    try:
        model = whisper.load_model(model_name, download_root=str(download_root) if download_root else None)
        result = model.transcribe(str(audio), word_timestamps=True, fp16=False, verbose=False)
        source_segments = result.get("segments", [])
        word_items = [word for segment in source_segments for word in segment.get("words", []) if isinstance(word, dict)]
        corrected_words, corrections = _correct_timed_words_from_script(word_items, approved_script)
        phrases = _group_words(corrected_words) if corrected_words else []
        if not phrases:
            phrases = [{"start": float(seg["start"]), "end": float(seg["end"]), "text": str(seg.get("text", "")).strip()} for seg in source_segments if str(seg.get("text", "")).strip()]
        if not phrases:
            raise SubtitleGenerationUnavailable("Whisper returned no timestamped text; subtitle generation cannot be declared successful.")
        _write_srt(phrases, srt)
        _write_ass(phrases, ass)
        transcript_payload = {"text": result.get("text", ""), "language": result.get("language"), "model": model_name, "segments": source_segments, "timed_words_corrected_from_approved_script": corrected_words, "script_corrections": corrections, "subtitle_phrases": phrases, "approved_script_was_provided": bool(approved_script), "cache_key": cache_key}
        transcript.write_text(json.dumps(transcript_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        cache_manifest.write_text(json.dumps(cache_key, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "success", "srt": str(srt), "ass": str(ass), "transcript": str(transcript), "phrase_count": len(phrases), "model": model_name, "transcribed_text": str(result.get("text", "")).strip(), "cached": False, "script_corrections": corrections}
    except SubtitleGenerationUnavailable:
        raise
    except Exception as exc:
        raise SubtitleGenerationUnavailable(f"Whisper transcription failed: {type(exc).__name__}: {exc}") from exc


def transcribe_to_srt(audio_path: str | Path, srt_path: str | Path, model_name: str = "base.en", approved_script: str | None = None) -> Path:
    return Path(transcribe_to_subtitles(audio_path, srt_path, model_name=model_name, approved_script=approved_script)["srt"])
