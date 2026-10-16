from research.idea_scoring import score_idea, rank_topic_results

def test_score_is_bounded_and_provenance_preserved():
    sources=[{"title":"Why this unexpected warning matters","snippet":"A visual investigation","url":"https://example.com/story","published_at":"2026-10-15"}]
    result=score_idea("The warning nobody expected",sources)
    assert 0 <= result["score"] <= 100
    assert result["evidence_urls"] == ["https://example.com/story"]
    assert "not a measured prediction" in result["limitations"][0]

def test_rank_sorts_descending():
    ranked=rank_topic_results([{"title":"low","score":1},{"title":"high","score":90}])
    assert [x["title"] for x in ranked] == ["high","low"]

def test_freshness_score_uses_age_not_only_date_presence():
    from datetime import datetime, timezone
    now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    recent = score_idea("Why this unexpected event matters", [{"title": "Recent report", "snippet": "evidence visual", "url": "https://example.com/recent", "published_at": "2026-10-15"}], now_utc=now)
    old = score_idea("Why this unexpected event matters", [{"title": "Old report", "snippet": "evidence visual", "url": "https://example.com/old", "published_at": "2024-01-01"}], now_utc=now)
    assert recent["components"]["freshness_signal_max_15"] > old["components"]["freshness_signal_max_15"]
    assert recent["freshness_evidence"][0]["age_days"] <= 2
    assert old["freshness_evidence"][0]["points"] == 0
