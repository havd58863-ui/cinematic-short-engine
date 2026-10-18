# Architecture Audit: Two-Account TikTok Cinematic Production Engine

**Repository:** `havd58863-ui/cinematic-short-engine`
**Governing Master Reference:** `MASTER_DNA_TIKTOK_TWO_ACCOUNTS_v1.0.pdf` (Version 1.0)
*Note on Governing Master Reference:* The PDF `MASTER_DNA_TIKTOK_TWO_ACCOUNTS_v1.0.pdf` is identified as a critical source file that is currently **missing from the repository root** and must be uploaded/added by the repository owner. This architecture audit incorporates all explicit requirements from the version 1.0 specification into the codebase configuration and architecture.

---

## 1. Factual Repository Inventory and Status Analysis

| Path / Module | Purpose | Current Implementation Status | Broken / Missing Components & Notes |
|---|---|---|---|
| `MASTER_DNA_TIKTOK_TWO_ACCOUNTS_v1.0.pdf` | Master reference document | **MISSING** | Identified as required source document; explicitly noted as missing from repository. |
| `config/project_settings.json` | Default pipeline settings | Functional (Single account) | Needs update to support account-specific profiles and output directories. |
| `config/accounts/` | Account DNA profiles | **MISSING** | Must be created (`account_01_psychology.json`, `account_02_storytelling.json`). |
| `research/engine.py` | Research orchestrator | Partial | Standard web research present; lacks multi-source aggregator and DNA gating. |
| `research/trend_finder.py` | Trend discovery & DDGS search | Functional | Uses DDGS public web search. TikTok Creative Center lacks official API credentials. |
| `research/idea_scoring.py` | Evidence-based scoring engine | Partial | Has basic weighting but missing mandatory DNA Gate and saturation penalty. |
| `research/source_registry.py` | Source provenance & dedup | Functional | Normalizes URLs, timestamps, and collection status. |
| `research/competitor_analysis.py` | Analysis of indexed content | Functional | Extracts publicly indexed page metadata without inventing view metrics. |
| `director/scriptwriter_adapter.py` | LLM scripting adapter | Functional (Ollama/CLI/OpenAI) | Needs OmniRoute (`https://omniroute.online/`) gateway support. |
| `director/script_analysis.py` | Pacing & structure analysis | Functional | Needs stage validation for Account 01 (5 stages) and Account 02 (7 stages, 75–120s). |
| `director/storyboard.py` | Pydantic v2 Shot list | Functional | Enforces timed shot schema, camera angles, and character continuity flags. |
| `director/continuity_manager.py` | Subject/world continuity | Functional | Validates visual prompts against Character/World Bibles. |
| `director/quality_control.py` | Storyboard QA | Functional | Checks duration, prompt details, and caption alignment. |
| `generation/image_generation.py` | SDXL / SD 1.5 T2I | Functional (Diffusers) | Requires GPU. Fallback to Pixabay/Pexels stock images when API keys present. |
| `generation/image_to_video.py` | Wan 2.1 / SVD-XT I2V | Functional (Diffusers) | Requires GPU + high VRAM (>=48GB for Wan 2.1, >=12GB for SVD-XT). FFmpeg fallback (`ffmpeg_animation`) supported. |
| `generation/voice_generation.py` | Kokoro-82M TTS | Functional | Uses `af_heart` voice. Unit tests need graceful handling when `soundfile` is missing on CPU sandbox. |
| `generation/subtitles.py` | Whisper SRT/ASS generation | Functional | Transcribes rendered narration, aligns word timings, burns ASS captions. |
| `editing/render_video.py` | FFmpeg video assembler | Functional | Assembles 1080x1920 MP4 at 30fps with audio mix and subtitle burn-in. |
| `editing/audio_mixer.py` | Audio mixing & normalization | Functional | Concatenates narration WAVs, normalizes loudness, mixes background music/procedural SFX. |
| `editing/kinocut_adapter.py` | Kinocut QC integration | Functional (Optional) | Second-line metric check; gracefully skips if `kinocut` is uninstalled. |
| `src/tiktok_director/pipeline.py` | Main execution pipeline | Functional | Manages stage manifests, caching, and resumption. Needs account profile integration. |
| `notebook/run_pipeline.ipynb` | Colab execution launcher | Functional | One-click manual Colab notebook. Needs account dropdown and Drive pathing update. |

---

## 2. Dependency Conflict and Runtime Analysis

