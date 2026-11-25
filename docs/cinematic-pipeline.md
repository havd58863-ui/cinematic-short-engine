# Cinematic render pipeline

The editor turns a list of beats into one vertical master. Everything here is
deterministic FFmpeg and typed Python, so a phone-triggered GitHub runner
produces the same file as a Kaggle GPU box.

## Flow

```
beats + clip pool ──allocate──▶ EDL ──rhythm gate──▶ ┬──▶ shot pass ──┐
                        │                           │                 ├──▶ concat ──▶ master ──▶ preview
                        └──motion gate (sources)────┴──▶ audio mix ────┘
```

| Stage | Module | Fails when |
| --- | --- | --- |
| Edit decision | `engine.edit.edl` | a shot has no `why`, ids collide, duration > 12s |
| Allocation | `engine.director.allocate` | pool is empty, no clip fits the beat |
| Motion gate | `engine.qa.motion_gate` | a shot is frozen, or moves but is a rigid transform of a still |
| Rhythm gate | `engine.qa.rhythm_gate` | shot > 4s, slow hook, mean cadence outside 1.2–3.5s |
| Render | `engine.edit.render` | FFmpeg refuses the graph |
| Look bible | `engine.director.look_bible` | reference has no decodable frames |

## The real-motion rule

The binding requirement is *no stills being moved*. The gate estimates a
4-DOF transform (rotation, uniform scale, translation) between consecutive
frames, warps the previous frame onto the current one, and measures the
residual after a light blur that removes resampling aliasing.

- A frozen shot: median frame difference below 0.003 → `frozen`.
- A panned or zoomed still: residual below 0.0055 → `rigid-only`.
- Real footage: independent object motion survives the warp → passes.

This is why a Ken Burns montage is rejected by the same test that accepts a
drone shot: the 2D still is fully described by one global transform, a 3D scene
is not.

## Two-pass colour

`shot` pass normalises exposure and white balance per clip so mixed sources
match; `master` pass lays the single film look (curves, halation, grain,
vignette) over the assembled timeline. One look per account, never per video.

Baked-in letterbox is detected with `cropdetect` and removed before scaling, so
cinema-ratio stock fills 1080x1920 instead of appearing as a strip in the middle
of the screen.

## Audio

Voice is the anchor. Music is ducked with a sidechain compressor driven by the
voice track, then the whole mix is normalised to -14 LUFS with -1.5 dBTP
headroom, which is what TikTok and Reels expect.

## Running it

```bash
PYTHONPATH=src python3 scripts/demo_pipeline.py --stock clip_a.mp4 clip_b.mp4 --out demo/out
```

Outputs: `master.mp4` (1080x1920, delivery), `preview.mp4` (540 wide, under
Telegram's 50 MB limit), `manifest.json` (provenance for every shot),
`demo_report.json` (gate measurements).

In CI, run the `cinematic-build (demo)` workflow manually; it renders the demo,
asserts both gates, and uploads the preview as an artifact.
