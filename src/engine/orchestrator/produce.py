"""End-to-end production: an approved script in, a finished vertical video out.

The order matters. Voice is synthesised first, shots are cut to the length of
each spoken sentence, and only then is footage chosen and graded. Cutting first
and fitting narration afterwards is what makes generated video feel detached
from its own soundtrack.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re

import yaml

from engine.audio.music import Mood, compose
from engine.audio.polish import polish_voice
from engine.audio.sfx import SfxEvent, compose_bed
from engine.audio.tts import probe_duration, synthesize
from engine.brain.script import assert_valid, load
from engine.brain.script import beats as script_beats
from engine.contracts import AccountId
from engine.director.allocate import Beat, SourcePolicy
from engine.edit.edl import EDL, AudioPlan
from engine.edit.look import load_look
from engine.edit.render import _run, ffmpeg_bin, render_edl
from engine.edit.subtitles import SubtitleStyle, karaoke_cues, write_ass
from engine.edit.timing import BeatAudio, TimedWord, plan_shots
from engine.media.stock import acquire
from engine.qa.exposure_gate import gate as exposure_gate
from engine.qa.motion_gate import gate_shots
from engine.qa.rhythm_gate import analyze_edl

BREATH = 0.22
MAX_SHOT = 7.6
WORDS_PER_SECOND = 2.6


class ProductionError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class ProduceResult:
    account: str
    master: pathlib.Path
    preview: pathlib.Path
    report: dict[str, object]


CONJUNCTIONS = (
    "and ", "but ", "because ", "so ", "yet ", "or ", "which ",
    "that ", "where ", "when ", "while ", "as ", "then ",
)


def _split(text: str, limit_words: int = 24) -> list[str]:
    """Sentence-sized speech units, split further at commas only when too long."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    pieces: list[str] = []
    for sentence in sentences:
        if len(sentence.split()) <= limit_words:
            pieces.append(sentence)
            continue
        clauses = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]
        buffer = ""
        for clause in clauses:
            starts_with_join = clause.lower().startswith(CONJUNCTIONS)
            candidate = f"{buffer} {clause}".strip()
            fits = len(candidate.split()) <= limit_words
            if not buffer or fits or (starts_with_join and len(candidate.split()) <= limit_words + 6):
                buffer = candidate
            else:
                pieces.append(buffer)
                buffer = clause
        if buffer:
            pieces.append(buffer)
    bounded: list[str] = []
    for piece in pieces:
        words = piece.split()
        while len(words) > limit_words + 6:
            bounded.append(" ".join(words[:limit_words]))
            words = words[limit_words:]
        bounded.append(" ".join(words))
    return [piece[0].upper() + piece[1:] if piece and piece[0].islower() else piece for piece in bounded]


def _pad_to(source: pathlib.Path, target: pathlib.Path, seconds: float) -> None:
    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-af", f"apad=whole_dur={seconds:.3f}",
            "-t", f"{seconds:.3f}",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            str(target),
        ],
        what="pad voice segment",
    )


def _concat_audio(paths: list[pathlib.Path], target: pathlib.Path, work: pathlib.Path) -> None:
    listing = work / "voice_concat.txt"
    listing.write_text("".join(f"file '{path.resolve().as_posix()}'\n" for path in paths), encoding="utf-8")
    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(target),
        ],
        what="concat voice",
    )


def _fit(source: pathlib.Path, target: pathlib.Path, limit: float) -> tuple[pathlib.Path, float]:
    from engine.audio.tts import probe_duration

    duration = probe_duration(source)
    if duration <= limit:
        return source, 1.0
    tempo = min(1.35, round(duration / limit, 3))
    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-af", f"atempo={tempo}", "-ar", "48000", "-ac", "2",
            "-c:a", "pcm_s16le", str(target),
        ],
        what="fit voice segment",
    )
    return target, tempo


def _mood(config_dir: pathlib.Path, name: str) -> Mood:
    table = yaml.safe_load((config_dir / "moods.yaml").read_text(encoding="utf-8"))
    if name not in table:
        raise ProductionError(f"unknown mood {name!r}; add it to config/moods.yaml")
    return Mood(name=name, **table[name])


def _sfx_events(spans: list[tuple[float, float, str]], total: float) -> list[SfxEvent]:
    events: list[SfxEvent] = [SfxEvent("riser", 0.0, -26.0)]
    for index, (start, _duration, field) in enumerate(spans):
        if index:
            events.append(SfxEvent("whoosh", max(0.0, start - 0.28), -24.0))
        if field in {"realization", "emotional_turn", "discovery"}:
            events.append(SfxEvent("impact", start, -19.0))
        if field in {"final_line", "payoff"}:
            events.append(SfxEvent("sub_drop", start, -21.0))
    events.append(SfxEvent("sub_drop", max(0.0, total - 1.4), -24.0))
    return events


