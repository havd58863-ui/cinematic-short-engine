from pathlib import Path
from src.tiktok_director.config import Settings
from research.idea_scoring import evaluate_dna_gate, score_idea
from director.script_analysis import validate_script_structure, analyze_script
from director.scriptwriter_adapter import generate_text

def test_account_profiles_exist_and_load():
    profile_1 = Settings.load_account_profile("account_01_psychology")
    assert profile_1.get("account_id") == "account_01_psychology"
    assert "HOOK" in profile_1.get("script_structure", [])

    profile_2 = Settings.load_account_profile("account_02_storytelling")
    assert profile_2.get("account_id") == "account_02_storytelling"
    assert "COLD OPEN" in profile_2.get("script_structure", [])

def test_account_01_dna_gate():
    profile_1 = Settings.load_account_profile("account_01_psychology")

    # Valid psychological self-discovery topic
    passed, reason = evaluate_dna_gate("The Spotlight Effect in Social Settings", "Why you feel watched.", profile_1)
    assert passed is True

    # Invalid topic diagnosing viewers
    passed, reason = evaluate_dna_gate("How to diagnose your disorder", "Here are symptoms to diagnose yourself", profile_1)
    assert passed is False
    assert "forbidden phrase" in reason

def test_account_02_dna_gate():
    profile_2 = Settings.load_account_profile("account_02_storytelling")

    # Valid storytelling
    passed, reason = evaluate_dna_gate("The Lost Clock of Prague", "A story about time and nostalgia", profile_2)
    assert passed is True

    # Invalid listicle clickbait
    passed, reason = evaluate_dna_gate("Top 5 Life Hacks", "Quick trick to buy this now", profile_2)
    assert passed is False

def test_topic_saturation_penalty():
    catalogue = ["The Spotlight Effect in Social Settings"]
    profile_1 = Settings.load_account_profile("account_01_psychology")

    res = score_idea("The Spotlight Effect in Social Settings", [], account_profile=profile_1, published_catalogue=catalogue)
    assert res["components"]["saturation_penalty"] == 15

def test_script_structure_validation():
    profile_1 = Settings.load_account_profile("account_01_psychology")
    script = "HOOK: Have you ever felt this? CURIOSITY: Here is why. PSYCHOLOGICAL MECHANISM: Your brain exaggerates attention. REALIZATION: You realize it is human. FINAL LINE: Remember this."

    res = validate_script_structure(script, profile_1)
    assert res["valid"] is True
    assert len(res["missing_stages"]) == 0

def test_omniroute_routing(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_API_KEY", "mock-key")

    def mock_run_omniroute(prompt, api_key, base_url, model, timeout):
        return "Generated script via OmniRoute"

    import director.scriptwriter_adapter as sw
    monkeypatch.setattr(sw, "_run_omniroute_gateway", mock_run_omniroute)

    output = generate_text("Write a hook")
    assert output == "Generated script via OmniRoute"
