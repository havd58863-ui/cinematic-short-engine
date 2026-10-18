"""LLM-generated structured shot plans with strict timing validation."""
from __future__ import annotations
import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from .scriptwriter_adapter import generate_structured_json, ScriptwriterUnavailable

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


def build_programmatic_storyboard(script: str, title: str, seconds: int = 45) -> Storyboard:
    """Construct a deterministic, fully schema-compliant Storyboard when LLMs are offline or fail validation."""
    clean_title = (title or "TikTok Short").strip()
    target_duration = max(5.0, float(seconds))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\s+", script) if p.strip()]
    if not paragraphs:
        paragraphs = [f"Discovering the truth about {clean_title}."]

    num_shots = len(paragraphs)
    shot_duration = target_duration / num_shots

    shot_sizes = ["medium shot", "close-up", "medium close-up", "wide shot"]
    camera_angles = ["eye level", "low angle", "eye level", "high angle"]
    camera_movements = ["slow push-in", "static", "pan right", "subtle zoom"]

    shots: list[Shot] = []
    for i, p_text in enumerate(paragraphs):
        start = round(i * shot_duration, 2)
        end = round(target_duration if i == num_shots - 1 else (i + 1) * shot_duration, 2)
        if end <= start:
            end = round(start + 1.0, 2)

        purpose = "Hook viewer with narrative premise" if i == 0 else ("Deliver resolution and payoff" if i == num_shots - 1 else "Escalate story context")
        v_prompt = f"High detail cinematic 9:16 vertical shot depicting {clean_title}. {p_text[:120]}. Professional cinematic lighting, detailed background, 8k resolution."

        sound = ["subtle cinematic atmosphere"] if i == 0 else ["whoosh transition"]

        shot_obj = Shot(
            shot_id=f"shot_{i+1:02d}",
            sequence_number=i + 1,
            start_seconds=start,
            end_seconds=end,
            narration=p_text,
            purpose=purpose,
            visual_prompt=v_prompt,
            negative_prompt="blurry, low quality, distorted anatomy, text, watermark, bad lighting",
            shot_size=shot_sizes[i % len(shot_sizes)],
            camera_angle=camera_angles[i % len(camera_angles)],
            camera_movement=camera_movements[i % len(camera_movements)],
            reference_assets=[],
            sound_cues=sound,
            subtitle_text=p_text,
            subtitle_start_seconds=start,
            subtitle_end_seconds=end,
            image_settings={"width": 768, "height": 1344, "steps": 25},
            video_settings={"frames": 25, "fps": 7},
        )
        shots.append(shot_obj)

    board = Storyboard(
        title=clean_title,
        target_audience="US TikTok viewers",
        aspect_ratio="9:16",
        target_duration_seconds=target_duration,
        visual_identity=f"A cohesive, grounded cinematic visual style with rich contrast and realistic texture suited for {clean_title}.",
        character_reference_required=False,
        shots=shots,
    )
    board.validate_timeline()
    return board