### CPU Sandbox (Jules) vs. GPU Runtime (Google Colab)
1. **PyTorch & CUDA:**
   - On local CPU / Sandbox: PyTorch may not be installed or may be CPU-only. Modules like `generation/image_to_video.py` and `generation/image_generation.py` perform runtime checks (`torch.cuda.is_available()`). Tests must mock `torch` or handle `ModuleNotFoundError` gracefully.
2. **Audio Libraries (`soundfile`, `kokoro`):**
   - `generation/voice_generation.py` requires `soundfile` for WAV header validation. In CPU test environments without C libraries (`libsndfile`), `import soundfile` fails. The codebase must handle missing `soundfile` during offline test suite runs without crashing non-audio tests.
3. **Diffusers & Model Cache Storage:**
   - Wan 2.1 I2V requires >=100 GB free disk space for model weights. Preflight checks in `generation/image_to_video.py` check disk space via `shutil.disk_usage()`.
4. **Pydantic v2:**
   - `pyproject.toml` pins `pydantic>=2.7,<3`. All schemas use Pydantic v2 `BaseModel` and `ConfigDict`.
5. **Kinocut:**
   - `kinocut==1.16.1` is an optional dependency in `pyproject.toml` (`[project.optional-dependencies] kinocut`). It is executed via subprocess CLI (`kino doctor`, `kino metric-qc`) and failure to import/run does not break rendering.

---

## 3. Evaluation of 10 Research Candidate Tools

| Candidate Tool | Repository URL / Source | License | API / Credentials Required | Colab Compatibility | Chosen Integration Method & Technical Evaluation |
|---|---|---|---|---|---|
| **1. Trend Pulse** | `https://github.com/claude-world/trend-pulse` *(Verified)* | MIT / Apache-2.0 | None (Public web scraping / RSS) | High | **Adapted methodology.** Search patterns and topic signals are integrated into `research/trend_finder.py`. No direct dependency required. |
| **2. Trendspyg** | `https://github.com/flack0x/trendspyg` | MIT | None (Scrapes Google Trends / related queries) | High | **Optional signal adapter.** Integrated into `research/trend_finder.py` via `pytrends` fallback for Google Trends search interest signals. |
| **3. YouTube Topic Insights** | `https://github.com/google-marketing-solutions/youtube-topic-insights` | Apache-2.0 | YouTube Data API Key (Optional) | High | **Optional adjacent-topic research.** Used only when `YOUTUBE_API_KEY` is provided in Colab Secrets to discover adjacent interest topics. |
| **4. Reddit AI Trends** | `https://github.com/liydanpdx/reddit-ai-trends` | MIT | Reddit API credentials (Optional) | High | **Simpler public Reddit JSON adapter chosen.** Direct public RSS/JSON fetching (`https://www.reddit.com/r/{subreddit}/hot.json`) without mandatory API keys. |
| **5. Last30Days Skill** | `https://github.com/mvanhorn/last30days-skill` | MIT | Multi-search APIs | High | **Research methodology adapted.** Rolling 30-day window research query generator in `research/trend_finder.py` instead of installing heavy external skill runner. |
| **6. Content Skills** | `https://github.com/vyralcontent/content-skills` | MIT | None | High | **Scriptwriting methodology imported.** Prompts and pacing rules for "viral-short-form" and "viral-tiktok-content" incorporated into LLM prompt templates. |
| **7. TikTok Viral Hooks** | `https://github.com/shixinzhang/tiktok-viral-hooks` | Code: MIT / Content: CC BY-NC-SA | None | High | **Code pattern adapted; content excluded.** Structural hook patterns implemented in code. CC BY-NC-SA corpus content is NOT imported into commercial production. |
| **8. TikTok Creative Center** | `https://ads.tiktok.com/creative/creativeCenter/trends` | First-Party Service | Web session / Official portal | High | **First-party primary source.** Checked via HTTP status; where restricted, fallback to public web search without inventing metrics. |
| **9. TikTok API (David Teather)** | `https://github.com/davidteather/TikTok-Api` | MIT | `ms_token`, Playwright / session cookies | Low / Fragile | **Optional fragile adapter.** Treated as non-critical. Never stored `ms_token` in git. Pipeline never depends on it for execution. |
| **10. ViralMint** | `https://github.com/openclaw-easy/ViralMint` | Unverified / Missing | Unknown | N/A | **Unverified repo.** Reported as unverified; candidate concepts incorporated via standard scoring and script analysis rules. |

