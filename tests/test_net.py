from __future__ import annotations

import http.client

import pytest
import requests
from requests.adapters import BaseAdapter
from urllib3.exceptions import ProtocolError

from snap_narrate.providers.elevenlabs import ElevenLabsSpeech
from snap_narrate.providers.net import CONNECTION_RETRIES, Session


def dropped() -> requests.ConnectionError:
    """What requests raises when a kept-alive connection was closed while idle."""
    return requests.ConnectionError(
        ProtocolError("Connection aborted.", http.client.RemoteDisconnected("Remote end closed connection without response"))
    )


class FlakyServer(BaseAdapter):
    """Fails the first `failures` requests with `error`, then answers 200."""

    def __init__(self, failures: int, error=dropped) -> None:  # noqa: ANN001
        super().__init__()
        self.failures, self.error = failures, error
        self.bodies: list[bytes | str | None] = []

    def send(self, request: requests.PreparedRequest, **kwargs) -> requests.Response:  # noqa: ANN003
        self.bodies.append(request.body)
        if len(self.bodies) <= self.failures:
            raise self.error()
        response = requests.Response()
        response.status_code, response._content, response.request, response.url = 200, b"audio", request, request.url
        return response

    def close(self) -> None:
        pass


def session_with(server: FlakyServer) -> Session:
    session = Session()
    session.mount("https://", server)
    return session


def test_request_on_a_dropped_idle_connection_is_sent_again() -> None:
    server = FlakyServer(failures=1)
    response = session_with(server).post("https://ollama.com/api/chat", json={"model": "gemma4:31b"})
    assert response.status_code == 200
    assert len(server.bodies) == 2 and server.bodies[0] == server.bodies[1]  # same request, resent


def test_gives_up_after_a_few_attempts() -> None:
    server = FlakyServer(failures=99)
    with pytest.raises(requests.ConnectionError):
        session_with(server).post("https://ollama.com/api/chat", json={})
    assert len(server.bodies) == CONNECTION_RETRIES + 1


def test_timeouts_are_not_resent() -> None:
    server = FlakyServer(failures=99, error=requests.ConnectTimeout)
    with pytest.raises(requests.ConnectTimeout):
        session_with(server).post("https://ollama.com/api/chat", json={})
    assert len(server.bodies) == 1


def test_first_narration_after_a_break_still_speaks() -> None:
    """2026-10-03: after ~10 idle minutes the first capture failed and had to be pressed again."""
    speech = ElevenLabsSpeech("sk_test", "voice")
    speech._session.mount("https://", FlakyServer(failures=1))
    assert speech.synthesize("Hello again.") == b"audio"
