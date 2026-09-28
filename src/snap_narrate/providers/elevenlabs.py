"""ElevenLabs text-to-speech."""

from __future__ import annotations

from typing import Any

import requests

API_BASE = "https://api.elevenlabs.io/v1"


class ElevenLabsSpeech:
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        speech_fast_model_id: str = "",
        output_format: str = "mp3_44100_128",
        timeout_sec: int = 60,
        session: Any = None,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.speech_fast_model_id = speech_fast_model_id.strip()
        self.output_format = output_format
        self.timeout_sec = timeout_sec
        self._session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("ElevenLabs API key is missing. Open Settings to add it.")
        return {"xi-api-key": self.api_key}

    def synthesize(self, text: str, fast: bool = False) -> bytes:
        headers = self._headers()
        if not self.voice_id:
            raise ValueError("No ElevenLabs voice selected. Open Settings to choose one.")
        model = (self.speech_fast_model_id or self.model_id) if fast else self.model_id
        response = self._session.post(
            f"{API_BASE}/text-to-speech/{self.voice_id}",
            headers={**headers, "Accept": "application/octet-stream"},
            params={"output_format": self.output_format},
            json={"text": text, "model_id": model},
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"ElevenLabs synthesis failed ({response.status_code}): {response.text[:200]}")
        if not response.content:
            raise RuntimeError("ElevenLabs returned an empty audio payload")
        return response.content

    def list_voices(self) -> list[tuple[str, str]]:
        """[(voice_id, name)] for every voice available to this API key."""
        response = self._session.get(f"{API_BASE}/voices", headers=self._headers(), timeout=self.timeout_sec)
        if response.status_code >= 400:
            raise RuntimeError(f"ElevenLabs voices failed ({response.status_code}): {response.text[:200]}")
        voices = response.json().get("voices", [])
        return sorted(
            ((str(v.get("voice_id", "")), str(v.get("name", ""))) for v in voices),
            key=lambda item: item[1].lower(),
        )
