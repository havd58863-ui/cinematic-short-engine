from research.source_registry import deduplicate_sources, normalize_source

def test_source_registry_normalizes_provenance():
    source = normalize_source({"title":"A page","href":"https://example.com/path","body":"excerpt","date":"2026-10-15"})
    assert source["url"] == "https://example.com/path"
    assert source["domain"] == "example.com"
    assert source["published_at"] == "2026-10-15"
    assert source["metrics"] == {}

def test_source_registry_deduplicates_urls_and_keeps_more_text():
    sources = deduplicate_sources([
        {"title":"A","url":"https://example.com/a","extracted_text":"short"},
        {"title":"A better text","url":"https://example.com/a","extracted_text":"longer extracted article"},
    ])
    assert len(sources) == 1
    assert sources[0]["title"] == "A better text"