def sanitize_storyboard_data(data: dict[str, Any], script: str, title: str, seconds: int = 45) -> dict[str, Any]:
    """Sanitize raw JSON input to guarantee compliance with Shot/Storyboard Pydantic schemas."""
    if not isinstance(data, dict):
        return build_programmatic_storyboard(script, title, seconds).model_dump()

    clean_title = str(data.get("title") or title or "Untitled Short").strip()
    target_dur = float(seconds)
    try:
        if data.get("target_duration_seconds"):
            target_dur = float(data["target_duration_seconds"])
    except (ValueError, TypeError):
        pass
    target_dur = max(5.0, target_dur)

    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        return build_programmatic_storyboard(script, title, seconds).model_dump()

    sanitized_shots: list[dict[str, Any]] = []

    for i, raw_s in enumerate(raw_shots, start=1):
        if not isinstance(raw_s, dict):
            raw_s = {}

        # 1. Guarantee reference_assets is list[str]
        ref_assets = raw_s.get("reference_assets")
        if isinstance(ref_assets, str):
            ref_list = [s.strip() for s in ref_assets.split(",") if s.strip() and s.strip().lower() not in ("none", "null", "[]")]
        elif isinstance(ref_assets, list):
            ref_list = [str(x) for x in ref_assets if str(x).strip() and str(x).strip().lower() not in ("none", "null")]
        else:
            ref_list = []

        # 2. Guarantee sound_cues is list[str]
        sound_cues_raw = raw_s.get("sound_cues")
        if isinstance(sound_cues_raw, str):
            sound_list = [s.strip() for s in sound_cues_raw.replace(";", ",").split(",") if s.strip() and s.strip().lower() not in ("none", "null", "silence", "intentional silence", "[]")]
        elif isinstance(sound_cues_raw, list):
            sound_list = [str(x) for x in sound_cues_raw if str(x).strip() and str(x).strip().lower() not in ("none", "null", "silence", "intentional silence")]
        else:
            sound_list = []

        # 3. Guarantee image_settings is dict
        img_settings = raw_s.get("image_settings")
        if not isinstance(img_settings, dict):
            img_settings = {"width": 768, "height": 1344, "steps": 25}
        else:
            img_settings = {
                "width": int(img_settings.get("width") or 768),
                "height": int(img_settings.get("height") or 1344),
                "steps": int(img_settings.get("steps") or 25),
            }

        # 4. Guarantee video_settings is dict
        vid_settings = raw_s.get("video_settings")
        if not isinstance(vid_settings, dict):
            vid_settings = {"frames": 25, "fps": 7}
        else:
            vid_settings = {
                "frames": int(vid_settings.get("frames") or 25),
                "fps": int(vid_settings.get("fps") or 7),
            }

        narration = str(raw_s.get("narration") or "").strip()
        if not narration:
            narration = clean_title

        purpose = str(raw_s.get("purpose") or "").strip()
        if not purpose:
            purpose = "advance story"

        v_prompt = str(raw_s.get("visual_prompt") or "").strip()
        if len(v_prompt) < 12:
            v_prompt = f"Detailed cinematic 9:16 vertical shot depicting {clean_title}. High detail realism."

        neg_prompt = str(raw_s.get("negative_prompt") or "").strip()
        if not neg_prompt:
            neg_prompt = "blurry, low quality, distorted anatomy, text, watermark"

        # Coerce timings
        try:
            start_sec = float(raw_s.get("start_seconds", 0.0))
        except (ValueError, TypeError):
            start_sec = 0.0

        try:
            end_sec = float(raw_s.get("end_seconds", 0.0))
        except (ValueError, TypeError):
            end_sec = 0.0

        sub_text = str(raw_s.get("subtitle_text") or narration)

        s_dict: dict[str, Any] = {
            "shot_id": str(raw_s.get("shot_id") or f"shot_{i:02d}"),
            "sequence_number": i,
            "start_seconds": start_sec,
            "end_seconds": end_sec,
            "narration": narration,
            "purpose": purpose,
            "visual_prompt": v_prompt,
            "negative_prompt": neg_prompt,
            "shot_size": str(raw_s.get("shot_size") or "medium close-up"),
            "camera_angle": str(raw_s.get("camera_angle") or "eye level"),
            "camera_movement": str(raw_s.get("camera_movement") or "slow push-in"),
            "subject_movement": str(raw_s.get("subject_movement") or "subtle natural movement"),
            "environmental_movement": str(raw_s.get("environmental_movement") or "subtle atmospheric motion"),
            "composition": str(raw_s.get("composition") or "vertical 9:16; keep subject central"),
            "lighting": str(raw_s.get("lighting") or "motivated cinematic lighting"),
            "palette": str(raw_s.get("palette") or "consistent restrained color palette"),
            "atmosphere": str(raw_s.get("atmosphere") or "cinematic, grounded"),
            "depth_of_field": str(raw_s.get("depth_of_field") or "shallow when it supports story clarity"),
            "reference_assets": ref_list,
            "continuity_notes": str(raw_s.get("continuity_notes") or "Maintain subject identity."),
            "sound_cues": sound_list,
            "transition": str(raw_s.get("transition") or "cut on action"),
            "subtitle_text": sub_text,
            "subtitle_start_seconds": start_sec,
            "subtitle_end_seconds": end_sec,
            "image_model": str(raw_s.get("image_model") or "stabilityai/stable-diffusion-xl-base-1.0"),
            "image_settings": img_settings,
            "video_model": str(raw_s.get("video_model") or "auto"),
            "video_settings": vid_settings,
        }
        sanitized_shots.append(s_dict)

    # Re-align timings to ensure strictly contiguous 0..target_dur timeline without gaps or overlaps
    num_s = len(sanitized_shots)
    shot_dur = target_dur / num_s
    for idx, s in enumerate(sanitized_shots):
        calc_start = round(idx * shot_dur, 2)
        calc_end = round(target_dur if idx == num_s - 1 else (idx + 1) * shot_dur, 2)
        if calc_end <= calc_start:
            calc_end = round(calc_start + 1.0, 2)

        # Use LLM timings if valid and contiguous, else use calc_start/calc_end
        if idx == 0:
            s["start_seconds"] = 0.0
            s["end_seconds"] = s["end_seconds"] if s["end_seconds"] > 0.5 else calc_end
        else:
            prev_end = sanitized_shots[idx - 1]["end_seconds"]
            s["start_seconds"] = prev_end
            if s["end_seconds"] <= prev_end:
                s["end_seconds"] = round(prev_end + max(1.0, shot_dur), 2)

        s["subtitle_start_seconds"] = s["start_seconds"]
        s["subtitle_end_seconds"] = s["end_seconds"]

    # Final shot end time should match target_dur
    if sanitized_shots:
        sanitized_shots[-1]["end_seconds"] = target_dur
        sanitized_shots[-1]["subtitle_end_seconds"] = target_dur

    return {
        "title": clean_title,
        "target_audience": str(data.get("target_audience") or "US TikTok viewers"),
        "aspect_ratio": "9:16",
        "target_duration_seconds": target_dur,
        "visual_identity": str(data.get("visual_identity") or f"Cinematic style for {clean_title}"),
        "character_reference_required": bool(data.get("character_reference_required", False)),
        "shots": sanitized_shots,
    }


