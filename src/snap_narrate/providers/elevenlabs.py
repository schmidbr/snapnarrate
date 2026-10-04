"""ElevenLabs text-to-speech."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from snap_narrate.providers.net import Session

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
        self._session = session or Session()

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
        return [(voice.voice_id, voice.name) for voice in self.voices()]

    def voices(self) -> list["Voice"]:
        """Every voice available to this API key, with descriptive labels, sorted by name."""
        response = self._session.get(f"{API_BASE}/voices", headers=self._headers(), timeout=self.timeout_sec)
        if response.status_code in (401, 403):
            raise ValueError("ElevenLabs rejected the API key. Check it in Settings.")
        if response.status_code >= 400:
            raise RuntimeError(f"ElevenLabs voices failed ({response.status_code}): {response.text[:200]}")
        voices = [Voice.from_api(v) for v in response.json().get("voices", []) if v.get("voice_id")]
        return sorted(voices, key=lambda voice: voice.name.lower())

    def fetch_preview(self, voice: "Voice") -> bytes:
        """The voice's public sample clip (MP3). Free: it does not use character credits."""
        if not voice.preview_url:
            raise ValueError(f"{voice.name} has no sample clip")
        response = self._session.get(voice.preview_url, timeout=self.timeout_sec)
        response.raise_for_status()
        return response.content


@dataclass(frozen=True)
class Voice:
    voice_id: str
    name: str
    category: str = ""  # premade, cloned, generated, professional
    labels: tuple[tuple[str, str], ...] = ()
    preview_url: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Voice":
        labels = data.get("labels") or {}
        return cls(
            voice_id=str(data.get("voice_id", "")),
            name=str(data.get("name", "")).strip() or "Unnamed voice",
            category=str(data.get("category") or ""),
            labels=tuple((str(k), str(v)) for k, v in labels.items() if v),
            preview_url=str(data.get("preview_url") or ""),
        )

    @property
    def details(self) -> str:
        """'American · Middle aged · Male · Narration' style summary for pickers."""
        values = dict(self.labels)
        parts = [values.get(key, "") for key in ("accent", "age", "gender", "use_case", "use case", "descriptive", "description")]
        seen: list[str] = []
        for part in parts:
            cleaned = part.replace("_", " ").strip()
            if cleaned and cleaned.lower() not in (s.lower() for s in seen):
                seen.append(cleaned[:1].upper() + cleaned[1:])
        if self.category and self.category not in ("premade",):
            seen.append(self.category.title())
        return " · ".join(seen[:4])
