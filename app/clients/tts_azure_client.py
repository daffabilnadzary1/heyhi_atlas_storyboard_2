"""
app/clients/tts_azure_client.py

This file is the bridge between Azure TTS and our pipeline
"""
from __future__ import annotations

import os
from typing import Protocol


class TTSClient(Protocol):
    def tts(self, text: str, voice_name: str) -> bytes: ...


class TTSError(RuntimeError):
    pass


class AzureTTSClient:
    """Azure Cognitive Services Speech -> 24kHz mono PCM WAV bytes."""

    def __init__(self, key: str | None = None, region: str | None = None):
        self.key = key or os.environ.get("HEYHI_AZURE_SPEECH_KEY")
        self.region = region or os.environ.get("HEYHI_AZURE_SPEECH_REGION")
        if not self.key or not self.region:
            raise TTSError("AZURE_SPEECH_KEY / AZURE_SPEECH_REGION not set")

    def tts(self, text: str, voice_name: str) -> bytes:
        import azure.cognitiveservices.speech as speechsdk

        cfg = speechsdk.SpeechConfig(subscription=self.key, region=self.region)
        cfg.speech_synthesis_voice_name = voice_name
        cfg.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm
        )
        synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        result = synth.speak_text_async(text).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            raise TTSError(f"Azure TTS failed for voice '{voice_name}': {result.reason}")
        return bytes(result.audio_data)