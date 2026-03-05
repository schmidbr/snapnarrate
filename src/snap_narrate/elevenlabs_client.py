from __future__ import annotations

import io

import numpy as np


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str,
        output_format: str = "mp3_44100_128",
        timeout_sec: int = 60,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.timeout_sec = timeout_sec

    def synthesize(self, text: str) -> bytes:
        import requests

        if not self.api_key:
            raise ValueError("ElevenLabs API key is missing")
        if not self.voice_id:
            raise ValueError("ElevenLabs voice_id is missing")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/octet-stream",
        }
        payload = {
            "text": text,
            "model_id": self.model_id,
        }
        response = requests.post(
            url,
            headers=headers,
            params={"output_format": self.output_format},
            json=payload,
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"ElevenLabs synthesis failed ({response.status_code}): {response.text[:200]}")
        return response.content

    def list_voices(self) -> list[tuple[str, str]]:
        import requests

        if not self.api_key:
            raise ValueError("ElevenLabs API key is missing")

        response = requests.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": self.api_key},
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"ElevenLabs voices failed ({response.status_code}): {response.text[:200]}")

        voices = response.json().get("voices", [])
        return [(str(v.get("voice_id", "")), str(v.get("name", ""))) for v in voices]

    def get_subscription_usage(self) -> dict[str, int | None]:
        import requests

        if not self.api_key:
            raise ValueError("ElevenLabs API key is missing")

        response = requests.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": self.api_key},
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"ElevenLabs subscription failed ({response.status_code}): {response.text[:200]}")

        payload = response.json()
        character_count = int(payload.get("character_count", 0))
        character_limit = int(payload.get("character_limit", 0))
        next_reset = payload.get("next_character_count_reset_unix")
        next_reset_unix = int(next_reset) if next_reset is not None else None
        return {
            "character_count": character_count,
            "character_limit": character_limit,
            "remaining_characters": max(character_limit - character_count, 0),
            "next_reset_unix": next_reset_unix,
        }


class TempFileAudioPlayer:
    def __init__(self) -> None:
        self._is_playing = False

    @staticmethod
    def _is_mp3(audio_bytes: bytes) -> bool:
        return audio_bytes.startswith(b"ID3") or audio_bytes[:2] == b"\xff\xfb"

    @staticmethod
    def audio_from_bytes(audio_bytes: bytes) -> tuple[np.ndarray, int]:
        if not audio_bytes:
            raise RuntimeError("Empty audio payload from ElevenLabs")

        if TempFileAudioPlayer._is_mp3(audio_bytes):
            import soundfile as sf

            try:
                samples, samplerate = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=False)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Failed to decode MP3 payload: {exc}") from exc

            if samples is None or len(samples) == 0:
                raise RuntimeError("Decoded MP3 payload has no samples")
            return samples, int(samplerate)

        if len(audio_bytes) % 2 != 0:
            audio_bytes = audio_bytes[:-1]

        if not audio_bytes:
            raise RuntimeError("Audio payload became empty after PCM normalization")

        pcm = np.frombuffer(audio_bytes, dtype=np.int16)
        if pcm.size == 0:
            raise RuntimeError("No PCM samples decoded from ElevenLabs payload")
        samples = pcm.astype(np.float32) / 32768.0
        return samples, 44100

    def play(self, audio_bytes: bytes) -> None:
        import sounddevice as sd

        samples, samplerate = self.audio_from_bytes(audio_bytes)
        self._is_playing = True
        try:
            sd.play(samples, samplerate=samplerate, blocking=True)
        finally:
            self._is_playing = False

    def stop(self) -> None:
        import sounddevice as sd

        sd.stop()
