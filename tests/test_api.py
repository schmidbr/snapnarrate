from __future__ import annotations

import http.client
import json
from pathlib import Path

import pytest

from snap_narrate import events
from snap_narrate.addons import AddonContext
from snap_narrate.addons.api import LocalApi
from snap_narrate.config import AppConfig
from snap_narrate.events import EventBus


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.paused = False

    def status(self) -> dict:
        return {"state": "idle", "paused": self.paused, "capture_mode": "fullscreen"}

    def capture(self, source: str) -> None:
        self.calls.append(("capture", source))

    def capture_region(self, source: str) -> None:
        self.calls.append(("region", source))

    def capture_fullscreen(self, source: str) -> None:
        self.calls.append(("fullscreen", source))

    def stop_speaking(self) -> None:
        self.calls.append(("stop",))

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def speak(self, text: str, source: str) -> None:
        self.calls.append(("speak", text))

    def submit_image(self, image: bytes, source: str) -> None:
        self.calls.append(("image", len(image)))


@pytest.fixture
def api(tmp_path: Path):
    cfg = AppConfig()
    cfg.api.port = 0  # let the OS pick
    engine, bus = FakeEngine(), EventBus()
    server = LocalApi()
    server.start(AddonContext(engine=engine, bus=bus, config=cfg, ui=None, data_dir=tmp_path))  # type: ignore[arg-type]
    token = (tmp_path / "api_token.txt").read_text(encoding="utf-8")
    yield server, engine, bus, token
    server.stop()


def request(port: int, method: str, path: str, token: str | None, body: bytes | None = None, ctype: str = "application/json"):  # noqa: ANN201
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": ctype}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def test_requires_token(api) -> None:  # noqa: ANN001
    server, engine, _bus, _token = api
    assert request(server.port, "POST", "/v1/stop", None)[0] == 401
    assert request(server.port, "POST", "/v1/stop", "wrong")[0] == 401
    assert engine.calls == []


def test_commands_reach_engine(api) -> None:  # noqa: ANN001
    server, engine, _bus, token = api
    port = server.port
    assert request(port, "POST", "/v1/capture", token, b'{"mode": "region"}')[0] == 202
    assert request(port, "POST", "/v1/capture", token)[0] == 202
    assert request(port, "POST", "/v1/stop", token)[0] == 202
    assert request(port, "POST", "/v1/speak", token, b'{"text": "hello"}')[0] == 202
    assert request(port, "POST", "/v1/narrate-image", token, b"\x89PNG....", "image/png")[0] == 202
    assert request(port, "POST", "/v1/pause", token, b'{"paused": true}')[0] == 202
    assert engine.calls == [("region", "api"), ("capture", "api"), ("stop",), ("speak", "hello"), ("image", 8)]
    assert engine.paused is True


def test_bad_input_is_400(api) -> None:  # noqa: ANN001
    server, _engine, _bus, token = api
    assert request(server.port, "POST", "/v1/speak", token, b"{}")[0] == 400
    assert request(server.port, "POST", "/v1/capture", token, b'{"mode": "webcam"}')[0] == 400


def test_status_and_event_stream(api) -> None:  # noqa: ANN001
    server, _engine, bus, token = api
    status, body = request(server.port, "GET", "/v1/status", token)
    assert status == 200 and json.loads(body)["state"] == "idle"

    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request("GET", f"/v1/events?token={token}")
    response = conn.getresponse()
    assert response.status == 200
    assert response.readline().startswith(b"event: status")
    response.readline()  # data
    response.readline()  # blank
    bus.publish(events.SPEECH_CHUNK, session=1, text="Hi there")
    assert response.readline() == b"event: speech.chunk\n"
    assert json.loads(response.readline()[len(b"data: ") :])["data"]["text"] == "Hi there"
    conn.close()
