"""
app/pipeline/external_tts.py — Layer 6 (Azure TTS overlay).

Layer 6: Azure TTS pipeline.

For each speaking scene:
1. Split text into phrases.
2. Generate Azure TTS for each phrase.
3. Diarize Veo's original audio to obtain word timings.
4. Align each TTS phrase to the matching spoken words.
5. Replace Veo audio with the aligned TTS track and trim the video.

If diarization is unreliable, alignment falls back to sequential phrase
placement. Lip-sync becomes less accurate, but the pipeline still completes.

TTS and diarization are injected via Protocols for easy testing without network
calls. FFmpeg operations live in ffmpeg_utils.

The ElevenLabs path (sts_elevenlabs.py) sidesteps the whole problem by
converting Veo's audio into the target voice instead of re-synthesising it,
which preserves the original timing for free. It is the default for that reason.
This module is still the Azure path and still the one to read to understand what
the timings sidecar contains.
"""
from __future__ import annotations

import difflib
import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from app import costs
from app.utils.ffmpeg_utils import build_tts_track, extract_audio, get_duration, trim_and_mux, trim_silence, detect_speech_end
from app.utils.text_utils import parse_json_lenient, split_phrases
from app.clients.tts_azure_client import TTSClient


class Diarizer(Protocol):
    def diarize(self, mp4_path: str | Path) -> list[dict]:
        """Return [{'word': str, 'start_ms': int, 'end_ms': int}, ...]."""
        ...

# A custom error to let us know if the error came from layer 6
class L6Error(RuntimeError):
    pass

def _norm(w: str) -> str:
    """Normalize a word for matching.

    Lowercases and removes non-alphanumeric characters so punctuation and casing
    do not affect alignment. Empty results are ignored by callers.
    """
    return "".join(ch for ch in w.lower() if ch.isalnum())


def _norm_phrases(phrases: list[str]) -> list[list[str]]:
    """Phrases -> normalised word lists, empties dropped (see _norm)."""
    return [[n for n in (_norm(w) for w in p.split()) if n] for p in phrases]


def _norm_timings(word_timings: list[dict]) -> tuple[list[str], list[int], list[int]]:
    """Normalize diarized words.

    Returns parallel lists of words, start times, and end times with empty tokens
    removed while preserving index alignment.
    """
    words: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for t in word_timings:
        n = _norm(t.get("word", ""))
        if not n:
            continue
        s = int(t.get("start_ms", 0))
        words.append(n)
        starts.append(s)
        ends.append(int(t.get("end_ms", s)))
    return words, starts, ends


def _nearest_matched(tts_to_dia: dict[int, int], idx: int, n: int) -> int | None:
    """Matched diarized index for tts word `idx`, else nearest matched neighbour
    (prefer forward)."""
    if idx in tts_to_dia:
        return tts_to_dia[idx]
    for delta in range(1, n + 1):
        f = idx + delta
        if f < n and f in tts_to_dia:
            return tts_to_dia[f]
        b = idx - delta
        if b >= 0 and b in tts_to_dia:
            return tts_to_dia[b]
    return None

def _match_tts_to_dia(tts_words: list[str], dia_words: list[str]) -> dict[int, int]:
    """Map TTS word indices to diarized word indices using difflib."""
    sm = difflib.SequenceMatcher(a=tts_words, b=dia_words, autojunk=False)
    out: dict[int, int] = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            out[blk.a + k] = blk.b + k
    return out

# Given the TTS phrases and the word timings, determine when each phrase should begin.
def align_starts(
    phrases: list[str], word_timings: list[dict], durations_ms: list[int], sync_offset_ms: int = 0, floor_ms: int = 0
) -> tuple[list[int], bool]:
    """Compute the start time of each TTS phrase.

    Phrases are aligned by matching their normalized words against the diarized
    transcript. This is resilient to inserted or missing words because matching is
    based on content rather than position.

    If fewer than half the words match, alignment falls back to sequential phrase
    placement.

    Returns:
        (starts_ms, used_diarization)
    """
    phrase_words = _norm_phrases(phrases)
    tts_words = [w for pw in phrase_words for w in pw]
    phrase_first_idx, acc = [], 0
    for pw in phrase_words:
        phrase_first_idx.append(acc)
        acc += max(len(pw), 1)

    dia_words, dia_starts, _ = _norm_timings(word_timings)

    if tts_words and dia_words:
        tts_to_dia = _match_tts_to_dia(tts_words, dia_words)
        # accept only if a solid fraction of words matched
        if len(tts_to_dia) >= max(1, int(0.5 * len(tts_words))):
            starts, prev = [], 0
            for first in phrase_first_idx:
                di = _nearest_matched(tts_to_dia, first, len(tts_words))
                s = dia_starts[di] if di is not None else prev
                s = max(int(s) + sync_offset_ms, floor_ms)   # never before real onset
                starts.append(s); prev = s
            return starts, True
    # fallback also respects the onset instead of starting at 0
    starts, t = [], max(sync_offset_ms, floor_ms)
    for d in durations_ms:
        starts.append(int(t)); t += d
    return starts, False

