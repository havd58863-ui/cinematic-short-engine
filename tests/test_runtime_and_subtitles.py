from generation.image_generation import environment_report
from generation.subtitles import _group_words, _srt_timestamp

def test_environment_report_has_expected_fields():
    report = environment_report()
    assert "cuda_available" in report and "ffmpeg" in report and "free_disk_gb" in report

def test_word_groups_are_timed_and_readable():
    words = [
        {"word":" Hello", "start":0.0,"end":0.3},
        {"word":" there", "start":0.31,"end":0.55},
        {"word":" friend.", "start":0.56,"end":0.9},
    ]
    phrases = _group_words(words, max_words=5)
    assert len(phrases) == 1
    assert phrases[0]["start"] == 0.0 and phrases[0]["end"] == 0.9
    assert "Hello there friend." == phrases[0]["text"]

def test_srt_timestamp_format():
    assert _srt_timestamp(3661.25) == "01:01:01,250"


def test_storyboard_character_reference_flag_defaults_off_and_can_be_enabled():
    from director.storyboard import Storyboard, Shot
    base = Shot(shot_id="s1", sequence_number=1, start_seconds=0, end_seconds=1, narration="line", purpose="purpose", visual_prompt="Detailed specific cinematic subject in a room", negative_prompt="blurry, text")
    default_board = Storyboard(title="test", shots=[base])
    assert default_board.character_reference_required is False
    reference_board = Storyboard(title="test", shots=[base], character_reference_required=True)
    assert reference_board.character_reference_required is True

def test_video_capability_wan_requires_high_vram_and_cache_space(monkeypatch, tmp_path):
    import types, sys
    try:
        import torch
    except ImportError:
        torch = types.ModuleType("torch")
        torch.cuda = types.SimpleNamespace(is_available=lambda: True, get_device_properties=lambda idx: types.SimpleNamespace(total_memory=60 * 1024**3, name="Large Test GPU"))
        monkeypatch.setitem(sys.modules, "torch", torch)
    else:
        props = types.SimpleNamespace(total_memory=60 * 1024**3, name="Large Test GPU")
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(torch.cuda, "get_device_properties", lambda index: props)

    import generation.image_to_video as i2v
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.setattr(i2v.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=120 * 1024**3, total=150 * 1024**3, used=30 * 1024**3))
    result = i2v.video_capabilities()
    assert result["method"] == "wan_i2v"
    assert result["selected_model"] == "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers"

def test_video_capability_skips_wan_when_cache_space_is_insufficient(monkeypatch, tmp_path):
    import types, sys
    try:
        import torch
    except ImportError:
        torch = types.ModuleType("torch")
        torch.cuda = types.SimpleNamespace(is_available=lambda: True, get_device_properties=lambda idx: types.SimpleNamespace(total_memory=60 * 1024**3, name="Large Test GPU"))
        monkeypatch.setitem(sys.modules, "torch", torch)
    else:
        props = types.SimpleNamespace(total_memory=60 * 1024**3, name="Large Test GPU")
        monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
        monkeypatch.setattr(torch.cuda, "get_device_properties", lambda index: props)

    import generation.image_to_video as i2v
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    monkeypatch.setattr(i2v.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=20 * 1024**3, total=150 * 1024**3, used=130 * 1024**3))
    result = i2v.video_capabilities()
    assert result["method"] == "svd_xt"
    assert result["selected_model"] == "stabilityai/stable-video-diffusion-img2vid-xt"


def test_approved_script_correction_preserves_word_timestamps():
    from generation.subtitles import _correct_timed_words_from_script, _group_words
    words = [
        {"word": " Heloo", "start": 0.0, "end": 0.3},
        {"word": " world", "start": 0.31, "end": 0.7},
    ]
    fixed, count = _correct_timed_words_from_script(words, "Hello world.")
    assert count == 2
    assert fixed[0]["start"] == 0.0 and fixed[0]["end"] == 0.3
    assert _group_words(fixed)[0]["text"] == "Hello world."

def test_kokoro_paragraph_cache_does_not_require_model_import(tmp_path, monkeypatch):
    import hashlib, json, sys, wave
    import generation.voice_generation as vg
    paragraph = "This audio is already rendered."
    output = tmp_path / "narration_001.wav"
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(b"\x00\x00" * 12000)
    digest = hashlib.sha256(json.dumps({"text": paragraph, "voice": "af_heart", "language": "a", "speed": 1.0, "model": "Kokoro-82M"}, sort_keys=True).encode()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(digest + "\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "kokoro", None)
    monkeypatch.setattr(vg, "_valid_cached_wav", lambda path: True)
    result = vg.generate_kokoro_paragraphs([paragraph], tmp_path, voice="af_heart", language_code="a", speed=1.0)
    assert result["cached_segments"] == 1 and result["generated_segments"] == 0

def test_subtitle_cache_does_not_require_whisper_import(tmp_path, monkeypatch):
    import hashlib, json, sys
    from generation.subtitles import transcribe_to_subtitles
    audio = tmp_path / "narration.wav"; audio.write_bytes(b"audio-test-bytes" * 300)
    srt = tmp_path / "captions.srt"; srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello world.\n", encoding="utf-8")
    ass = tmp_path / "captions.ass"; ass.write_text("[Script Info]\nPlayResX: 1080\nPlayResY: 1920\n" + "X" * 100, encoding="utf-8")
    transcript = srt.with_suffix(".transcript.json")
    transcript.write_text(json.dumps({"text":"Hello world.", "subtitle_phrases":[{"start":0, "end":1, "text":"Hello world."}], "script_corrections":0}), encoding="utf-8")
    approved = "Hello world."
    cache_key = {"audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(), "model": "base.en", "approved_script_sha256": hashlib.sha256(approved.encode("utf-8")).hexdigest()}
    srt.with_suffix(srt.suffix + ".cache.json").write_text(json.dumps(cache_key), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "whisper", None)
    result = transcribe_to_subtitles(audio, srt, ass_path=ass, model_name="base.en", approved_script=approved)
    assert result["cached"] is True and result["phrase_count"] == 1
