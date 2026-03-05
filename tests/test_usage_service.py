from __future__ import annotations

from snap_narrate.usage import (
    USAGE_STATUS_OK,
    USAGE_STATUS_UNAUTHORIZED,
    UsageService,
    record_openai_usage,
)


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_usage_service_openai_org_success_and_budget(monkeypatch) -> None:
    def fake_get(url, headers=None, params=None, timeout=None):  # noqa: ANN001,ARG001
        if url.endswith("/v1/organization/usage/completions"):
            return _Resp(
                200,
                {
                    "data": [
                        {"results": [{"input_tokens": 120, "output_tokens": 80}]},
                        {"results": [{"input_tokens": 10, "output_tokens": 5}]},
                    ]
                },
            )
        if url.endswith("/v1/organization/costs"):
            return _Resp(200, {"data": [{"results": [{"amount": {"value": 2.25}}]}]})
        if url.endswith("/v1/user/subscription"):
            return _Resp(200, {"character_count": 400, "character_limit": 1000, "next_character_count_reset_unix": 12345})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("requests.get", fake_get)
    svc = UsageService(
        openai_api_key="oa",
        openai_admin_api_key="oa-admin",
        openai_base_url="https://api.openai.com",
        openai_monthly_budget_usd=5.0,
        elevenlabs_api_key="el",
        timeout_sec=5,
        cache_seconds=0,
    )
    snap = svc.get_snapshot(force_refresh=True)
    assert snap.openai.status == USAGE_STATUS_OK
    assert snap.openai.source == "organization"
    assert snap.openai.prompt_tokens == 130
    assert snap.openai.completion_tokens == 85
    assert snap.openai.total_tokens == 215
    assert snap.openai.cost_usd == 2.25
    assert snap.openai.remaining_usd == 2.75
    assert snap.elevenlabs.status == USAGE_STATUS_OK
    assert snap.elevenlabs.remaining_characters == 600


def test_usage_service_openai_falls_back_to_session_on_unauthorized(monkeypatch) -> None:
    record_openai_usage({"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40})

    def fake_get(url, headers=None, params=None, timeout=None):  # noqa: ANN001,ARG001
        if url.endswith("/v1/organization/usage/completions"):
            return _Resp(403, {"error": "forbidden"})
        if url.endswith("/v1/user/subscription"):
            return _Resp(403, {"detail": "unauthorized"})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("requests.get", fake_get)
    svc = UsageService(
        openai_api_key="oa",
        openai_admin_api_key="oa-admin",
        openai_base_url="https://api.openai.com",
        openai_monthly_budget_usd=None,
        elevenlabs_api_key="el",
        timeout_sec=5,
        cache_seconds=0,
    )
    snap = svc.get_snapshot(force_refresh=True)
    assert snap.openai.status == USAGE_STATUS_UNAUTHORIZED
    assert snap.openai.source == "session_fallback"
    assert snap.openai.total_tokens >= 40
    assert snap.openai.remaining_usd is None
    assert snap.elevenlabs.status == USAGE_STATUS_UNAUTHORIZED

