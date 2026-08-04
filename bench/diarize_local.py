"""
Erase this file later, this is to test the accuracy of diarization for the time being

bench/diarize_local.py — test transcription + word-timing accuracy on a LOCAL
video, no budget approval needed.

Default engine = whisper (self-hosted faster-whisper: FREE, no credits, no key).
Gemini engine is optional and DOES cost credits + a key.

Setup (whisper, free):
  pip install faster-whisper

Run:
  # free, local:
  python -m bench.diarize_local --video /path/clip.mp4
  # bigger/more accurate whisper model:
  python -m bench.diarize_local --video /path/clip.mp4 --whisper-model small
  # quantify accuracy vs the known script (word error rate):
  python -m bench.diarize_local --video /path/clip.mp4 --expected "the exact words spoken"
  # compare against Gemini (needs HEYHI_GEMINI_API_KEY + credits):
  python -m bench.diarize_local --video /path/clip.mp4 --engine gemini

Prints each word with start/end ms, total words, and — if --expected is given —
a word error rate and the aligned diff, so you can judge accuracy before
committing budget to the Gemini path.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def build_diarizer(engine: str, whisper_model: str):
    if engine == "whisper":
        from app.pipeline.external_tts import WhisperDiarizer
        return WhisperDiarizer(model_size=whisper_model)
    if engine == "gemini":
        from app.config import make_client
        from app.pipeline.external_tts import GeminiDiarizer
        return GeminiDiarizer(make_client())
    raise SystemExit(f"unknown engine '{engine}'")


def wer(reference: str, hypothesis: str) -> tuple[float, int, int, int]:
    """Word error rate via Levenshtein over word tokens.
    Returns (wer, substitutions, deletions, insertions)."""
    r = reference.lower().split()
    h = hypothesis.lower().split()
    n, m = len(r), len(h)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    # backtrack for S/D/I counts
    i, j, s, dele, ins = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (r[i - 1] != h[j - 1]):
            s += r[i - 1] != h[j - 1]; i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dele += 1; i -= 1
        else:
            ins += 1; j -= 1
    return ((s + dele + ins) / max(n, 1)), s, dele, ins


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Local diarization accuracy test")
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--engine", choices=["whisper", "gemini"], default="whisper",
                    help="whisper = free/local (default); gemini = credits+key")
    ap.add_argument("--whisper-model", default="base",
                    help="tiny|base|small|medium|large-v3 (bigger = slower, more accurate)")
    ap.add_argument("--expected", default=None, help="known transcript -> prints WER")
    a = ap.parse_args(argv)

    if not a.video.is_file():
        raise SystemExit(f"video not found: {a.video}")

    diarizer = build_diarizer(a.engine, a.whisper_model)
    print(f"# engine={a.engine}  video={a.video.name}")
    words = diarizer.diarize(a.video)

    print(f"# {len(words)} words with timings:")
    for w in words:
        print(f"  [{w['start_ms']:>6} - {w['end_ms']:>6} ms]  {w['word']}")

    transcript = " ".join(w["word"] for w in words)
    print("\n# transcript:")
    print(f"  {transcript}")

    if a.expected:
        rate, s, dele, ins = wer(a.expected, transcript)
        print(f"\n# WER vs --expected: {rate:.1%}  (S={s} D={dele} I={ins}, ref_words={len(a.expected.split())})")
        print("  (D5T1 success bar is ~90% word accuracy => WER <= 10%)")

    # rough timing sanity: monotonic non-overlapping starts
    starts = [w["start_ms"] for w in words]
    nonmono = sum(1 for x, y in zip(starts, starts[1:]) if y < x)
    print(f"\n# timing sanity: {nonmono} out-of-order word starts "
          f"({'OK' if nonmono == 0 else 'check drift'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())