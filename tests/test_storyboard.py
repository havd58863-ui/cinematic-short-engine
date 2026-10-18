import pytest
from director.storyboard import Storyboard, Shot

def shot(sid, start, end, seq):
    return Shot(shot_id=sid, sequence_number=seq, start_seconds=start, end_seconds=end, narration="line", purpose="advance story", visual_prompt="A specific cinematic image of the event", negative_prompt="blurry, malformed anatomy", subtitle_text="line")

def test_storyboard_valid_timeline():
    board = Storyboard(title="test", shots=[shot("s1", 0, 2, 1), shot("s2", 2, 4, 2)])
    board.validate_timeline()

def test_storyboard_rejects_overlap():
    board = Storyboard(title="test", shots=[shot("s1", 0, 3, 1), shot("s2", 2, 4, 2)])
    with pytest.raises(ValueError): board.validate_timeline()

def test_storyboard_rejects_duplicate_ids():
    board = Storyboard(title="test", shots=[shot("s1", 0, 2, 1), shot("s1", 2, 4, 2)])
    with pytest.raises(ValueError): board.validate_timeline()

def test_storyboard_rejects_timeline_gap():
    board = Storyboard(title="test", shots=[shot("s1", 0, 2, 1), shot("s2", 3, 4, 2)])
    with pytest.raises(ValueError): board.validate_timeline()

def test_create_storyboard_offline_fallback():
    from director.storyboard import create_storyboard
    script = "This is a test hook sentence.\n\nHere is some context and escalation.\n\nThis is the payoff."
    board = create_storyboard(script, title="Offline Test Topic", seconds=30)
    assert isinstance(board, Storyboard)
    assert board.title == "Offline Test Topic"
    assert len(board.shots) > 0
    board.validate_timeline()

def test_sanitize_storyboard_data_coercion():
    from director.storyboard import sanitize_storyboard_data, Storyboard
    malformed_data = {
        "title": "Malformed Test",
        "target_duration_seconds": "30",
        "shots": [
            {
                "shot_id": "shot_01",
                "sequence_number": "1",
                "start_seconds": "0.0",
                "end_seconds": "15.0",
                "narration": "First sentence narration.",
                "purpose": "hook",
                "visual_prompt": "Cinematic visual prompt for shot 1",
                "reference_assets": "asset_a.png, asset_b.png",
                "sound_cues": "whoosh, ticking clock",
                "image_settings": "768x1344",  # String instead of dict
                "video_settings": None,  # Null instead of dict
            },
            {
                "shot_id": "shot_02",
                "sequence_number": "2",
                "start_seconds": "10.0",  # Overlaps with shot 1
                "end_seconds": "30.0",
                "narration": "Second sentence narration.",
                "purpose": "payoff",
                "visual_prompt": "Cinematic visual prompt for shot 2",
                "reference_assets": None,
                "sound_cues": ["subtle drone"],
                "image_settings": {"width": 768, "height": 1344, "steps": 20},
                "video_settings": {"frames": 25, "fps": 7},
            }
        ]
    }
    sanitized = sanitize_storyboard_data(malformed_data, "script text", "Malformed Test", 30)

    # Check types coerced properly
    s1 = sanitized["shots"][0]
    assert isinstance(s1["reference_assets"], list)
    assert s1["reference_assets"] == ["asset_a.png", "asset_b.png"]
    assert isinstance(s1["sound_cues"], list)
    assert s1["sound_cues"] == ["whoosh", "ticking clock"]
    assert isinstance(s1["image_settings"], dict)
    assert isinstance(s1["video_settings"], dict)

    # Verify Pydantic validation passes without error
    board = Storyboard.model_validate(sanitized)
    board.validate_timeline()

def test_write_script_offline_fallback():
    from director.scriptwriter_adapter import write_script
    sources = [{"title": "Test Source", "snippet": "Research confirms significant findings."}]
    script = write_script("Offline Script Test", sources, seconds=30)
    assert isinstance(script, str)
    assert len(script) > 20
    assert "Offline Script Test" in script

def test_pipeline_planning_job_offline(tmp_path):
    from src.tiktok_director.pipeline import run_planning_job
    from tiktok_director.config import Settings

    settings = Settings(
        output_root=tmp_path / "outputs",
        model_cache_root=tmp_path / "cache",
        target_region="US",
        video_seconds=30
    )

    job_dir = run_planning_job(topic="AI Video Pipeline Test", settings=settings)
    assert job_dir.exists()
    assert (job_dir / "script" / "approved_script.txt").exists()
    assert (job_dir / "storyboard" / "storyboard.json").exists()
    assert (job_dir / "run_manifest.json").exists()
