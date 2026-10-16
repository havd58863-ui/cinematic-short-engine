"""LLM-generated structured shot plans with strict timing validation."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from .scriptwriter_adapter import generate_structured_json

VideoMethod = Literal["not_generated", "neural_image_to_video", "ffmpeg_animation"]

class Shot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    shot_id: str = Field(min_length=1)
    sequence_number: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    narration: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    visual_prompt: str = Field(min_length=12)
    negative_prompt: str = Field(min_length=1)
    shot_size: str = "medium close-up"
    camera_angle: str = "eye level"
    camera_movement: str = "slow push-in"
    subject_movement: str = "subtle natural movement"
    environmental_movement: str = "subtle atmospheric motion"
    composition: str = "vertical 9:16; keep the subject and essential details inside central safe area"
    lighting: str = "motivated cinematic lighting"
    palette: str = "consistent restrained color palette"
    atmosphere: str = "cinematic, grounded"
    depth_of_field: str = "shallow when it supports story clarity"
    reference_assets: list[str] = Field(default_factory=list)
    continuity_notes: str = "Maintain subject identity, wardrobe, lighting direction, object position, and screen direction."
    sound_cues: list[str] = Field(default_factory=list)
    transition: str = "cut on action"
    subtitle_text: str = ""
    subtitle_start_seconds: float | None = None
    subtitle_end_seconds: float | None = None
    image_model: str = "stabilityai/stable-diffusion-xl-base-1.0"
    image_settings: dict[str, Any] = Field(default_factory=lambda: {"width": 768, "height": 1344, "steps": 25})
    video_model: str = "auto"
    video_settings: dict[str, Any] = Field(default_factory=lambda: {"frames": 25, "fps": 7})
    image_path: str | None = None
    video_path: str | None = None
    video_method: VideoMethod = "not_generated"
    generation_status: str = "pending"
    generation_error: str | None = None

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds

    @model_validator(mode="after")
    def validate_end(self) -> "Shot":
        if self.end_seconds <= self.start_seconds:
            raise ValueError(f"{self.shot_id}: end_seconds must be after start_seconds")
        if self.subtitle_start_seconds is not None and self.subtitle_start_seconds < 0:
            raise ValueError("subtitle_start_seconds cannot be negative")
        if self.subtitle_end_seconds is not None and self.subtitle_start_seconds is not None and self.subtitle_end_seconds < self.subtitle_start_seconds:
            raise ValueError("subtitle end precedes subtitle start")
        return self

class Storyboard(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    target_audience: str = "US TikTok viewers"
    aspect_ratio: str = "9:16"
    target_duration_seconds: float = 45
    visual_identity: str = ""
    character_reference_required: bool = False
    shots: list[Shot]

    def validate_timeline(self, tolerance: float = 0.12) -> None:
        if not self.shots:
            raise ValueError("Storyboard must contain at least one shot.")
        ordered = sorted(self.shots, key=lambda x: x.sequence_number)
        ids: set[str] = set()
        last_end = 0.0
        for index, shot in enumerate(ordered, start=1):
            if shot.shot_id in ids:
                raise ValueError(f"Duplicate shot_id: {shot.shot_id}")
            ids.add(shot.shot_id)
            if shot.sequence_number != index:
                raise ValueError(f"Shot sequence must be contiguous: expected {index}, got {shot.sequence_number}")
            if shot.end_seconds <= shot.start_seconds:
                raise ValueError(f"Invalid timing in {shot.shot_id}")
            if index == 1 and shot.start_seconds > tolerance:
                raise ValueError("The first shot must start at approximately 0 seconds.")
            if shot.start_seconds < last_end - tolerance:
                raise ValueError(f"Overlapping or out-of-order timeline near {shot.shot_id}")
            if index > 1 and shot.start_seconds > last_end + tolerance:
                raise ValueError(f"Timeline gap before {shot.shot_id}: {shot.start_seconds-last_end:.2f}s")
            last_end = shot.end_seconds


def create_storyboard(script: str, title: str, seconds: int = 45, model: str | None = None) -> Storyboard:
    prompt = f"""Act as a film director and storyboard artist for a coherent vertical TikTok short.
Create a valid JSON object only, no Markdown, with root keys: title,target_audience,aspect_ratio,target_duration_seconds,visual_identity,character_reference_required,shots. `visual_identity` must describe the consistent overall look. Set `character_reference_required` to true only when a recurring main character/recognizable subject appears in multiple shots; otherwise false.
Target total runtime: {seconds} seconds, US audience, aspect ratio 9:16. Plan 8-14 connected shots as the story length requires (not arbitrary repeats). Distribute the full timeline continuously from 0 to about {seconds} seconds. Every shot has a unique id and sequential sequence_number.
Each shot MUST include: shot_id,sequence_number,start_seconds,end_seconds,narration,purpose,visual_prompt,negative_prompt,shot_size,camera_angle,camera_movement,subject_movement,environmental_movement,composition,lighting,palette,atmosphere,depth_of_field,reference_assets,continuity_notes,sound_cues,transition,subtitle_text,subtitle_start_seconds,subtitle_end_seconds,image_model,image_settings,video_model,video_settings.
Visual direction requirements: write specific shot prompts that depict the actual event described in the corresponding narration; vary shot size and angle deliberately; maintain visual identity, geography, subject appearance, props, screen direction and light direction; no generic repeated images; specify action and temporal progression; avoid placing important text near TikTok UI zones. Negative prompts should name likely visual defects. Every shot must have clear function in the narrative. Provide 1-2 concise sound_cues per shot when useful (for example whoosh transition, low impact, subtle ticking, ambient drone, radio static, alarm beep, wind); use an explicit "none" only when silence is intentional. Use start and end times in seconds, no overlaps or timeline gaps. The narration segments together must cover the supplied script in order without omissions or additions. Set image_settings to a practical portrait size around 768x1344 and 20-30 steps; video_settings frames=25 fps=7 unless another supported choice is clearly warranted. Set generation paths/status fields only if known; otherwise omit them.
TITLE: {title}
SCRIPT:
{script}"""
    data = generate_structured_json(prompt, model=model)
    try:
        board = Storyboard.model_validate(data)
        board.validate_timeline()
        # Clamp target aspect metadata and ensure specific model defaults exist.
        board.aspect_ratio = "9:16"
        return board
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"Director storyboard failed schema/timeline validation; no synthetic storyboard was substituted: {exc}") from exc
