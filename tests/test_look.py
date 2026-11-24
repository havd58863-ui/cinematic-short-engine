from __future__ import annotations

import pathlib

import pytest

from engine.edit.look import (
    LookProfile,
    grade_chain,
    load_look,
    master_filter,
    normalize_chain,
    shot_filter,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_builtin_looks_load_and_lock_frame() -> None:
    for name in ("psychology", "storytelling"):
        profile = load_look(f"config/looks/{name}.yaml", ROOT / "config")
        assert profile.output_size() == (1080, 1920)
        assert profile.fps == 30
        assert profile.grain > 0


def test_normalize_chain_covers_the_frame() -> None:
    chain = normalize_chain(LookProfile(name="t"))
    assert "scale=1080:1920" in chain
    assert "force_original_aspect_ratio=increase" in chain
    assert "crop=1080:1920" in chain
    assert chain.endswith("format=yuv420p")


def test_shot_and_master_stages_differ() -> None:
    profile = LookProfile(name="t")
    shot = grade_chain(profile, "shot")
    master = grade_chain(profile, "master")
    assert "unsharp" in shot
    assert "blend=all_mode=screen" in master
    assert "noise=" in master
    assert "vignette" in master
    assert shot != master


def test_grain_and_vignette_can_be_disabled() -> None:
    profile = LookProfile(name="clean", grain=0, vignette=0, halation=0)
    chain = grade_chain(profile, "master")
    assert "noise=" not in chain
    assert "vignette" not in chain
    assert "blend=" not in chain


def test_shot_filter_fades_inside_short_clips() -> None:
    profile = LookProfile(name="t")
    chain = shot_filter(profile, duration=1.6)
    assert "fade=t=in" in chain
    out_at = [part for part in chain.split(",") if part.startswith("fade=t=out")][0]
    assert "st=1.4" in out_at


def test_letterbox_keeps_vertical_master() -> None:
    profile = LookProfile(name="t", letterbox_ratio=2.0)
    chain = normalize_chain(profile, letterbox=True)
    assert "crop=1080:540" in chain
    assert "pad=1080:1920" in chain


def test_master_filter_ends_on_yuv420p() -> None:
    profile = LookProfile(name="t")
    assert master_filter(profile, 12.0).split(",")[-1] == "format=yuv420p"


def test_invalid_profile_rejected() -> None:
    with pytest.raises(ValueError):
        LookProfile(name="t", contrast=9.0)
    with pytest.raises(ValueError):
        LookProfile(name="t", grain=-1)
