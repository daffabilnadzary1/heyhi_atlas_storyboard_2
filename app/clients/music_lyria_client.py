"""
app/clients/music_lyria_client.py

Act as a thin layer between pipeline and Lyria
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.utils.retry import (
    RetriesExhausted, backoff_from_env, looks_transient, retry_call,
)


# ---------------------------------------------------------------- errors
class MusicError(RuntimeError):
    pass


class TransientMusicError(MusicError):
    """Retryable: 5xx, rate-limit, timeout."""


# ---------------------------------------------------------------- job spec
@dataclass
class MusicJobSpec:
    mood: str                        # bp.music_style, verbatim
    instrumental: bool = True
    duration_s: float | None = None  # Lyria fixes ~30s, removing is a breaking API change, keep it for now


class MusicClient(Protocol):
    # Returns raw audio bytes; container (wav/pcm) declared by `.audio_mime`.
    def generate_music(self, spec: MusicJobSpec) -> bytes: ...

class MusicFilteredError(MusicError):
    """Represent an error when the model returned no audio (safety / finish_reason)."""


# ---------------------------------------------------------------- reliability knobs
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_S = 2.0

# Lyria's rate lives in app/costs.py PRICING, with every other provider's.

def retry_backoff_from_env() -> float:
    return backoff_from_env("ATLAS_LYRIA_BACKOFF", DEFAULT_RETRY_BACKOFF_S)


def generate_with_retry(
    client: MusicClient,
    spec: MusicJobSpec,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_s: float = DEFAULT_RETRY_BACKOFF_S,
) -> tuple[bytes, int]:
    """Return (audio_bytes, attempts). Retries ONLY TransientMusicError.
    Here max_retries is the TOTAL attempt count (historical meaning)."""
    try:
        return retry_call(lambda: client.generate_music(spec), attempts=max_retries,
                          exc_type=TransientMusicError, backoff_s=backoff_s)
    except RetriesExhausted as ex:
        raise MusicError(f"Lyria failed after {max_retries} attempts: {ex.last}")

def build_bed_prompt(mood: str, instrumental: bool = True) -> str:
    """Prompt construction is extracted to its own function so to test and check
    the prompt, we can do it without needing to call lyria, its not buried inside
    the API call."""
    parts = [f"A background music bed. Mood: {mood}."]
    if instrumental:
        parts.append("Instrumental only — no vocals, no lyrics, no spoken words.")
    parts.append("Seamless, loopable, suitable as a quiet bed under narration.")
    return " ".join(parts)


# ---------------------------------------------------------------- Gemini/Lyria
class GeminiLyriaClient:
    """generate_content(model, contents=prompt) -> inline audio bytes.

    Convert MusicJobSpec into prompt -> Calls the gemini model
    -> Extract returned audio bytes -> convert API errors into specific exceptions.
    """

    def __init__(self, client, model: str = "lyria-3-clip-preview"):
        self.client = client
        self.model = model

    def generate_music(self, spec: MusicJobSpec) -> bytes:
        prompt = build_bed_prompt(spec.mood, spec.instrumental)
        try:
            resp = self.client.models.generate_content(model=self.model, contents=prompt)
        except Exception as e:                         # classify transient
            if looks_transient(e):
                raise TransientMusicError(str(e)) from e
            raise MusicError(str(e)) from e
        cand = resp.candidates[0]
        for part in cand.content.parts:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return bytes(inline.data)              # real container (e.g. mp3)

        reason = getattr(cand, "finish_reason", "unknown")
        raise MusicFilteredError(f"Lyria returned no audio (finish_reason={reason})")
