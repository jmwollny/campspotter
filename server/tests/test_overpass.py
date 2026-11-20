import overpass


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code, self._payload, self.text = status_code, payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_overpass_tries_next_mirror_on_failure(monkeypatch):
    monkeypatch.setenv(
        "OVERPASS_URLS", "https://a.example, https://b.example ,https://c.example"
    )
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if url == "https://a.example":
            raise overpass.requests.exceptions.ConnectTimeout("dead mirror")
        if url == "https://b.example":
            return FakeResponse(502, text="at capacity")
        return FakeResponse(200, {"elements": [{"id": 1}]})

    monkeypatch.setattr(overpass.requests, "post", fake_post)
    assert overpass.call_overpass_with_retry("query") == {"elements": [{"id": 1}]}
    assert calls == ["https://a.example", "https://b.example", "https://c.example"]


def test_overpass_stops_on_syntax_error(monkeypatch):
    monkeypatch.setenv("OVERPASS_URLS", "https://a.example,https://b.example")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResponse(400, text="parse error")

    monkeypatch.setattr(overpass.requests, "post", fake_post)
    assert overpass.call_overpass_with_retry("bad query") is None
    assert calls == ["https://a.example"]


def test_overpass_backs_off_exponentially_when_all_mirrors_are_busy(monkeypatch):
    monkeypatch.setenv("OVERPASS_URLS", "https://a.example")
    monkeypatch.setenv("OVERPASS_MAX_ROUNDS", "4")
    monkeypatch.setenv("OVERPASS_BACKOFF_S", "2")
    sleeps: list[float] = []
    attempts: list[str] = []
    monkeypatch.setattr(overpass.time, "sleep", sleeps.append)

    def fake_post(url, **kwargs):
        attempts.append(url)
        if len(attempts) < 4:
            return FakeResponse(502, text="at capacity")
        return FakeResponse(200, {"elements": []})

    monkeypatch.setattr(overpass.requests, "post", fake_post)
    assert overpass.call_overpass_with_retry("query") == {"elements": []}
    assert sleeps == [2, 4, 8]


def test_overpass_gives_up_after_max_rounds(monkeypatch):
    monkeypatch.setenv("OVERPASS_URLS", "https://a.example,https://b.example")
    monkeypatch.setenv("OVERPASS_MAX_ROUNDS", "2")
    attempts: list[str] = []

    def fake_post(url, **kwargs):
        attempts.append(url)
        return FakeResponse(429)

    monkeypatch.setattr(overpass.requests, "post", fake_post)
    assert overpass.call_overpass_with_retry("query") is None
    assert len(attempts) == 4


def test_default_mirror_order_tries_reliable_mirror_first():
    assert (
        overpass.get_overpass_mirrors()[0] == "https://overpass-api.de/api/interpreter"
    )