def create_storyboard(script: str, title: str, seconds: int = 45, model: str | None = None) -> Storyboard:
    prompt = f"""Act as a film director and storyboard artist for a coherent vertical TikTok short.
Create a valid JSON object only, no Markdown, with root keys: title,target_audience,aspect_ratio,target_duration_seconds,visual_identity,character_reference_required,shots. `visual_identity` must describe the consistent overall look. Set `character_reference_required` to true only when a recurring main character/recognizable subject appears in multiple shots; otherwise false.
Target total runtime: {seconds} seconds, US audience, aspect ratio 9:16. Plan 8-14 connected shots as the story length requires (not arbitrary repeats). Distribute the full timeline continuously from 0 to about {seconds} seconds. Every shot has a unique id and sequential sequence_number.
Each shot MUST include: shot_id,sequence_number,start_seconds,end_seconds,narration,purpose,visual_prompt,negative_prompt,shot_size,camera_angle,camera_movement,subject_movement,environmental_movement,composition,lighting,palette,atmosphere,depth_of_field,reference_assets,continuity_notes,sound_cues,transition,subtitle_text,subtitle_start_seconds,subtitle_end_seconds,image_model,image_settings,video_model,video_settings.
Visual direction requirements: write specific shot prompts that depict the actual event described in the corresponding narration; vary shot size and angle deliberately; maintain visual identity, geography, subject appearance, props, screen direction and light direction; no generic repeated images; specify action and temporal progression; avoid placing important text near TikTok UI zones. Negative prompts should name likely visual defects. Every shot must have clear function in the narrative. Provide 1-2 concise sound_cues per shot when useful (for example whoosh transition, low impact, subtle ticking, ambient drone, radio static, alarm beep, wind); use an explicit "none" only when silence is intentional. Use start and end times in seconds, no overlaps or timeline gaps. The narration segments together must cover the supplied script in order without omissions or additions. Set image_settings to a practical portrait size around 768x1344 and 20-30 steps; video_settings frames=25 fps=7 unless another supported choice is clearly warranted. Set generation paths/status fields only if known; otherwise omit them.
TITLE: {title}
SCRIPT:
{script}"""
    try:
        data = generate_structured_json(prompt, model=model)
    except ScriptwriterUnavailable:
        return build_programmatic_storyboard(script, title, seconds)
    except Exception:
        return build_programmatic_storyboard(script, title, seconds)

    try:
        sanitized_data = sanitize_storyboard_data(data, script, title, seconds)
        board = Storyboard.model_validate(sanitized_data)
        board.validate_timeline()
        board.aspect_ratio = "9:16"
        return board
    except (ValidationError, ValueError, Exception):
        return build_programmatic_storyboard(script, title, seconds)
