from tiktok_director.scriptwriter import estimate_duration_seconds

def test_duration_estimate_is_positive():
    assert estimate_duration_seconds("hello there this is a test script") > 0

def test_duration_scales_with_words():
    assert estimate_duration_seconds("word " * 100) > estimate_duration_seconds("word " * 20)
