"""
app/clients/sts_elevenlabs_client.py

Bridge between ElevenLabs speech-to-speech and our pipeline.
Mirrors AzureTTSClient's contract: credentials read from env here and nowhere
else; returns 24kHz mono PCM WAV bytes so downstream ffmpeg is unchanged.
"""
from __future__ import annotations

import io
import json
import os
import wave
from pathlib import Path

STS_SAMPLE_RATE = 24000          # matches Azure's Riff24Khz16BitMonoPcm


class STSError(RuntimeError):
    pass


def _pcm_to_wav(pcm: bytes, sample_rate: int = STS_SAMPLE_RATE) -> bytes:
    """ElevenLabs pcm_* output is headerless raw PCM. Add the RIFF header so
    the bytes are indistinguishable from Azure's output to ffmpeg."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)                    # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class ElevenLabsSTSClient:
    """Converts an existing audio track into a target voice, preserving the
    source timing, emotion, intonation and pronounciation."""

    def __init__(self, api_key: str | None = None,
                 model_id: str = "eleven_multilingual_sts_v2"):
        self.api_key = api_key or os.environ.get("HEYHI_ELEVENLABS_API_KEY")
        if not self.api_key:
            raise STSError("HEYHI_ELEVENLABS_API_KEY not set")
        self.model_id = model_id
        self._client = None

    def convert(self, wav_path: str | Path, voice_id: str) -> bytes:
        """Return 24kHz mono PCM WAV bytes in the target voice."""
        from elevenlabs.client import ElevenLabs

        if self._client is None:
            self._client = ElevenLabs(api_key=self.api_key)

        wav_path = Path(wav_path)
        if not wav_path.is_file():
            raise STSError(f"STS input audio not found: {wav_path}")

        try:
            with wav_path.open("rb") as f:
                stream = self._client.speech_to_speech.convert(
                    voice_id=voice_id,
                    audio=f,
                    model_id=self.model_id,
                    output_format=f"pcm_{STS_SAMPLE_RATE}",
                    voice_settings=json.dumps({
                        "stability": 0.75,
                        "similarity_boost": 0.90,
                        "style": 0.0,
                        "use_speaker_boost": True,
                    }),
                    remove_background_noise=True,
                )
                pcm = b"".join(stream)
        except Exception as e:                     # quota, 5xx, network
            raise STSError(f"ElevenLabs STS failed for voice '{voice_id}': {e}") from e

        if not pcm:
            raise STSError(f"ElevenLabs STS returned empty audio for '{voice_id}'")
        return _pcm_to_wav(pcm)

    def list_voices(self, page_size: int = 100,
                    voice_type: str | None = None) -> list[dict]:
        """Paginate GET /v2/voices to completion and return shaped voice tags.
        voice_type=None"""
        from elevenlabs.client import ElevenLabs

        if self._client is None:
            self._client = ElevenLabs(api_key=self.api_key)

        out: list[dict] = []
        token: str | None = None
        try:
            while True:
                resp = self._client.voices.search(
                    page_size=page_size,
                    next_page_token=token,
                    voice_type=voice_type,
                )
                for v in _get(resp, "voices") or []:
                    out.append(_shape_voice(v))
                if not _get(resp, "has_more"):
                    break
                token = _get(resp, "next_page_token")
                if not token:
                    break
        except Exception as e:                      # quota, 5xx, network, bad SDK shape
            raise STSError(f"ElevenLabs voice list failed: {e}") from e
        return out


def _get(obj, key, default=None):
    """A field access that helps handles the data whether the SDK returns objects or dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _shape_voice(v) -> dict:
    """Converts ElevenLabs voice object into a format that our pipeline can use."""
    langs: list[str] = []
    for vl in _get(v, "verified_languages") or []:
        lang = _get(vl, "language")
        if lang and lang not in langs:
            langs.append(lang)
    if not langs:
        lab_lang = _get(_get(v, "labels") or {}, "language")
        if lab_lang:
            langs.append(lab_lang)
    if not langs:
        langs = ["unknown"]
    return {
        "voice_id": _get(v, "voice_id"),
        "name": _get(v, "name"),
        "preview_url": _get(v, "preview_url"),
        "languages": langs,
        "gender": _get(_get(v, "labels") or {}, "gender") or "unknown",
    }