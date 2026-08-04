"""
Seams and registries — does a request flag actually reach the object it configures?

These are cheap tests for an expensive failure mode. A flag that is accepted by
the API, documented, and then silently dropped on the way to the client looks
exactly like a flag that works, and the only way you find out is a bill or a
batch of bad output. Each test here follows one value from the request body to
the thing that consumes it.

Covers open-questions #16 (WhisperDiarizer was unreachable) and #25 (use_schema
was off and unreachable).
"""
from __future__ import annotations

import pytest

from app.pipeline.audio_providers import DIARIZERS, PROVIDERS
from app.pipeline.director import GeminiDirector
from app.pipeline.external_tts import GeminiDiarizer, WhisperDiarizer
from app.schemas import DirectIn, ScenesIn, VideoBlueprint


# ---------------------------------------------------------------- #25 schema
def test_use_schema_is_on_by_default():
    """Changed 2026-08-02. If this flips back, open-questions #25 should say why."""
    assert GeminiDirector(client=None).use_schema is True
    assert DirectIn(run_id="run_abcdef12").use_schema is True


def test_the_blueprint_model_converts_to_a_gemini_response_schema():
    """The whole feature rests on google-genai being able to render
    VideoBlueprint as a response schema. It is a nested model with enums,
    optionals and a list of lists — none of that is guaranteed to survive, and
    an SDK upgrade could break it. Fails loudly here rather than mid-run."""
    types = pytest.importorskip("google.genai").types
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=VideoBlueprint)
    assert cfg.response_schema is not None


def test_director_passes_the_schema_only_when_asked():
    """Pins the plumbing without a network call: a fake client captures the
    config object the director built."""
    captured = {}

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            captured["schema"] = getattr(config, "response_schema", None)
            class R:
                text = "{}"
                usage_metadata = None
            return R()

    class FakeClient:
        models = FakeModels()

    GeminiDirector(FakeClient(), use_schema=False).complete("sys", "user")
    assert captured["schema"] is None

    GeminiDirector(FakeClient(), use_schema=True).complete("sys", "user")
    assert captured["schema"] is VideoBlueprint


# ---------------------------------------------------------------- #16 diarizer
def test_both_diarizers_are_reachable_by_name():
    """The bug this pins: WhisperDiarizer existed as a class and nothing could
    construct it, because both audio builders hard-coded GeminiDiarizer."""
    assert set(DIARIZERS) == {"gemini", "whisper"}
    assert isinstance(DIARIZERS["gemini"](object()), GeminiDiarizer)
    assert isinstance(DIARIZERS["whisper"](object()), WhisperDiarizer)


def test_whisper_construction_costs_nothing():
    """Model loading is deferred to the first diarize() call, so selecting
    whisper does not download anything until a scene actually needs it — which
    is what keeps this test free of the faster-whisper dependency."""
    d = DIARIZERS["whisper"](object())
    assert d._model is None


@pytest.mark.parametrize("provider", ["azure", "elevenlabs"])
def test_an_injected_diarizer_is_the_one_the_provider_uses(provider, monkeypatch):
    """Both audio paths must honour the choice — Azure uses the timings to place
    audio, ElevenLabs to time subtitles, and the endpoint sets it once."""
    monkeypatch.setattr("app.pipeline.audio_providers.AzureTTSClient",
                        lambda *a, **k: object())
    monkeypatch.setattr("app.pipeline.audio_providers.ElevenLabsSTSClient",
                        lambda *a, **k: object())
    sentinel = object()
    built = PROVIDERS[provider](object(), diarizer=sentinel)
    assert built.diarizer is sentinel


@pytest.mark.parametrize("provider", ["azure", "elevenlabs"])
def test_omitting_the_diarizer_still_defaults_to_gemini(provider, monkeypatch):
    """Back-compat: callers that pass only the Gemini client keep working."""
    monkeypatch.setattr("app.pipeline.audio_providers.AzureTTSClient",
                        lambda *a, **k: object())
    monkeypatch.setattr("app.pipeline.audio_providers.ElevenLabsSTSClient",
                        lambda *a, **k: object())
    assert isinstance(PROVIDERS[provider](object()).diarizer, GeminiDiarizer)


def test_scenes_request_defaults_to_gemini_diarization():
    """Opt-in, not a silent switch — whisper needs an optional dependency that
    may not be installed."""
    assert ScenesIn(run_id="run_abcdef12").diarizer == "gemini"


def test_an_unknown_diarizer_is_rejected_by_the_schema():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ScenesIn(run_id="run_abcdef12", diarizer="whispr")
