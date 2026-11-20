import http.server
import json
import threading
import time
from types import SimpleNamespace
from typing import cast

import pytest
import requests

import overpass


class FakeResponse:
    """A streamed requests.Response: the body is read with raw.read1() like the real one."""

    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        body = json.dumps(payload) if payload is not None else text
        self._chunks = [body.encode()] if body else []
        self.raw = SimpleNamespace(read1=self._read1)
        self.closed = False

    def _read1(self, amt=None, decode_content=None):
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        self.closed = True


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


# The real requests.post, captured before conftest's autouse fixture blocks the network.
REAL_POST = requests.post


class StoppableServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, handler: type[http.server.BaseHTTPRequestHandler]) -> None:
        super().__init__(("127.0.0.1", 0), handler)
        self.stopping = threading.Event()


class TricklingHandler(http.server.BaseHTTPRequestHandler):
    server: StoppableServer

    """Answers 200, then sends one byte every 50 ms forever - never silent for long."""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            while not self.server.stopping.is_set():
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client gave up, as it should

    def log_message(self, *args):
        pass


class AnswerHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = b'{"elements": [{"id": 1}]}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    servers = []

    def start(handler):
        server = StoppableServer(handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}/api/interpreter"

    yield start
    for server in servers:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def test_a_mirror_that_trickles_data_forever_is_abandoned(monkeypatch, local_server):
    """Regression: a mirror kept a request open for 90 minutes by trickling data, which
    the read timeout (time between packets) never caught."""
    trickling = local_server(TricklingHandler)
    healthy = local_server(AnswerHandler)
    monkeypatch.setattr(overpass.requests, "post", REAL_POST)
    monkeypatch.setenv("OVERPASS_URLS", f"{trickling},{healthy}")
    monkeypatch.setenv(
        "OVERPASS_READ_TIMEOUT_S", "5"
    )  # longer than any gap between bytes
    monkeypatch.setenv("OVERPASS_TOTAL_TIMEOUT_S", "0.5")

    started = time.perf_counter()
    payload = overpass.call_overpass_with_retry("query")

    assert payload == {"elements": [{"id": 1}]}  # moved on to the healthy mirror
    assert time.perf_counter() - started < 3


def test_read_body_respects_the_limit():
    response = FakeResponse(502, text="x" * 10_000)
    response._chunks = [b"x" * 1000] * 10
    body = overpass.read_body(
        cast(requests.Response, response), deadline=time.perf_counter() + 5, limit=2000
    )
    assert len(body) == 2000
