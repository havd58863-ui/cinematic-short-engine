from __future__ import annotations
from pathlib import Path
import json, os
from pydantic import BaseModel, Field, field_validator

class Settings(BaseModel):
    target_region: str = "us-en"
    target_language: str = "English"
    target_audience: str = "US TikTok viewers"
    video_seconds: int = Field(default=45, ge=10, le=180)
    fps: int = Field(default=30, ge=24, le=60)
    width: int = Field(default=1080, ge=360, le=2160)
    height: int = Field(default=1920, ge=640, le=3840)
    image_model: str = "stabilityai/stable-diffusion-xl-base-1.0"
    image_fallback_model: str | None = "runwayml/stable-diffusion-v1-5"
    video_model: str = "auto"
    enable_real_image_to_video: bool = True
    max_neural_video_shots: int = 0  # 0 = all shots eligible; loaded pipeline is reused for the job
    tts_voice: str = "af_heart"
    tts_language_code: str = "a"
    tts_speed: float = Field(default=1.0, ge=0.5, le=1.5)
    whisper_model: str = "base.en"
    ollama_model: str = "qwen2.5:3b-instruct"
    output_root: Path = Path("jobs")
    model_cache_root: Path = Path("model_cache")
    research_max_results: int = Field(default=6, ge=1, le=20)
    extract_top_sources: int = Field(default=3, ge=0, le=8)
    use_ip_adapter: bool = True
    music_file: Path | None = None
    music_volume: float = Field(default=0.14, ge=0, le=0.4)
    run_black_silence_checks: bool = True

    @field_validator("output_root", "model_cache_root", mode="before")
    @classmethod
    def path_from_string(cls, value):
        return Path(value) if value else value

    @field_validator("music_file", mode="before")
    @classmethod
    def optional_path(cls, value):
        return Path(value) if value else None

    @classmethod
    def from_json(cls, path: str | Path) -> "Settings":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            target_region=os.getenv("RESEARCH_REGION", "us-en"),
            video_seconds=int(os.getenv("DEFAULT_VIDEO_SECONDS", "45")),
            enable_real_image_to_video=os.getenv("ENABLE_REAL_IMAGE_TO_VIDEO", "true").lower() == "true",
            ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct"),
            output_root=Path(os.getenv("TIKTOK_OUTPUT_ROOT", "jobs")),
            model_cache_root=Path(os.getenv("TIKTOK_MODEL_CACHE", "model_cache")),
            tts_voice=os.getenv("KOKORO_VOICE", "af_heart"),
            whisper_model=os.getenv("WHISPER_MODEL", "base.en"),
            use_ip_adapter=os.getenv("ENABLE_IP_ADAPTER", "true").lower() == "true",
        )
