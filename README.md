# Cinematic Short Engine — Open-source TikTok AI Director

A reusable, resumable TikTok video-production pipeline for Google Colab + Google Drive. The default output is American English, US audience, vertical 9:16 H.264 MP4.

## Production stages and actual tool assignments

| Stage | Tool / model | Role |
|---|---|---|
| Trend entry point | [TikTok Creative Center](https://ads.tiktok.com/creative/creativeCenter/trends) | Official trend source where accessible; does not assume unrestricted API access |
| Research | [DDGS](https://github.com/deedy5/ddgs), [Trafilatura](https://github.com/adbar/trafilatura) | Public search, article extraction and source provenance |
| Optional search signal | [pytrends](https://github.com/GeneralMills/pytrends) | Google search-interest only, never TikTok performance data |
| Script | Existing writer adapter or [Ollama](https://github.com/ollama/ollama) + `qwen2.5:3b-instruct` | Coherent script with hook, escalation, payoff; no paid LLM API required |
| Director/storyboard | Pydantic v2 + Ollama structured JSON | Timed shots, positive/negative prompts, camera and motion, visual identity, sound, subtitles, paths |
| Image generation | [Diffusers](https://github.com/huggingface/diffusers) + `stabilityai/stable-diffusion-xl-base-1.0` | Generate a unique image for each shot; lower-memory SD 1.5 fallback is explicit |
| Reference consistency | [IP-Adapter](https://github.com/tencent-ailab/IP-Adapter) through Diffusers | Optional image conditioning when a compatible reference file exists and weights load |
| Real image-to-video | Diffusers + Wan 2.1 I2V only with >=48 GB VRAM and >=100 GB free model-cache storage, or Stable Video Diffusion XT with >=12 GB VRAM | Neural motion; exact method/model is recorded per shot |
| Video fallback | FFmpeg image animation | Real pan/zoom animation, explicitly labelled `ffmpeg_animation` — not neural video |
| Voice | [Kokoro-82M](https://github.com/hexgrad/kokoro), `af_heart` | Text-to-speech, no user audio upload required |
| Subtitle timing | [Whisper](https://github.com/openai/whisper) | Transcribe actual generated audio, write SRT + ASS |
| Rendering/mix/validation | [FFmpeg](https://github.com/FFmpeg/FFmpeg) + `ffprobe` | 1080×1920 MP4, caption burn-in, audio mix and technical validation |
| Optional low-resource stills | Pixabay/Pexels APIs in `generation/stock_images.py` | Only if configured with a provider key; recorded as stock, never called AI-generated |
| Edit integration candidate | [Kinocut](https://github.com/KyaniteLabs/kinocut) | Not on the critical path until CLI/API compatibility is actually verified |

See `TOOLS_MANIFEST.yaml` for each module, model URL, role, hardware gate and licensing caveat.

## One-time setup in Colab

1. Open `notebook/run_pipeline.ipynb` in Google Colab.
2. Choose a GPU runtime if available (Runtime → Change runtime type → T4 GPU). Neural video generation is optional and depends on actual VRAM.
3. Run all notebook cells. It mounts Drive, clones the repository (a private repository requires a `GITHUB_TOKEN` Colab Secret), installs Python dependencies without blindly replacing Colab's Torch build, starts Ollama if needed, and pulls `qwen2.5:3b-instruct`.
4. In the job cell, leave `TOPIC = None` to research and rank candidate topics, enter a topic to research it, or supply `SCRIPT_TEXT`/`SCRIPT_FILE` to preserve a script. Set `RESUME_JOB` to an existing job ID to resume cached stages.
5. Find artifacts in `Google Drive/TikTokAIDirector/jobs/JOB_ID/`.

Optional Pixabay/Pexels credentials can be added under Colab Secrets as `PIXABAY_API_KEY` and/or `PEXELS_API_KEY`. They are not mandatory for the main image model, but can supply disclosed stock-image fallbacks if diffusion cannot run. Never commit API keys.

## Local installation

Use Python 3.10+ and install FFmpeg separately. Install a Torch build compatible with your compute environment before the optional model dependencies.

```bash
python -m pip install -e . --no-deps
python -m pip install -r requirements-colab.txt
pytest -q
python -m tiktok_director.cli --env-check
python -m tiktok_director.cli --topic "Your topic" --plan-only
```

The complete render can be run with `python -m tiktok_director.cli --topic "Your topic"` after Ollama and the required generation dependencies/models are available. For automatic topic selection, omit `--topic`.

## Resume and outputs

Each job has a unique ID. Assets and `run_manifest.json` persist per stage. The pipeline verifies cached image fingerprints, preserves completed artifacts after an error, records failure state, and can resume with `--resume JOB_ID`.

Output tree includes research evidence, ranked ideas, competitor examples, script, script analysis, validated storyboard, continuity report, image report, narration segments, combined narration, SRT/ASS captions, per-shot MP4s, final `final_video.mp4`, `quality_report.json`, and `quality_report.md`.

## Important reliability limits

No software system can guarantee zero errors in every network, model and Colab session. This code uses preflight checks, validation, explicit fallbacks and stage-specific reports. A successful FFmpeg animation does not mean neural image-to-video succeeded. TikTok metrics are not invented when Creative Center access is blocked. A model/API stage that is not installed or compatible fails with a useful report instead of a fake output. Model licenses and commercial rights must be reviewed separately; see `LICENSES.md`.
