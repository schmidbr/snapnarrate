from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from snap_narrate.config import AppConfig


USAGE_STATUS_OK = "ok"
USAGE_STATUS_UNAUTHORIZED = "unauthorized"
USAGE_STATUS_UNAVAILABLE = "unavailable"
USAGE_STATUS_NETWORK_ERROR = "network_error"
USAGE_STATUS_PARSE_ERROR = "parse_error"


@dataclass
class OpenAIUsageSnapshot:
    period_start: int | None = None
    period_end: int | None = None
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    remaining_usd: float | None = None
    source: str = "none"
    status: str = USAGE_STATUS_UNAVAILABLE


@dataclass
class ElevenLabsUsageSnapshot:
    character_count: int | None = None
    character_limit: int | None = None
    remaining_characters: int | None = None
    next_reset_unix: int | None = None
    status: str = USAGE_STATUS_UNAVAILABLE


@dataclass
class UsageSnapshot:
    fetched_at_unix: int
    openai: OpenAIUsageSnapshot
    elevenlabs: ElevenLabsUsageSnapshot

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpenAISessionUsageTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0

    def record(self, usage_payload: dict[str, Any] | None) -> None:
        if not usage_payload:
            return
        try:
            prompt = int(usage_payload.get("prompt_tokens", 0) or 0)
            completion = int(usage_payload.get("completion_tokens", 0) or 0)
            total = int(usage_payload.get("total_tokens", 0) or 0)
        except (TypeError, ValueError):
            return

        if total == 0:
            total = prompt + completion

        with self._lock:
            self._prompt_tokens += max(prompt, 0)
            self._completion_tokens += max(completion, 0)
            self._total_tokens += max(total, 0)

    def snapshot(self) -> tuple[int, int, int]:
        with self._lock:
            return self._prompt_tokens, self._completion_tokens, self._total_tokens


_OPENAI_TRACKER = OpenAISessionUsageTracker()


def record_openai_usage(usage_payload: dict[str, Any] | None) -> None:
    _OPENAI_TRACKER.record(usage_payload)


def _month_bounds_unix(now: datetime | None = None) -> tuple[int, int]:
    current = now or datetime.now(timezone.utc)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return int(start.timestamp()), int(end.timestamp())


def _sum_openai_token_data(payload: dict[str, Any]) -> tuple[int, int]:
    prompt_tokens = 0
    completion_tokens = 0
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        return 0, 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        results = row.get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            prompt_tokens += int(result.get("input_tokens", 0) or 0)
            completion_tokens += int(result.get("output_tokens", 0) or 0)
    return prompt_tokens, completion_tokens


def _sum_openai_cost_data(payload: dict[str, Any]) -> float:
    total = 0.0
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        return 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        results = row.get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            amount = result.get("amount", {})
            if isinstance(amount, dict):
                total += float(amount.get("value", 0.0) or 0.0)
    return total


