"""Cinematic look: one grade applied to every shot so mixed sources read as one film.

The look is the layer that hides the seam between stock footage, generated clips
and abstract plates. It is deliberately deterministic and expressed only as
FFmpeg filters, so the same look renders identically on a phone-triggered
GitHub runner and on a Kaggle GPU machine.
"""

from __future__ import annotations

import pathlib
from typing import Literal

import yaml
from pydantic import Field

from engine.contracts import StrictModel

Stage = Literal["shot", "master"]


class LookProfile(StrictModel):
    """A single, locked visual identity. One profile per account, never per video."""

    name: str = Field(min_length=1, max_length=80)
    width: int = 1080
    height: int = 1920
    fps: int = 30

    contrast: float = Field(default=1.08, ge=0.5, le=2.0)
    saturation: float = Field(default=1.06, ge=0.0, le=2.0)
    gamma: float = Field(default=0.98, ge=0.5, le=2.0)
    brightness: float = Field(default=0.0, ge=-0.3, le=0.3)
    warmth: float = Field(default=0.03, ge=-0.2, le=0.2, description="highlight +R / -B")
    shadow_tint_r: float = Field(default=-0.03, ge=-0.3, le=0.3)
    shadow_tint_b: float = Field(default=0.04, ge=-0.3, le=0.3)
    clarity: float = Field(default=0.35, ge=0.0, le=2.0)

    grain: float = Field(default=5.0, ge=0.0, le=40.0)
    halation: float = Field(default=0.14, ge=0.0, le=1.0)
    halation_sigma: float = Field(default=22.0, ge=2.0, le=80.0)
    vignette: float = Field(default=0.30, ge=0.0, le=1.0)
    letterbox_ratio: float | None = Field(default=None, ge=1.0, le=2.6)

    def output_size(self) -> tuple[int, int]:
        return self.width, self.height


def _n(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".") or "0"


def normalize_chain(
    profile: LookProfile,
    letterbox: bool = False,
    source_crop: str | None = None,
) -> str:
    """Cover-scale any source to the master frame, then optionally add cinema bars.

    `source_crop` is a crop rectangle detected by `detect_content_crop`, applied
    first so footage delivered with baked-in black bars still fills the frame.
    """
    w, h = profile.output_size()
    prefix = [f"crop={source_crop}"] if source_crop else []
    parts = [
        *prefix,
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={w}:{h}",
    ]
    if letterbox and profile.letterbox_ratio:
        box_h = int(round(w / profile.letterbox_ratio / 2) * 2)
        parts = [
            *prefix,
            f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop={w}:{h}",
            f"crop={w}:{box_h}",
            f"pad={w}:{h}:0:{(h - box_h) // 2}:black",
        ]
    parts += [
        f"fps={profile.fps}",
        "setsar=1",
        "format=yuv420p",
    ]
    return ",".join(parts)


def grade_chain(profile: LookProfile, stage: Stage = "shot") -> str:
    """Colour science for one stage.

    `shot` normalises exposure and white balance per clip so mixed sources match.
    `master` lays the single film look over the assembled timeline.
    """
    chain: list[str] = []

    if stage == "shot":
        chain.append(
            "eq="
            f"contrast={_n(profile.contrast)}:"
            f"saturation={_n(profile.saturation)}:"
            f"gamma={_n(profile.gamma)}:"
            f"brightness={_n(profile.brightness)}"
        )
        chain.append("curves=all='0/0 0.24/0.20 0.76/0.82 1/1'")
        chain.append(
            "colorbalance="
            f"rs={_n(profile.shadow_tint_r)}:bs={_n(profile.shadow_tint_b)}:"
            f"rh={_n(profile.warmth)}:bh={_n(-profile.warmth)}"
        )
        if profile.clarity > 0:
            chain.append(f"unsharp=5:5:{_n(profile.clarity)}")
        return ",".join(chain)

    chain.append("curves=all='0/0 0.22/0.18 0.78/0.84 1/1'")
    chain.append(
        "colorbalance="
        f"rs={_n(profile.shadow_tint_r * 0.6)}:bs={_n(profile.shadow_tint_b * 0.6)}:"
        f"rh={_n(profile.warmth * 0.6)}:bh={_n(-profile.warmth * 0.6)}"
    )
    if profile.halation > 0:
        chain.append(
            "split=2[b0][b1];"
            f"[b1]gblur=sigma={_n(profile.halation_sigma)},"
            "eq=brightness=0.06:contrast=1.25[hh];"
            f"[b0][hh]blend=all_mode=screen:all_opacity={_n(profile.halation)}"
        )
    if profile.grain > 0:
        chain.append(f"noise=alls={int(profile.grain)}:allf=t+u")
    if profile.vignette > 0:
        angle = 3.14159 * (0.10 + 0.25 * profile.vignette)
        chain.append(f"vignette=angle={_n(angle)}")
    return ",".join(chain)


def shot_filter(
    profile: LookProfile,
    duration: float,
    letterbox: bool = False,
    source_crop: str | None = None,
) -> str:
    """Full per-shot filter: normalise, grade, and fade the edges of the clip."""
    chain = [
        normalize_chain(profile, letterbox=letterbox, source_crop=source_crop),
        grade_chain(profile, "shot"),
    ]
    fade = min(0.25, max(0.0, duration / 8))
    if fade > 0:
        chain.append(f"fade=t=in:st=0:d={_n(fade)}")
        chain.append(f"fade=t=out:st={_n(max(0.0, duration - fade))}:d={_n(fade)}")
    return ",".join(chain)


def master_filter(profile: LookProfile, duration: float, letterbox: bool = False) -> str:
    parts = [grade_chain(profile, "master")]
    if letterbox and profile.letterbox_ratio:
        w, h = profile.output_size()
        box_h = int(round(w / profile.letterbox_ratio / 2) * 2)
        parts = [
            f"scale={w}:{h}:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:0:{(h - box_h) // 2}:black",
            *parts,
        ]
    parts.append("fade=t=in:st=0:d=0.3")
    parts.append(f"fade=t=out:st={_n(max(0.0, duration - 0.4))}:d=0.4")
    parts.append("format=yuv420p")
    return ",".join(parts)


BUILTIN_LOOKS: dict[str, str] = {
    "psychology": "config/looks/psychology.yaml",
    "storytelling": "config/looks/storytelling.yaml",
}


def load_look(path_or_name: str | pathlib.Path, config_dir: str | pathlib.Path | None = None) -> LookProfile:
    """Load a look by YAML path or by built-in name."""
    path = pathlib.Path(path_or_name)
    if not path.suffix:
        path = pathlib.Path(BUILTIN_LOOKS[path_or_name])
    if not path.is_absolute() and config_dir is not None:
        candidate = pathlib.Path(config_dir).parent / path
        if candidate.exists():
            path = candidate
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Look file must contain a mapping: {path}")
    return LookProfile(**data)
