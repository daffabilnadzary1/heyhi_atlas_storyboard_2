"""
app/pipeline/sts_elevenlabs.py

For each speaking scene:
1. Extract Veo's audio.
2. Convert it to the target voice with ElevenLabs STS.
3. Trim to the detected speech end.
4. Replace the original audio.

Unlike the Azure path, audio timing is preserved by STS, so no alignment is
needed. Diarization is only used to generate subtitle timings.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.clients.sts_elevenlabs_client import (
    ElevenLabsSTSClient, STSError, STS_SAMPLE_RATE,
)
from app import costs
from app.utils.ffmpeg_utils import (
    detect_speech_end, extract_audio, get_duration, trim_and_mux,
)

from app.utils.text_utils import split_phrases
from app.pipeline.external_tts import (
    Diarizer, _record_diarizer_usage, mark_scene_done, phrase_spans,
    write_timings_sidecar,
)

def process_scene(
    mp4_path: str | Path,
    voice_id: str,
    run_dir: str | Path,
    scene_id: str,
    sts: ElevenLabsSTSClient,
    text: str,
    diarizer: Diarizer,
) -> Path:
    """Convert a scene with ElevenLabs STS.

    Extracts Veo's audio, converts it to the target voice, generates subtitle
    timings when possible, and writes the final scene to `scenes/<id>.mp4`.

    Only the converted audio is kept.
    """
    run_dir = Path(run_dir)
    tts_dir = run_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)

    src_wav = Path(tempfile.mktemp(suffix=".wav"))
    try:
        extract_audio(mp4_path, src_wav, sample_rate=STS_SAMPLE_RATE)
        # BILLABLE length is the INPUT audio, not the output: ElevenLabs charges
        # for what it converts and the converted track is not separately billed.
        # Measured here because src_wav is deleted in the finally below, and it is
        # the full ~8s Veo clip — Veo's trailing silence is paid for even though
        # the trim later discards it.
        billed_s = get_duration(src_wav)
        converted = sts.convert(src_wav, voice_id)
        costs.record(run_dir, layer="L6", provider="elevenlabs",
                     model=getattr(sts, "model_id", "eleven_multilingual_sts_v2"),
                     unit="second", quantity=billed_s, measured=True,
                     scene_id=scene_id)
    finally:
        src_wav.unlink(missing_ok=True)

    track = tts_dir / f"{scene_id}_track.wav"
    track.write_bytes(converted)

    # Veo is asked for a fixed 8s; the character usually stops speaking earlier.
    # STS preserves that trailing silence, so trim where speech actually ends —
    # the same contract the Azure path gets from its last-TTS-end calculation.
    end_ms = detect_speech_end(track)
    if end_ms <= 0:
        raise STSError(f"scene '{scene_id}': converted audio contains no speech")

    phrases = split_phrases(text)
    if phrases:
        timings = diarizer.diarize(track)                  # converted track = what is heard
        _record_diarizer_usage(diarizer, run_dir, scene_id)
        starts_ms, durs_ms, matched = phrase_spans(
            phrases, timings, speech_end_ms=end_ms)
        if matched:
            write_timings_sidecar(tts_dir, scene_id, phrases, starts_ms, durs_ms)

    scenes_dir = run_dir / "scenes"
    dest = scenes_dir / f"{scene_id}.mp4"
    tmp = scenes_dir / f"{scene_id}_l6.mp4"
    trim_and_mux(mp4_path, track, tmp, end_ms / 1000.0)
    os.replace(tmp, dest)
    mark_scene_done(run_dir, scene_id)     # last, so it only exists if dest does
    return dest