"""
app/pipeline/video_providers.py

Layer 5 video provider registry.

Maps a provider name to a VeoClient builder so the pipeline can select a video
backend without provider-specific branching.

Add a new provider by implementing VeoClient and registering it in
VIDEO_PROVIDERS.
"""
from __future__ import annotations

from typing import Callable

from app.clients.video_veo_client import GeminiVeoClient, VeoClient
from app.clients.video_kieai_client import KieAiVeoClient


def _build_gemini(gemini) -> VeoClient:
    return GeminiVeoClient(gemini)


def _build_kieai(gemini) -> VeoClient:      # gemini arg unused: kie reads KIE_API_KEY
    return KieAiVeoClient()


VIDEO_PROVIDERS: dict[str, Callable[[object], VeoClient]] = {
    "gemini": _build_gemini,
    "kieai": _build_kieai,
}