---

## 4. Modular Pipeline Architecture and Sequence

```
+-----------------------------------------------------------------------------------+
|                               USER INTERFACE                                      |
|            Google Colab Notebook / CLI / Optional Orchestrator (n8n)               |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              ACCOUNT PROFILE ENGINE                               |
|   Select: Account 01 (Cinematic Psychology) or Account 02 (Cinematic Storytelling)  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              RESEARCH & EVIDENCE AGGREGATOR                        |
|   DDGS Web Search + TikTok Creative Center + Reddit Adapter + Google Trends       |
|   Preserves URL, Timestamp, Query Region, Collection Status & Metric Notes            |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              MANDATORY DNA GATE & SCORING                         |
|   Filter ideas against Account DNA -> Score Recency, Curiosity, Saturation, Payoff |
|   Log rejected candidates with reasons in `rejected_ideas.json`                  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              LLM SCRIPTWRITER ADAPTER                              |
|   Routes to: OmniRoute Gateway / Ollama / OpenAI API / Custom CLI                 |
|   Enforces Script Structure:                                                      |
|   - Account 01: Hook -> Curiosity -> Psych Mechanism -> Realization -> Final Line |
|   - Account 02: Cold Open -> Question -> Journey -> Discovery -> Turn -> Payoff    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                             STORYBOARD & CONTINUITY ENGINE                        |
|   Pydantic v2 Shot List (Shot sizes, Camera angles, Visual prompts, Safe areas)   |
|   Account 02 Character/World Bible continuity check                              |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                             GENERATION ENGINE (Colab GPU)                         |
|   - Voice: Kokoro-82M TTS (`af_heart` English male voice)                         |
|   - Images: Diffusers SDXL (1080x1920) + IP-Adapter reference                     |
|   - Video: Wan 2.1 I2V / SVD-XT / FFmpeg pan-zoom fallback (`ffmpeg_animation`)   |
|   - Captions: Whisper SRT/ASS word-level alignment                                |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                              EDITING & RENDERING (FFmpeg)                         |
|   1080x1920 30fps MP4, Audio Mix, Loudness Normalization, Subtitle Burn-In, QA    |
+-----------------------------------------------------------------------------------+
```

---

## 5. Proposed Directory Structure and Multi-Account Isolation

```
cinematic-short-engine/
├── ARCHITECTURE_AUDIT.md
├── MASTER_DNA_TIKTOK_TWO_ACCOUNTS_v1.0.pdf (To be added by repo owner)
├── README.md
├── TOOLS_MANIFEST.yaml
├── pyproject.toml
├── requirements.txt
├── requirements-colab.txt
├── config/
│   ├── default_job.json
│   ├── project_settings.json
│   └── accounts/
│       ├── account_01_psychology.json
│       └── account_02_storytelling.json
├── director/
│   ├── __init__.py
│   ├── continuity_manager.py
│   ├── quality_control.py
│   ├── script_analysis.py
│   ├── scriptwriter_adapter.py
│   ├── shot_planner.py
│   └── storyboard.py
├── editing/
│   ├── __init__.py
│   ├── audio_mixer.py
│   ├── kinocut_adapter.py
│   └── render_video.py
├── generation/
│   ├── __init__.py
│   ├── image_generation.py
│   ├── image_to_video.py
│   ├── stock_images.py
│   ├── subtitles.py
│   └── voice_generation.py
├── notebook/
│   ├── bootstrap_repository.ipynb
│   └── run_pipeline.ipynb
├── research/
│   ├── __init__.py
│   ├── competitor_analysis.py
│   ├── engine.py
│   ├── idea_scoring.py
│   ├── source_registry.py
│   └── trend_finder.py
├── schemas/
│   ├── job.schema.json
│   └── storyboard.schema.json
├── src/
│   └── tiktok_director/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── pipeline.py
│       ├── qa.py
│       ├── research.py
│       ├── scriptwriter.py
│       └── storyboard.py
└── tests/
    ├── test_accounts.py
    ├── test_kinocut_and_bootstrap.py
    ├── test_qa.py
    ├── test_render_smoke.py
    ├── test_runtime_and_subtitles.py
    ├── test_scoring.py
    ├── test_script_analysis.py
    ├── test_script_duration.py
    ├── test_source_registry.py
    ├── test_storyboard.py
    └── test_trend_finder.py
```

