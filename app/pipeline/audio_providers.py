"""
app/pipeline/audio_providers.py

Layer 6 audio provider dispatch.

This module hides the differences between audio providers (currently Azure and
ElevenLabs) behind a common interface. The rest of the pipeline simply selects a
provider by name and calls `process()`—it never needs provider-specific `if`
statements.

To add a new provider:
1. Implement a class that follows the `SceneAudioProvider` interface.
2. Add a builder function.
3. Register it in `PROVIDERS`.

Each provider also declares a `voice_field`, which tells the pipeline which
attribute of an `AudioEntry` contains that provider's voice identifier. This is
necessary because Azure and ElevenLabs use different voice ID formats.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from app.clients.tts_azure_client import AzureTTSClient
from app.clients.sts_elevenlabs_client import ElevenLabsSTSClient
from app.pipeline.external_tts import GeminiDiarizer, WhisperDiarizer
from app.pipeline import external_tts, sts_elevenlabs


class SceneAudioProvider(Protocol):
    voice_field: str
    def process(self, raw_mp4: Path, scene: dict, voice: str,
                run_dir: Path) -> Path: ...


class AzureSceneAudio:
    """
    Adapter around the existing Azure Layer 6 implementation.

    This class doesn't contain Azure TTS logic itself—it simply translates the
    common `SceneAudioProvider.process()` interface into the argument list
    expected by `external_tts.process_scene()`.
    """
    voice_field = "voice_name"

    def __init__(self, tts, diarizer, sync_offset_ms: int = 0):
        self.tts, self.diarizer = tts, diarizer
        self.sync_offset_ms = sync_offset_ms

    def process(self, raw_mp4: Path, scene: dict, voice: str, run_dir: Path) -> Path:
        return external_tts.process_scene(
            raw_mp4, scene["text"], voice, run_dir, scene["id"],
            self.tts, self.diarizer, self.sync_offset_ms,
        )


class ElevenLabsSceneAudio:
    voice_field = "voice_id_elevenlabs"

    def __init__(self, sts, diarizer):
        self.sts = sts
        self.diarizer = diarizer

    def process(self, raw_mp4: Path, scene: dict, voice: str, run_dir: Path) -> Path:
        return sts_elevenlabs.process_scene(
            raw_mp4, voice, run_dir, scene["id"], self.sts,
            scene["text"], self.diarizer,
        )


# ---------------------------------------------------------------- diarizers
# Available diarizers.
#
# Gemini
#   - Uses the Gemini API.
#   - One billed Gemini request per speaking scene.
#   - Works with both Azure and ElevenLabs.
#
# Whisper
#   - Uses faster-whisper locally (no API key or usage cost).
#   - Requires `pip install faster-whisper`.
#   - Downloads the model on first use, so the first scene is slower.
DIARIZERS: dict[str, Callable[[object], object]] = {
    "gemini": lambda gemini: GeminiDiarizer(gemini),
    "whisper": lambda gemini: WhisperDiarizer(),
}

"""
Build an Azure audio provider.

`diarizer` is optional. If none is provided, a Gemini-based diarizer is created
automatically. Making it optional keeps existing callers and tests compatible,
since older code only passed the Gemini client.
"""
def _build_azure(gemini, diarizer=None) -> SceneAudioProvider:
    return AzureSceneAudio(AzureTTSClient(), diarizer or GeminiDiarizer(gemini))


def _build_elevenlabs(gemini, diarizer=None) -> SceneAudioProvider:
    return ElevenLabsSceneAudio(ElevenLabsSTSClient(), diarizer or GeminiDiarizer(gemini))


PROVIDERS: dict[str, Callable[..., SceneAudioProvider]] = {
    "azure": _build_azure,
    "elevenlabs": _build_elevenlabs,
}


def resolve_voices(blueprint: dict, voice_source: str, audio: SceneAudioProvider,
                   entries=None, provider_name: str = "",
                   ) -> tuple[Callable[[dict], str], list[str]]:
    """
    Resolve the voice ID for each speaking scene, regardless of the audio provider.

    For `voice_source="index"`, `audio_id` is looked up in the audio library and
    translated into the provider's voice ID using `audio.voice_field`.

    For `voice_source="elevenlabs"`, `audio_id` is already the ElevenLabs voice ID,
    so no lookup is needed.

    Returns `(voice_for, problems)`. If `problems` is not empty, the caller should
    stop before generating audio.
    """
    speaking = [sc for sc in blueprint.get("scenes", [])
                if sc.get("type") == "video-with-audio"]

    if voice_source == "elevenlabs":
        # audio_id already IS the voice_id — no index lookup, no translation
        # layer (Change 2). Bad ids surface as the ElevenLabs 422 downstream.
        problems = [f"scene '{sc.get('id')}': video-with-audio has no audio mapping"
                    for sc in speaking if not (sc.get("audios") or [])]

        def voice_for(scene: dict) -> str:
            return scene["audios"][0]["audio_id"]

        return voice_for, problems

    # index path: audio_id -> the provider's voice field on the library entry
    voice_by_audio = {e.audio_id: getattr(e, audio.voice_field) for e in (entries or [])}
    problems: list[str] = []
    for sc in speaking:
        audios = sc.get("audios") or []
        if not audios:
            problems.append(f"scene '{sc.get('id')}': video-with-audio has no audio mapping")
            continue
        aid = audios[0]["audio_id"]
        if aid not in voice_by_audio:
            problems.append(f"scene '{sc.get('id')}': audio_id '{aid}' not in audio library")
        elif not voice_by_audio[aid]:
            problems.append(
                f"scene '{sc.get('id')}': audio_id '{aid}' has no "
                f"'{audio.voice_field}' for provider '{provider_name}'"
            )

    def voice_for(scene: dict) -> str:
        return voice_by_audio[scene["audios"][0]["audio_id"]]

    return voice_for, problems