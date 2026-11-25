# AGENTS.md

Repository knowledge for future sessions. Keep it factual and short; delete anything that stops being true.

## Environment

- Python is pinned to 3.12 (`requires-python = ">=3.12,<3.13"`). The sandbox default `python3` may be 3.13 — use `uv venv .venv --python 3.12` and `.venv/bin/python`.
- ffmpeg is **not** preinstalled in the dev container. Install a static build and put it on `PATH`; several tests skip themselves when `ffmpeg` is missing (`8 skipped` instead of the full suite).
- `make setup` installs `requirements/locks/dev.txt`. `.venv` created by `uv venv` has no `pip`; use `uv pip install --python .venv/bin/python`.

## Commands

```bash
make test            # pytest, needs ffmpeg for the full 75-test run
make lint            # ruff (E, F, I, UP, B; line-length 110)
make render-demo     # renders demo/out/{master,preview}.mp4
PYTHONPATH=src .venv/bin/python -m engine.cli doctor --json
```

## House rules encoded in code

- **No animated stills.** `engine/qa/motion_gate.py` estimates a rigid transform between frames and measures the residual: `frozen` (no motion) and `rigid-only` (Ken Burns / pan / zoom on a still) both fail. Do not relax `RIGID_RESIDUAL` to make a shot pass; replace the shot.
- **Every shot carries `why` and a narrative function** (`engine/edit/edl.py` rejects shots without them).
- **One look per account**, expressed as FFmpeg filters in `engine/edit/look.py` and configured in `config/looks/*.yaml`. Never grade per video.
- **Cuts are hard by default.** Per-shot fades are opt-in via `shot_fade`; a fade on every cut reads as strobing.
- **Real footage before plates.** `engine/director/allocate.py` sorts by tag overlap, then source priority (stock > generated > plate), and refuses generated faces unless explicitly allowed.
- **Never reuse the same source file back to back**, and prefer clips whose measured luma sits in `[min_luma, max_luma]`.
- **Audio targets**: -14 LUFS integrated, -1.5 dBTP ceiling, music ducked under voice.

## Layout

```
src/engine/edit/       EDL, look, render, subtitles
src/engine/qa/         motion, rhythm, exposure gates
src/engine/director/   allocation, look bible
src/engine/validation.py  script contract (no production caller yet)
src/engine/{research,brain,orchestrator,media,audio}/  empty placeholders
config/looks/          per-account grade profiles
config/accounts/       account DNA
docs/                  pipeline architecture + production readiness (Arabic)
```

## Known gaps

Voice-over (TTS), stock acquisition (Pexels), the script → beats bridge, the orchestrator, and Telegram delivery do not exist yet. `docs/PRODUCTION_READINESS_AR.md` tracks them with evidence.
