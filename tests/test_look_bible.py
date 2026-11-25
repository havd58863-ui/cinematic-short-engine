from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

from engine.director.look_bible import build_look_bible, write_look_bible

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg is required to build a fixture video"
)


@pytest.fixture(scope="module")
def reference(tmp_path_factory: pytest.TempPathFactory) -> str:
    root = tmp_path_factory.mktemp("bible")
    parts = []
    for index, colour in enumerate(("red", "blue", "green")):
        part = root / f"part{index}.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"color=c={colour}:s=360x640:r=30:d=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(part)],
            check=True,
        )
        parts.append(part)

    listing = root / "list.txt"
    listing.write_text("".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8")
    joined = root / "reference.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)],
        check=True,
    )
    return str(joined)


def test_look_bible_detects_cuts_and_colour(reference: str) -> None:
    bible = build_look_bible([reference], name="demo")
    targets = bible.targets()
    assert targets["cadence"]["mean_shot_seconds"] > 0
    assert 0.0 <= targets["colour"]["saturation_mean"] <= 1.0
    reference_analysis = bible.references[0]
    assert len(reference_analysis.shot_durations) >= 2
    assert reference_analysis.duration_seconds > 5.0


def test_look_bible_writes_yaml(reference: str, tmp_path: pathlib.Path) -> None:
    bible = build_look_bible([reference], name="demo")
    out = write_look_bible(bible, tmp_path / "bible.yaml")
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["name"] == "demo"
    assert "cadence" in data["targets"]
    assert data["references"][0]["path"].endswith("reference.mp4")