class UsageService:
    def __init__(
        self,
        openai_api_key: str,
        openai_admin_api_key: str,
        openai_base_url: str,
        openai_monthly_budget_usd: float | None,
        elevenlabs_api_key: str,
        timeout_sec: int = 10,
        cache_seconds: int = 60,
    ) -> None:
        self.openai_api_key = openai_api_key.strip()
        self.openai_admin_api_key = openai_admin_api_key.strip()
        self.openai_base_url = openai_base_url.rstrip("/")
        self.openai_monthly_budget_usd = openai_monthly_budget_usd
        self.elevenlabs_api_key = elevenlabs_api_key.strip()
        self.timeout_sec = timeout_sec
        self.cache_seconds = max(cache_seconds, 0)

        self._cache_lock = threading.Lock()
        self._cached_at = 0.0
        self._cached_snapshot: UsageSnapshot | None = None

    @classmethod
    def from_config(cls, cfg: AppConfig) -> "UsageService":
        return cls(
            openai_api_key=cfg.openai.api_key,
            openai_admin_api_key=cfg.openai.admin_api_key or cfg.openai.api_key,
            openai_base_url=cfg.openai.base_url,
            openai_monthly_budget_usd=cfg.usage.openai_monthly_budget_usd,
            elevenlabs_api_key=cfg.elevenlabs.api_key,
            timeout_sec=max(cfg.vision.timeout_sec, 5),
            cache_seconds=cfg.usage.cache_seconds,
        )

    def get_snapshot(self, force_refresh: bool = False) -> UsageSnapshot:
        now_ts = time.time()
        with self._cache_lock:
            if (
                not force_refresh
                and self._cached_snapshot is not None
                and (now_ts - self._cached_at) < self.cache_seconds
            ):
                return self._cached_snapshot

        openai = self._fetch_openai_usage()
        eleven = self._fetch_elevenlabs_usage()
        snapshot = UsageSnapshot(
            fetched_at_unix=int(now_ts),
            openai=openai,
            elevenlabs=eleven,
        )
        with self._cache_lock:
            self._cached_snapshot = snapshot
            self._cached_at = now_ts
        return snapshot

    def _fetch_openai_usage(self) -> OpenAIUsageSnapshot:
        import requests

        period_start, period_end = _month_bounds_unix()
        prompt_session, completion_session, total_session = _OPENAI_TRACKER.snapshot()
        fallback = OpenAIUsageSnapshot(
            period_start=period_start,
            period_end=period_end,
            total_tokens=total_session,
            prompt_tokens=prompt_session,
            completion_tokens=completion_session,
            cost_usd=None,
            remaining_usd=None,
            source="session_fallback",
            status=USAGE_STATUS_UNAVAILABLE,
        )

        if not self.openai_api_key:
            return fallback

        headers = {
            "Authorization": f"Bearer {self.openai_admin_api_key or self.openai_api_key}",
            "Content-Type": "application/json",
        }

        params = {"start_time": period_start, "end_time": period_end}
        usage_url = f"{self.openai_base_url}/v1/organization/usage/completions"
        cost_url = f"{self.openai_base_url}/v1/organization/costs"

        try:
            usage_resp = requests.get(usage_url, headers=headers, params=params, timeout=self.timeout_sec)
        except requests.RequestException:
            fallback.status = USAGE_STATUS_NETWORK_ERROR
            return fallback

        if usage_resp.status_code in (401, 403):
            fallback.status = USAGE_STATUS_UNAUTHORIZED
            return fallback
        if usage_resp.status_code >= 400:
            fallback.status = USAGE_STATUS_UNAVAILABLE
            return fallback

        try:
            usage_payload = usage_resp.json()
            prompt_tokens, completion_tokens = _sum_openai_token_data(usage_payload)
        except Exception:
            fallback.status = USAGE_STATUS_PARSE_ERROR
            return fallback

        openai_snapshot = OpenAIUsageSnapshot(
            period_start=period_start,
            period_end=period_end,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            source="organization",
            status=USAGE_STATUS_OK,
        )

        try:
            cost_resp = requests.get(cost_url, headers=headers, params=params, timeout=self.timeout_sec)
            if cost_resp.status_code < 400:
                cost_payload = cost_resp.json()
                openai_snapshot.cost_usd = _sum_openai_cost_data(cost_payload)
                if self.openai_monthly_budget_usd is not None:
                    openai_snapshot.remaining_usd = self.openai_monthly_budget_usd - openai_snapshot.cost_usd
            elif cost_resp.status_code in (401, 403):
                openai_snapshot.status = USAGE_STATUS_UNAUTHORIZED
            else:
                openai_snapshot.status = USAGE_STATUS_UNAVAILABLE
        except requests.RequestException:
            openai_snapshot.status = USAGE_STATUS_NETWORK_ERROR
        except Exception:
            openai_snapshot.status = USAGE_STATUS_PARSE_ERROR

        return openai_snapshot

    def _fetch_elevenlabs_usage(self) -> ElevenLabsUsageSnapshot:
        import requests

        if not self.elevenlabs_api_key:
            return ElevenLabsUsageSnapshot(status=USAGE_STATUS_UNAVAILABLE)

        try:
            response = requests.get(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": self.elevenlabs_api_key},
                timeout=self.timeout_sec,
            )
        except requests.RequestException:
            return ElevenLabsUsageSnapshot(status=USAGE_STATUS_NETWORK_ERROR)

        if response.status_code in (401, 403):
            return ElevenLabsUsageSnapshot(status=USAGE_STATUS_UNAUTHORIZED)
        if response.status_code >= 400:
            return ElevenLabsUsageSnapshot(status=USAGE_STATUS_UNAVAILABLE)

        try:
            payload = response.json()
            character_count = int(payload.get("character_count", 0))
            character_limit = int(payload.get("character_limit", 0))
            next_reset = payload.get("next_character_count_reset_unix")
            next_reset_unix = int(next_reset) if next_reset is not None else None
            remaining = max(character_limit - character_count, 0)
            return ElevenLabsUsageSnapshot(
                character_count=character_count,
                character_limit=character_limit,
                remaining_characters=remaining,
                next_reset_unix=next_reset_unix,
                status=USAGE_STATUS_OK,
            )
        except Exception:
            return ElevenLabsUsageSnapshot(status=USAGE_STATUS_PARSE_ERROR)

