# Production pipeline

One command turns an approved script into a finished vertical video:

```bash
make produce SCRIPT=content/psychology/ep01_reread_messages.json OUT=out/psychology
```

## Stages, in order

| Stage | Module | What it guarantees |
|---|---|---|
| Script gate | `brain/script.py` | The script passes the pre-registered word budgets, hook limit and repetition rules before any compute is spent. |
| Narration | `audio/tts.py` | One audio file per spoken sentence, plus word-level timestamps from the synthesiser itself. No forced aligner, no drift. |
| Voice polish | `audio/polish.py` | High-pass, de-ess, presence lift, gentle compression, limiter, −16 LUFS. Conservative on purpose: over-processing is what makes synthetic voices sound synthetic. |
| Score | `audio/music.py` | A bed generated from the mood table: key, mode, tempo, brightness, pulse. Deterministic for a given seed. |
| Sound design | `audio/sfx.py` | Whoosh on every cut, impact on the turn, riser on the open, sub-drop on the payoff, all placed on one timed stem. |
| Footage | `media/stock.py` | Pexels when `PEXELS_API_KEY` exists, otherwise the curated Commons shelf. Every clip is probed and luma-measured. |
| Edit | `edit/timing.py` | Shot length equals spoken sentence length. A 3.4 second line gets a 3.4 second shot. |
| Captions | `edit/subtitles.py` | Word-by-word fill (`\kf`) driven by the same timestamps as the edit. |
| Mix and master | `edit/render.py` | Music ducked under the voice by sidechain, −14 LUFS, −1.5 dBTP, 1080×1920 at 30 fps. |
| Gates | `qa/` | Motion, rhythm and exposure reports written to `production_report.json`. |

## Why the order matters

Voice first, picture second. Cutting to a pacing template and fitting narration
afterwards is what makes generated video feel detached from its own soundtrack.
Here the narration decides how long each shot lives, and the footage is chosen
afterwards to match the line.

## Adding a script

Scripts live in `content/<account>/<episode>.json` and must pass
`python -m engine.cli validate-script` rules from `config/writing_gate.yaml`.
Each beat carries a `visuals` list: one footage theme per spoken sentence.

## Changing the feel

- Mood: `config/moods.yaml` (root note, mode, tempo, brightness, pulse).
- Voice and pace: the `tone` block in the script (`voice`, `rate`).
- Grade: `config/looks/*.yaml`.
- Footage themes: `config/footage_catalog.yaml`.

## Footage and licensing

Wikimedia Commons clips are licensed (usually CC BY-SA). Every render writes
`credits.txt` next to the master; publish it with the video. Pexels footage does
not require attribution but the file still records the credit line.

The shelf is fetched once by `.github/workflows/footage-shelf.yml` and attached
to a release, so a render never depends on a live download from a host that may
rate-limit the runner.
