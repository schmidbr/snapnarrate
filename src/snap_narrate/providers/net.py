"""HTTP plumbing shared by the providers."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import requests

logger = logging.getLogger("snap_narrate")

CONNECTION_RETRIES = 2


class Session(requests.Session):
    """A requests.Session that resends a request when the connection fails before any
    response arrives.

    Providers keep connections open between captures. After a few idle minutes, servers
    (or the network in between) silently drop them, so the first capture after a break
    went out on a dead connection and failed with "Remote end closed connection without
    response". Nothing was processed, so sending again on a fresh connection is safe.
    Timeouts are not retried: the server may still be working on those.
    """

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:  # type: ignore[override]
        for attempt in range(CONNECTION_RETRIES + 1):
            try:
                return super().send(request, **kwargs)
            except requests.ConnectionError as exc:
                if isinstance(exc, requests.Timeout) or attempt == CONNECTION_RETRIES:
                    raise
                url = urlsplit(request.url or "")
                logger.info("event=http_retry reason=connection_dropped host=%s path=%s error=%s", url.netloc, url.path, exc)
        raise AssertionError("unreachable")