### Account Output Directory Paths
Outputs are saved into Google Drive / Local Storage under isolated account roots:
- **Account 01:** `Google Drive/TikTokAIDirector/jobs/account_01/{JOB_ID}/`
- **Account 02:** `Google Drive/TikTokAIDirector/jobs/account_02/{JOB_ID}/`

---

## 6. Schemas, Idea Scoring, and Analytics Feedback Loop

### Idea-Record & Evidence Schema (`schemas/idea_record.schema.json`)
```json
{
  "idea_id": "psych_001_20261018",
  "account_id": "account_01_psychology",
  "topic": "The Spotlight Effect in Social Anxiety",
  "dna_gate_passed": true,
  "dna_gate_reason": "Matches psychological self-recognition core promise without medical diagnosing.",
  "evidence": [
    {
      "source_name": "DDGS public web search",
      "url": "https://example.com/spotlight-effect-study",
      "collected_at_utc": "2026-10-18T12:00:00Z",
      "published_at": "2026-10-15",
      "metrics": {},
      "metrics_note": "No unverified TikTok metrics inferred."
    }
  ],
  "scores": {
    "recency_and_quality": 8.5,
    "search_growth": 7.0,
    "audience_relevance": 9.0,
    "hook_strength": 9.2,
    "narrative_payoff": 8.8,
    "visual_feasibility": 8.0,
    "saturation_penalty": -1.0,
    "final_score": 8.41
  },
  "explanation": "High curiosity gap and self-recognition value; moderate search interest.",
  "status": "shortlisted"
}
```

### Evidence-Based Scoring Explanation
Ideas pass through a 2-stage evaluation:
1. **Mandatory DNA Gate:** Boolean check against account rules (e.g. Account 01 fails if medical advice or diagnosing viewers is present; Account 02 fails if non-narrative or under 75s when unsuited). Failed ideas are written to `rejected_ideas.json` with reasons.
2. **Weighted Score Calculation (0 – 10 scale):**
   - Recency & Evidence Quality (20%)
   - Search Interest / Growth (15%)
   - Hook Strength & Curiosity Gap (20%)
   - Retention Progression & Payoff (25%)
   - Visual Feasibility & Generation Cost (20%)
   - Saturation Penalty (Subtracted based on duplicate topics in account history).

*Note:* Scores are internal prioritization metrics, **never labeled as guaranteed viral probabilities**.

### Post-Publication Analytics Feedback Loop
After publishing, post-performance analytics (watch time, 3s retention %, completion rate, share/save count) are recorded in `analytics/post_publication_log.json`.
The feedback engine calculates topic saturation weights and improves hook visual prompt templates without altering either account's core creative DNA.

---

## 7. Execution Matrix: Sandbox vs. Colab vs. Credentials

| Feature / Execution Step | Jules Sandbox (CPU) | Google Colab (T4 / A100 GPU) | Credentials / Secrets Needed |
|---|---|---|---|
| Python unit tests (`pytest`) | **FULL RUN** | Can run | None |
| Code audit & schema validation | **FULL RUN** | Can run | None |
| Research & DDGS web scraping | **FULL RUN** | Can run | None |
| Idea Scoring & DNA Gating | **FULL RUN** | Can run | None |
| Script structure verification | **FULL RUN** | Can run | None |
| OmniRoute LLM provider call | Can call | Can call | `OMNIROUTE_API_KEY` (Colab Secret) |
| Ollama local LLM scriptwriter | If Ollama running | **FULL RUN** | None |
| Voice Generation (Kokoro-82M) | Tests mocked/cached | **FULL RUN** | None |
| Image Generation (SDXL T2I) | CPU fallback (slow) | **FULL RUN (GPU)** | None |
| Video Generation (Wan 2.1 / SVD) | FFmpeg animation fallback | **FULL RUN (GPU >=12GB/48GB)** | None |
| Subtitle Generation (Whisper) | Tests mocked/cached | **FULL RUN** | None |
| FFmpeg Video Render & Mix | **FULL RUN** | **FULL RUN** | None |
| Kinocut Quality Diagnostic | Optional CLI check | Optional CLI check | None |
| Google Drive Storage Sync | Local `./jobs` | **Mounted Drive** | `GITHUB_TOKEN` (for private repo) |
| n8n Scheduling Orchestration | N/A (Later stage) | N/A (Dispatches job) | Webhook URL / n8n env |

---
