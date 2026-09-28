"""Local control API: lets widgets, overlays, and tools in any language drive SnapNarrate.

Listens on 127.0.0.1 only and requires a bearer token stored in
%APPDATA%\\SnapNarrate\\api_token.txt, so web pages and other users cannot trigger
captures (which would send the screen to a cloud model). Endpoints are in docs/ADDONS.md.
"""

from __future__ import annotations

import hmac
import json
import logging
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from snap_narrate import events
from snap_narrate.addons import AddonContext
from snap_narrate.version import get_app_version

logger = logging.getLogger("snap_narrate")

MAX_IMAGE_BYTES = 20 * 1024 * 1024
SSE_HEARTBEAT_SEC = 15.0


def load_or_create_token(data_dir: Path) -> str:
    path = data_dir / "api_token.txt"
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except FileNotFoundError:
        pass
    data_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    return token


class LocalApi:
    name = "api"

    def __init__(self) -> None:
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, ctx: AddonContext) -> None:
        token = load_or_create_token(ctx.data_dir)
        handler = type("BoundHandler", (_Handler,), {"ctx": ctx, "token": token, "port": ctx.config.api.port})
        self._server = ThreadingHTTPServer(("127.0.0.1", ctx.config.api.port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="snapnarrate-api", daemon=True)
        self._thread.start()
        logger.info("event=api_listening port=%s", ctx.config.api.port)

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else 0

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class _Handler(BaseHTTPRequestHandler):
    ctx: AddonContext
    token: str
    port: int
    protocol_version = "HTTP/1.1"
    server_version = "SnapNarrate"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("event=api_request " + fmt, *args)

    # ---- plumbing ---------------------------------------------------------------------

    def _authorized(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host not in {"127.0.0.1", "localhost"}:  # DNS-rebinding guard
            return False
        supplied = ""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        else:
            supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return bool(supplied) and hmac.compare_digest(supplied, self.token)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self, limit: int = 64 * 1024) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ValueError(f"Request body too large (limit {limit} bytes)")
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _route(self) -> str:
        return urlparse(self.path).path.rstrip("/")

    # ---- endpoints --------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        route = self._route()
        if route == "/v1/status":
            self._send_json(200, {"version": get_app_version(), **self.ctx.engine.status()})
        elif route == "/v1/events":
            self._stream_events()
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        engine = self.ctx.engine
        route = self._route()
        try:
            if route == "/v1/capture":
                mode = self._json_body().get("mode")
                if mode == "region":
                    engine.capture_region("api")
                elif mode == "fullscreen":
                    engine.capture_fullscreen("api")
                elif mode in (None, ""):
                    engine.capture("api")
                else:
                    raise ValueError("mode must be 'fullscreen', 'region', or omitted")
            elif route == "/v1/stop":
                engine.stop_speaking()
            elif route == "/v1/pause":
                body = self._json_body()
                engine.set_paused(bool(body.get("paused", not engine.paused)))
            elif route == "/v1/speak":
                text = str(self._json_body().get("text", "")).strip()
                if not text:
                    raise ValueError("text is required")
                engine.speak(text, "api")
            elif route == "/v1/narrate-image":
                if not (self.headers.get("Content-Type") or "").startswith(("image/png", "image/jpeg")):
                    raise ValueError("Content-Type must be image/png or image/jpeg")
                engine.submit_image(self._read_body(limit=MAX_IMAGE_BYTES), "api")
            else:
                self._send_json(404, {"error": "not found"})
                return
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(202, {"ok": True, **engine.status()})

    def _stream_events(self) -> None:
        inbox: queue.Queue[events.Event] = queue.Queue(maxsize=256)

        def forward(event: events.Event) -> None:
            try:
                inbox.put_nowait(event)
            except queue.Full:
                pass  # slow client: drop rather than block the engine

        unsubscribe = self.ctx.bus.subscribe(events.ALL, forward)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            initial = events.Event(events.STATUS, self.ctx.engine.status())
            self._write_event(initial)
            while True:
                try:
                    self._write_event(inbox.get(timeout=SSE_HEARTBEAT_SEC))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            unsubscribe()

    def _write_event(self, event: events.Event) -> None:
        data = json.dumps(event.to_dict())
        self.wfile.write(f"event: {event.topic}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()
