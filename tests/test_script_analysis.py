from director.script_analysis import analyze_script, estimate_duration_seconds

def test_duration_estimate_is_positive():
    assert estimate_duration_seconds("hello there this is a test script") > 0

def test_duration_scales_with_words():
    assert estimate_duration_seconds("word " * 100) > estimate_duration_seconds("word " * 20)

def test_analysis_extracts_paragraphs_and_hook():
    result = analyze_script("Look at this.\n\nNow the problem gets worse.\n\nHere is the payoff.", target_seconds=15)
    assert result["opening_hook"] == "Look at this."
    assert result["paragraph_count"] == 3
    assert result["word_count"] == 12