def produce(
    script_path: str | pathlib.Path,
    out_dir: str | pathlib.Path,
    *,
    pexels_key: str | None = None,
    config_dir: str | pathlib.Path = "config",
    work_dir: str | pathlib.Path | None = None,
    voice: str | None = None,
    rate: str | None = None,
    seed: int = 7,
) -> ProduceResult:
    root = pathlib.Path(out_dir)
    work = pathlib.Path(work_dir) if work_dir else root / "work"
    config = pathlib.Path(config_dir)
    for directory in (root, work, work / "vo", work / "footage"):
        directory.mkdir(parents=True, exist_ok=True)

    script = load(script_path)
    account = AccountId(script["account"])
    report = assert_valid(script, account, config)
    tone = script.get("tone", {})
    voice = voice or tone.get("voice", "en-US-AndrewNeural")
    rate = rate or tone.get("rate", "-4%")
    mood = _mood(config, tone.get("mood", "controlled_tension"))
    print(f"[produce] {script['title']} · {account.value} · mood={mood.name}")

    units: list[tuple[str, str, dict]] = []
    for beat in script_beats(script, account):
        pieces = _split(beat["text"])
        visuals = beat.get("visuals") or [beat["visual"]]
        for index, piece in enumerate(pieces):
            units.append((piece, visuals[index % len(visuals)], beat))

    segments: list[tuple[pathlib.Path, list[TimedWord], float]] = []
    spans: list[tuple[float, float, str]] = []
    cursor = 0.0
    for unit_index, (piece, _, beat) in enumerate(units):
        tag = f"{unit_index:02d}"
        raw = work / "vo" / f"{tag}_raw.mp3"
        clip = synthesize(piece, raw, voice=voice, rate=rate)
        polished = pathlib.Path(polish_voice(raw, work / "vo" / f"{tag}_polished.wav"))
        fitted, tempo = _fit(polished, work / "vo" / f"{tag}_fit.wav", MAX_SHOT - BREATH)
        duration = min(MAX_SHOT, round(probe_duration(fitted) + BREATH, 3))
        padded = work / "vo" / f"{tag}_padded.wav"
        _pad_to(fitted, padded, duration)
        words = [
            TimedWord(word.text, round(word.start / tempo + cursor, 3), round(word.end / tempo + cursor, 3))
            for word in clip.words
        ]
        segments.append((padded, words, duration))
        spans.append((cursor, duration, beat["field"]))
        cursor += duration
        print(f"[produce]   {tag} {duration:5.2f}s · {piece[:58]}")

    total = round(cursor, 3)
    voice_track = work / "voice_full.wav"
    _concat_audio([segment[0] for segment in segments], voice_track, work)

    score = pathlib.Path(compose(mood, total, work / "score.wav", seed=seed))
    sfx = pathlib.Path(compose_bed(_sfx_events(spans, total), total, work / "sfx.wav", seed=seed + 1))

    queries: list[str] = [visual for _, visual, _ in units]
    catalog = config / "footage_catalog.yaml"
    clips = acquire(
        queries,
        work / "footage",
        pexels_key=pexels_key,
        per_query=1,
        catalog=catalog if catalog.exists() else None,
        account=account.value,
    )

    beat_audio: list[BeatAudio] = []
    pairs = zip(units, segments, strict=True)
    for unit_index, ((piece, visual, beat), (_, words, duration)) in enumerate(pairs):
        beat_audio.append(
            BeatAudio(
                beat=Beat(
                    id=f"{unit_index:02d}_{re.sub(r'[^a-z0-9_]+', '_', beat['field'].lower())[:28]}",
                    spoken=piece,
                    visual_intent=beat["why"],
                    tags=sorted({*beat.get("tags", []), *re.sub(r"[^a-z0-9]+", " ", visual.lower()).split()}),
                    weight=1.0,
                ),
                duration=duration,
                words=tuple(words),
            )
        )
    policy = SourcePolicy(min_luma=0.10, max_luma=0.86)
    planned = plan_shots(beat_audio, clips, policy)

    all_words = [word for shot in planned for word in shot.words]
    cues = karaoke_cues([(word.text, word.start, word.end) for word in all_words], max_words=3)
    style = SubtitleStyle(font="DejaVu Serif", size=64, margin_v=300, uppercase=True, fade_ms=0)
    subtitle = write_ass(cues, style, (1080, 1920), root / "captions.ass")

    look_name = "psychology" if account is AccountId.PSYCHOLOGY else "storytelling"
    profile = load_look(look_name, config)
    edl = EDL(
        account=account,
        title=script["title"],
        look=profile.name,
        shots=[shot.shot for shot in planned],
        subtitle_path=str(subtitle),
        audio=AudioPlan(
            voice_path=str(voice_track),
            music_path=str(score),
            music_gain_db=-17.0,
            sfx_paths=[str(sfx)],
            sfx_gain_db=0.0,
            target_lufs=-14.0,
            true_peak_db=-1.5,
        ),
    )
    (root / "edl.json").write_text(edl.model_dump_json(indent=2), encoding="utf-8")

    result = render_edl(edl, profile, root)
    print(f"[produce] rendered {result.duration_seconds}s master")

    shot_paths = sorted((root / "shots").glob("*.mp4"))
    motion = gate_shots([str(path) for path in shot_paths])
    rhythm = analyze_edl(edl)
    exposure = exposure_gate([str(result.master)])

    credits = sorted({clip.credit for clip in clips if clip.credit})
    (root / "credits.txt").write_text("\n".join(credits) + "\n", encoding="utf-8")

    payload = {
        "account": account.value,
        "title": script["title"],
        "mood": mood.name,
        "voice": voice,
        "rate": rate,
        "duration_seconds": result.duration_seconds,
        "shot_count": len(edl.shots),
        "word_count": len(all_words),
        "script_validation": report.model_dump(mode="json"),
        "motion_gate": motion,
        "rhythm_gate": rhythm.as_dict(),
        "exposure_gate": exposure,
        "clips": [
            {
                "path": pathlib.Path(clip.path).name,
                "tags": clip.tags,
                "luma": clip.mean_luma,
                "credit": clip.credit,
            }
            for clip in clips
        ],
        "files": {"master": str(result.master), "preview": str(result.preview), "captions": str(subtitle)},
    }
    (root / "production_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ProduceResult(account.value, result.master, result.preview, payload)
