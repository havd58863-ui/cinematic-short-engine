"""Actual FFmpeg smoke test using a locally generated test pattern, not a mocked renderer."""
from pathlib import Path
import shutil
import pytest

@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg/ffprobe not installed")
def test_ffmpeg_renders_real_vertical_mp4(tmp_path):
    from PIL import Image, ImageDraw
    from editing.render_video import render_video, validate_video
    image_path = tmp_path / "test_frame.png"
    image = Image.new("RGB", (360, 640), "#202b3c")
    draw = ImageDraw.Draw(image)
    draw.ellipse((90, 120, 270, 300), fill="#dca66b")
    draw.rectangle((120, 300, 240, 520), fill="#7488a5")
    image.save(image_path)
    output = tmp_path / "smoke.mp4"
    render_video([(str(image_path), 1.5)], None, output, width=360, height=640, fps=24)
    result = validate_video(output, expected_width=360, expected_height=640, expected_duration=1.5)
    assert output.exists() and output.stat().st_size > 1024
    assert result["video_codec"] == "h264"
    assert result["width"] == 360 and result["height"] == 640
    assert abs(result["duration_seconds"] - 1.5) < 1.0

@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg/ffprobe not installed")
def test_ffmpeg_animation_fallback_to_final_mp4(tmp_path):
    """Exercise real still-image animation, audio muxing, and final stream checks."""
    import subprocess
    from PIL import Image, ImageDraw
    from generation.image_to_video import animate_image_ffmpeg
    from editing.render_video import render_video, validate_video

    image_path = tmp_path / "portrait.png"
    image = Image.new("RGB", (360, 640), "#101820")
    draw = ImageDraw.Draw(image)
    draw.ellipse((100, 100, 260, 260), fill="#f2aa4c")
    draw.rectangle((125, 260, 235, 540), fill="#395b70")
    image.save(image_path)

    clip = tmp_path / "animated.mp4"
    animate_image_ffmpeg(image_path, clip, duration=1.2, width=360, height=640, fps=24, movement="push_in")
    assert clip.exists() and clip.stat().st_size > 1024

    audio = tmp_path / "narration.wav"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2",
        "-ar", "24000", "-ac", "1", str(audio),
    ], check=True, capture_output=True, text=True)
    from types import SimpleNamespace
    from editing.audio_mixer import generate_procedural_sfx_track
    sound_shot = SimpleNamespace(shot_id="shot_001", sequence_number=1, start_seconds=0.0, end_seconds=1.2, duration=1.2, sound_cues=["short whoosh transition", "low impact"] )
    sfx = generate_procedural_sfx_track([sound_shot], 1.2, tmp_path / "sfx")
    assert sfx["status"] == "success" and sfx["track_path"]
    ass = tmp_path / "captions.ass"
    ass.write_text("""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Arial,54,&H00FFFFFF,&H0000FFFF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,4,1,2,90,90,300,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.10,TikTok,,0,0,0,,TEST CAPTION
""", encoding="utf-8")
    final = tmp_path / "final_video.mp4"
    render_video([(str(clip), 1.2)], str(audio), final, subtitles_path=str(ass), sfx_path=sfx["track_path"], width=360, height=640, fps=24)
    report = validate_video(final, expected_width=360, expected_height=640, require_audio=True)
    assert report["video_codec"] == "h264"
    assert report["has_audio"] is True
    assert report["duration_seconds"] > 0.7

@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg/ffprobe not installed")
def test_clip_cache_is_reused_without_regeneration(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    import generation.image_to_video as i2v

    image_path = tmp_path / "shot.png"
    Image.new("RGB", (360, 640), "#223344").save(image_path)
    output_path = tmp_path / "clips" / "shot.mp4"
    shot = SimpleNamespace(
        shot_id="shot_001", sequence_number=1, start_seconds=0.0, end_seconds=1.0,
        duration=1.0, image_path=str(image_path), video_path=str(output_path),
        visual_prompt="A blue room with slowly moving light", camera_movement="slow push-in",
        video_settings={}, generation_status="pending", video_method=None,
    )
    monkeypatch.setattr(i2v, "video_capabilities", lambda: {"cuda_available": False, "gpu_memory_gb": 0.0, "selected_model": None, "method": "ffmpeg_animation", "reason": "CPU test"})
    first = i2v.generate_clips_for_storyboard([shot], try_neural=False, width=360, height=640, fallback_fps=24)
    assert first["clips"]["shot_001"]["method"] == "ffmpeg_animation"

    def must_not_regenerate(*args, **kwargs):
        raise AssertionError("Cached clip should not be regenerated")
    monkeypatch.setattr(i2v, "animate_image_ffmpeg", must_not_regenerate)
    second = i2v.generate_clips_for_storyboard([shot], try_neural=False, width=360, height=640, fallback_fps=24)
    assert second["clips"]["shot_001"]["cached"] is True
