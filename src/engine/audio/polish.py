"""Studio polish for synthesised narration.

The chain is deliberately conservative: clean the low end, tame sibilance, add a
little presence, then compress gently. Aggressive processing on TTS is what
makes synthetic voices sound synthetic.
"""

from __future__ import annotations

import pathlib

from engine.edit.render import _run, ffmpeg_bin

VOICE_CHAIN = (
    "highpass=f=85:poles=2,"
    "lowpass=f=14500:poles=2,"
    "afftdn=nf=-30:tn=1,"
    "deesser=i=0.35:m=0.5:f=0.5,"
    "equalizer=f=240:t=q:w=1.1:g=-1.6,"
    "equalizer=f=3100:t=q:w=1.4:g=1.4,"
    "equalizer=f=7800:t=q:w=1.8:g=-1.0,"
    "acompressor=threshold=-19dB:ratio=2.8:attack=9:release=160:makeup=1.5,"
    "alimiter=limit=0.89:level=false,"
    "aresample=48000"
)


def polish_voice(
    source: str | pathlib.Path,
    target: str | pathlib.Path,
    *,
    target_lufs: float = -16.0,
    true_peak: float = -2.0,
) -> str:
    out = pathlib.Path(target)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-af", f"{VOICE_CHAIN},loudnorm=I={target_lufs}:TP={true_peak}:LRA=7",
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            str(out),
        ],
        what="polish voice",
    )
    return str(out)
