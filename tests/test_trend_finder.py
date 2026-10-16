from io import BytesIO
from research.trend_finder import creative_center_status


class FakeResponse:
    status = 200
    headers = {"Content-Type": "text/html; charset=utf-8"}
    def __init__(self, body, url="https://ads.tiktok.com/creative/creativeCenter/trends"):
        self._body = body
        self._url = url
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, n=-1): return self._body[:n]
    def geturl(self): return self._url


def test_creative_center_only_reports_hashtags_found_in_visible_html(monkeypatch):
    import urllib.request
    body = b"<html><head><title>Trends</title><script>const fake='#notvisible';</script></head><body><h1>Trending</h1><p>#realtrend #another_trend</p></body></html>"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: FakeResponse(body))
    result = creative_center_status()
    assert result["http_status"] == 200
    assert [item["hashtag"] for item in result["public_hashtags_found"]] == ["#realtrend", "#another_trend"]
    assert result["metrics"] == {}


def test_creative_center_http_failure_is_reported_without_fabrication(monkeypatch):
    import urllib.request
    import urllib.error
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://ads.tiktok.com/creative/creativeCenter/trends", 403, "Forbidden", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    result = creative_center_status()
    assert result["status"] == "blocked_or_unavailable"
    assert result["http_status"] == 403
    assert result["public_hashtags_found"] == []