# subtitle timing for an externally-timed (STS) track:
def phrase_spans(
    phrases: list[str], word_timings: list[dict], floor_ms: int = 0,
    speech_end_ms: int | None = None,
) -> tuple[list[int], list[int], bool]:
    """Return subtitle timing for each phrase.

    Phrase spans are derived from the matching diarized words. If the transcript is
    too sparse to trust, returns matched=False so the renderer can fall back to a
    single scene caption.

    The final caption is extended to the detected speech end when provided.
    """
    phrase_words = _norm_phrases(phrases)
    tts_words = [w for pw in phrase_words for w in pw]
    bounds, acc = [], 0
    for pw in phrase_words:
        n = max(len(pw), 1)
        bounds.append((acc, acc + n - 1)); acc += n

    dia_words, dia_starts, dia_ends = _norm_timings(word_timings)
    if not (tts_words and dia_words):
        return [], [], False

    tts_to_dia = _match_tts_to_dia(tts_words, dia_words)
    if len(tts_to_dia) < max(1, int(0.5 * len(tts_words))):
        return [], [], False

    starts, durs, n = [], [], len(tts_words)
    for first, last in bounds:
        ds = _nearest_matched(tts_to_dia, first, n)
        de = _nearest_matched(tts_to_dia, last, n)
        s = max(dia_starts[ds] if ds is not None else 0, floor_ms)
        e = dia_ends[de] if de is not None else s
        if e <= s:
            e = s + 1
        starts.append(int(s)); durs.append(int(e - s))

    # HOLD THE LAST CAPTION TO THE END OF SPEECH.
    # `speech_end_ms` is the same value the caller trims the video to, so this can
    # never run past the clip.
    if speech_end_ms and starts:
        last_end = starts[-1] + durs[-1]
        if speech_end_ms > last_end:
            durs[-1] = int(speech_end_ms - starts[-1])

    return starts, durs, True

def write_timings_sidecar(tts_dir: Path, scene_id: str, phrases: list[str],
                          starts_ms: list[int], durs_ms: list[int]) -> Path:
    """Persist per-phrase timings next to the TTS wavs. build_srt reads
    this to place per-phrase subtitle cues; without it the renderer layer falls back 
    to one whole-scene caption."""
    p = tts_dir / f"{scene_id}_timings.json"
    p.write_text(
        json.dumps({"phrases": phrases, "starts_ms": starts_ms, "durs_ms": durs_ms},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return p


def mark_scene_done(run_dir: Path, scene_id: str) -> Path:
    """Create the L6 completion marker for a scene.

    Written only after the final processed video has been successfully produced.
    """
    d = run_dir / "tts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{scene_id}.done"
    p.write_text("", encoding="utf-8")
    return p


def scene_is_done(run_dir: Path, scene_id: str) -> bool:
    """True when the sts layer finished this scene AND its output is still on disk.
    """
    return ((run_dir / "tts" / f"{scene_id}.done").is_file()
            and (run_dir / "scenes" / f"{scene_id}.mp4").is_file())


def _record_diarizer_usage(diarizer, run_dir: Path, scene_id: str) -> None:
    """Record diarizer token usage if the implementation exposes it."""
    log = getattr(diarizer, "usage_log", None)
    if log:
        costs.record_tokens(run_dir, layer="L6",
                            model=getattr(diarizer, "model", "gemini-2.5-flash"),
                            usage=log[-1], scene_id=scene_id, purpose="diarization")


def process_scene(
    mp4_path: str | Path,
    text: str,
    voice_name: str,
    run_dir: str | Path,
    scene_id: str,
    tts: TTSClient,
    diarizer: Diarizer,
    sync_offset_ms: int = 0,
) -> Path:
    """Generate and align Azure TTS for a scene.

    Creates phrase-level TTS, aligns it to Veo's word timings, replaces the native
    audio, trims the video to the narration length, and writes subtitle timing
    metadata.

    Returns the processed scene path.
    """
    run_dir = Path(run_dir)
    # Split on commas TOO, explicitly — this is the one path where it still pays.
    # Azure re-synthesises each phrase as its own clip and places it at its own
    # diarized timestamp, so finer phrases mean tighter lip-sync. The ElevenLabs
    # path takes the default (sentences only), because it places no audio and
    # phrases only drive subtitles.
    phrases = split_phrases(text, split_on_comma=True)
    if not phrases:
        raise L6Error(f"scene '{scene_id}': empty text for video-with-audio")

    tts_dir = run_dir / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    wavs: list[Path] = []
    durs_ms: list[int] = []
    # Run the TTS for each phrase while measuring duration
    for i, phrase in enumerate(phrases):
        w = tts_dir / f"{scene_id}_{i}.wav"
        w.write_bytes(tts.tts(phrase, voice_name))
        # BILLABLE length is measured HERE, before trimming: Azure charged for
        # what it synthesised, including the silence we are about to discard.
        # Measured in place — no second file is kept, only the number.
        billed_s = get_duration(w)
        costs.record(run_dir, layer="L6", provider="azure", model="azure-tts",
                     unit="second", quantity=billed_s, measured=True,
                     scene_id=scene_id, phrase_index=i)
        # Azure pads each synthesis with leading/trailing silence. Left in, that
        # padding would push every phrase later than its diarized start and
        # inflate the measured duration used to place the NEXT phrase, so it has
        # to go before the PLACEMENT duration is measured. Order matters here.
        trim_silence(w)                                 # strip lead/trail silence
        wavs.append(w)
        # PLACEMENT length — post-trim, drives alignment and the final trim.
        # Deliberately a different number from billed_s above.
        durs_ms.append(int(round(get_duration(w) * 1000)))

    # Calls the diarizer function to get the timings
    timings = diarizer.diarize(mp4_path)
    _record_diarizer_usage(diarizer, run_dir, scene_id)
    onset_ms = detect_speech_end(mp4_path)
    starts_ms, used = align_starts(phrases, timings, durs_ms, sync_offset_ms, floor_ms=onset_ms)

    # Build the audio track and combine them as one
    track = tts_dir / f"{scene_id}_track.wav"
    build_tts_track(list(zip(wavs, starts_ms)), track)

    # Find the last end time
    last_end_ms = max(s + d for s, d in zip(starts_ms, durs_ms))
    write_timings_sidecar(tts_dir, scene_id, phrases, starts_ms, durs_ms)

    scenes_dir = run_dir / "scenes"
    dest = scenes_dir / f"{scene_id}.mp4"
    tmp = scenes_dir / f"{scene_id}_l6.mp4"
    trim_and_mux(mp4_path, track, tmp, last_end_ms / 1000.0) # Mute audio, insert TTS, trim the video
    os.replace(tmp, dest)
    mark_scene_done(run_dir, scene_id)     # last, so it only exists if dest does
    return dest


# ---------------------------------------------------------------- diarizers
class GeminiDiarizer:
    """Gemini-based diarizer.

    Extracts per-word timestamps from audio using Gemini. Token usage is stored in
    usage_log so callers can record costs.
    """

    _PROMPT = (
        "Transcribe the spoken words in this audio. Return ONLY a JSON array; "
        "each element is {\"word\": <string>, \"start_ms\": <int>, \"end_ms\": "
        "<int>} with each word's start and end time in milliseconds from the "
        "start of the audio. No prose, no markdown fences."
    )

    def __init__(self, client, model: str = "gemini-2.5-flash"):
        self.client = client
        self.model = model
        # Token counts per diarize() call, drained by whichever path (Azure/Elevenlabs) called
        # it. Same side-channel pattern as GeminiDirector — the Diarizer Protocol
        # is `diarize(path) -> list[dict]` and has no run_dir to write to.
        # NOTE both audio paths diarize once per speaking scene: Azure needs the
        # timings to place audio, ElevenLabs needs them only for subtitles.
        self.usage_log: list[dict] = []

    # Formats the return output of Gemini
    @staticmethod
    def _parse_word_timings(text: str) -> list[dict]:
        data = parse_json_lenient(text)
        out: list[dict] = []
        for e in data:
            word = str(e.get("word", "")).strip()
            if "start_ms" in e:                       # preferred form
                s = int(e["start_ms"]); en = int(e.get("end_ms", s))
            else:                                     # tolerate seconds form
                s = int(float(e.get("start", 0)) * 1000)
                en = int(float(e.get("end", e.get("start", 0))) * 1000)
            out.append({"word": word, "start_ms": s, "end_ms": en})
        return out

    def diarize(self, mp4_path: str | Path) -> list[dict]:
        from google.genai import types          # lazy: keeps the API bootable without the SDK
        wav = Path(tempfile.mktemp(suffix=".wav"))
        extract_audio(mp4_path, wav)
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=[self._PROMPT,
                          types.Part.from_bytes(data=wav.read_bytes(), mime_type="audio/wav")],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.0),
            )
        finally:
            wav.unlink(missing_ok=True)
        self.usage_log.append(costs.usage_from_response(resp))
        return self._parse_word_timings(resp.text)


class WhisperDiarizer:
    """Local faster-whisper diarizer.

    Provides more accurate word timings than Gemini at the cost of loading a local
    Whisper model.
    """

    def __init__(self, model_size: str = "base", device: str = "cpu"):
        self.model_size, self.device = model_size, device
        self._model = None

    def diarize(self, mp4_path: str | Path) -> list[dict]:
        from faster_whisper import WhisperModel
        if self._model is None:
            self._model = WhisperModel(self.model_size, device=self.device)
        segments, _ = self._model.transcribe(str(mp4_path), word_timestamps=True)
        out: list[dict] = []
        for seg in segments:
            for w in (seg.words or []):
                out.append({"word": w.word.strip(),
                            "start_ms": int(w.start * 1000),
                            "end_ms": int(w.end * 1000)})
        return out