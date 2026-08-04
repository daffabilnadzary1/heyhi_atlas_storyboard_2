"""
L6 timing maths — align_starts, phrase_spans, split_phrases.

The subtlest logic in the repo, and the most likely to regress silently: a bad
alignment does not raise, it just produces a video where the voice does not
match the lips. Nobody notices until they watch it.

The vocabulary: TTS words are what we synthesised, diarized words are what an
LLM heard in Veo's native audio. Alignment matches the two streams by CONTENT
(difflib) so a transcription miss stays local instead of shifting everything
after it.
"""
from __future__ import annotations

import pytest

from app.pipeline.external_tts import align_starts, phrase_spans
from app.utils.text_utils import split_phrases

PHRASES = ["Hello there.", "How are you?"]

# hello there | how are you — evenly spaced, everything matches
PERFECT = [
    {"word": "Hello",  "start_ms": 0,    "end_ms": 400},
    {"word": "there.", "start_ms": 500,  "end_ms": 900},
    {"word": "How",    "start_ms": 1000, "end_ms": 1400},
    {"word": "are",    "start_ms": 1500, "end_ms": 1900},
    {"word": "you?",   "start_ms": 2000, "end_ms": 2400},
]
DURS = [900, 1400]


# ---------------------------------------------------------------- split_phrases
def test_splits_on_sentence_punctuation_and_commas():
    assert split_phrases("Hello there. How are you?") == ["Hello there.", "How are you?"]


def test_commas_do_not_split_by_default():
    """DEFAULT CHANGED 2026-08-03 (open-questions #29). Comma splitting existed
    for the Azure path, where each phrase is re-synthesised and placed at its own
    diarized timestamp. ElevenLabs places no audio, so on the default path
    phrases only time subtitles — and splitting a comma-heavy list gave 8
    captions in 8 seconds."""
    assert split_phrases("First, second.") == ["First, second."]


def test_the_azure_path_can_still_split_on_commas():
    """external_tts passes split_on_comma=True explicitly, because there the
    finer granularity buys real lip-sync accuracy. The comma is a split point,
    not part of the phrase — Azure would voice the pause twice."""
    assert split_phrases("First, second.", split_on_comma=True) == ["First", "second."]


@pytest.mark.parametrize("text,expected", [
    ("你好世界。你好吗？", ["你好世界。", "你好吗？"]),
    ("第一。第二！第三？", ["第一。", "第二！", "第三？"]),
])
def test_chinese_sentence_punctuation_splits(text, expected):
    """ADDED 2026-08-03. Chinese uses full-width 。！？ exclusively, which the
    ASCII-only pattern never matched — so a whole Chinese scene came back as one
    phrase and the subtitle sidecar degraded to a single caption per scene."""
    assert split_phrases(text) == expected


def test_chinese_commas_are_split_points_too_when_asked():
    assert split_phrases("第一，第二。", split_on_comma=True) == ["第一", "第二。"]


def test_trailing_fragment_without_punctuation_is_kept():
    assert split_phrases("Done. And then this") == ["Done.", "And then this"]


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_text_yields_no_phrases(text):
    assert split_phrases(text) == []


# ---------------------------------------------------------------- align_starts
def test_perfect_diarization_places_phrases_at_their_first_word():
    starts, used = align_starts(PHRASES, PERFECT, DURS)
    assert used is True
    assert starts == [0, 1000]


def test_alignment_survives_a_dropped_word():
    """REGRESSION GUARD for the positional-alignment bug.

    The original code took the Nth diarized word for the Nth TTS word, so one
    dropped word shifted every later phrase by a word's worth of time and the
    drift compounded across the clip.

    Here diarization misses "there". Positionally, phrase 2 would land on "are"
    (1500ms). Content matching still puts it on "How" (1000ms).
    """
    dropped = [w for w in PERFECT if not w["word"].startswith("there")]
    starts, used = align_starts(PHRASES, dropped, DURS)
    assert used is True
    assert starts == [0, 1000], "a single transcription miss must stay local"


def test_sparse_diarization_falls_back_to_sequential():
    """Below the 50% match threshold the whole alignment is discarded rather
    than trusted partially — phrases play back-to-back. Worse lip-sync, but
    intelligible and still inside the clip."""
    garbage = [{"word": "zzz", "start_ms": 0, "end_ms": 100}]
    starts, used = align_starts(PHRASES, garbage, DURS)
    assert used is False
    assert starts == [0, 900], "sequential placement stacks by duration"


def test_no_diarization_at_all_falls_back():
    starts, used = align_starts(PHRASES, [], DURS)
    assert used is False
    assert starts == [0, 900]


def test_nothing_is_placed_before_the_speech_onset():
    """floor_ms is where Veo's character actually starts moving their mouth.
    Audio before that point means the voice leads the lips."""
    starts, used = align_starts(PHRASES, PERFECT, DURS, floor_ms=700)
    assert used is True
    assert min(starts) >= 700


def test_floor_applies_to_the_fallback_path_too():
    starts, used = align_starts(PHRASES, [], DURS, floor_ms=700)
    assert used is False
    assert starts[0] == 700


def test_sync_offset_shifts_everything():
    base, _ = align_starts(PHRASES, PERFECT, DURS)
    shifted, _ = align_starts(PHRASES, PERFECT, DURS, sync_offset_ms=250)
    assert shifted == [b + 250 for b in base]


def test_out_of_order_diarization_is_preserved_not_clamped():
    """PINS A DELIBERATE DESIGN DECISION (open-questions #12).

    Azure re-synthesises the script as separate phrase clips, and its delivery
    speed does not match the speed Veo animated the mouth at — so the lips for
    phrase N+1 often start before the Azure audio for phrase N has finished.
    Each phrase is pinned to the lips it belongs to, even when that means
    starting before its predecessor ends. Overlapping audio beats audio that
    visibly lags the mouth.

    A monotonic clamp would trade correct lip-sync for tidier numbers. If this
    test starts failing, someone has added one — read open-questions #12 before
    concluding the test is out of date.

    Only the Azure path is affected; ElevenLabs never calls this function.
    """
    backwards = [
        {"word": "Hello",  "start_ms": 5000, "end_ms": 5400},
        {"word": "there.", "start_ms": 5500, "end_ms": 5900},
        {"word": "How",    "start_ms": 100,  "end_ms": 400},
        {"word": "are",    "start_ms": 200,  "end_ms": 500},
        {"word": "you?",   "start_ms": 300,  "end_ms": 600},
    ]
    starts, used = align_starts(PHRASES, backwards, DURS)
    assert used is True
    assert starts == [5000, 100]
    assert starts != sorted(starts), "phrases stay pinned to their own lip timing"


def test_tokens_that_normalise_to_nothing_cannot_match_each_other():
    """_norm maps an emoji or a bare "..." to "", and two empty strings are
    equal — so before they were dropped, a stray punctuation token in the
    transcript could match a stray one in the script and pin a phrase to
    whatever moment that happened to be at. Here the junk sits at 9000ms; if it
    were still in the streams it would drag phrase 2 there."""
    noisy = [
        {"word": "Hello",  "start_ms": 0,    "end_ms": 400},
        {"word": "...",    "start_ms": 9000, "end_ms": 9100},
        {"word": "there.", "start_ms": 500,  "end_ms": 900},
        {"word": "How",    "start_ms": 1000, "end_ms": 1400},
        {"word": "are",    "start_ms": 1500, "end_ms": 1900},
        {"word": "you?",   "start_ms": 2000, "end_ms": 2400},
    ]
    starts, used = align_starts(["Hello ... there.", "How are you?"], noisy, DURS)
    assert used is True
    assert starts == [0, 1000]


@pytest.mark.parametrize("phrase,transcript", [
    ("Привет мир.", ["Привет", "мир."]),                # Cyrillic
    ("مرحبا بالعالم.", ["مرحبا", "بالعالم."]),          # Arabic
    ("Xin chào thế giới.", ["Xin", "chào", "thế", "giới."]),   # Vietnamese
])
def test_non_latin_scripts_with_spaces_align_normally(phrase, transcript):
    """CORRECTS AN EARLIER CLAIM (open-questions #18). isalnum() is true for any
    Unicode letter, so these scripts survive _norm intact and match like any
    other. What actually breaks is a script with no spaces between words — see
    the next test."""
    timings = [{"word": w, "start_ms": 500 * i, "end_ms": 500 * i + 400}
               for i, w in enumerate(transcript)]
    starts, used = align_starts([phrase], timings, [1000])
    assert used is True
    assert starts == [0]


def test_a_script_without_word_spaces_degrades_to_the_fallback():
    """Chinese has no spaces, so split() yields ONE token for the whole
    sentence and it matches none of the per-word transcript. The 50% threshold
    trips and phrases play back-to-back — degraded, not broken, and on the
    ElevenLabs default path the audio is unaffected either way.

    Documents the current limit rather than endorsing it: if CJK output is ever
    commissioned, this is the test that should start failing."""
    timings = [{"word": w, "start_ms": 400 * i, "end_ms": 400 * i + 300}
               for i, w in enumerate(["你好", "世界"])]
    starts, used = align_starts(["你好世界。"], timings, [800])
    assert used is False
    assert starts == [0]


def test_matching_ignores_case_and_punctuation():
    """_norm strips everything non-alphanumeric before comparing, so "Hello,"
    and "hello" are the same word."""
    noisy = [dict(w, word=w["word"].upper() + "!!") for w in PERFECT]
    starts, used = align_starts(PHRASES, noisy, DURS)
    assert used is True
    assert starts == [0, 1000]


# ---------------------------------------------------------------- phrase_spans
def test_phrase_spans_cover_first_to_last_word():
    """The STS path synthesises no individual phrases, so there is no measured
    duration — subtitle spans are read out of diarization instead."""
    starts, durs, matched = phrase_spans(PHRASES, PERFECT)
    assert matched is True
    assert starts == [0, 1000]
    assert durs == [900, 1400]        # first word start -> last word end


def test_phrase_spans_report_no_match_when_sparse():
    """matched=False makes the caller skip the sidecar entirely, and build_srt
    falls back to one caption per scene. Same graceful-degrade contract as
    align_starts."""
    _, _, matched = phrase_spans(PHRASES, [{"word": "zzz", "start_ms": 0, "end_ms": 1}])
    assert matched is False


def test_phrase_spans_with_no_timings():
    assert phrase_spans(PHRASES, []) == ([], [], False)


def test_phrase_spans_never_produce_zero_duration():
    """A phrase whose start and end resolve to the same instant would give a
    zero-length subtitle cue."""
    flat = [dict(w, start_ms=1000, end_ms=1000) for w in PERFECT]
    _, durs, matched = phrase_spans(PHRASES, flat)
    if matched:
        assert all(d > 0 for d in durs)


def test_phrase_spans_respect_the_floor():
    starts, _, matched = phrase_spans(PHRASES, PERFECT, floor_ms=700)
    assert matched is True
    assert min(starts) >= 700


# ------------------------------------- last caption held to speech end (#29)
def test_last_phrase_is_held_to_the_end_of_speech():
    """THE FIX for run_77d71eba/s1 (open-questions #29).

    Every span ends at its last word's diarized end. For the FINAL phrase that
    breaks in the common case: when the closing words fail to match the
    transcript, _nearest_matched falls back to an earlier word and the caption
    vanishes while the character is still talking. Measured on that run: the
    caption ended at 5.90s of a 7.99s clip — 2.09s of uncaptioned speech.

    Here diarization stops at 900ms but speech runs to 2400ms.
    """
    short = [{"word": "Hello", "start_ms": 0, "end_ms": 400},
             {"word": "there.", "start_ms": 500, "end_ms": 900}]
    starts, durs, matched = phrase_spans(["Hello there."], short,
                                         speech_end_ms=2400)
    assert matched is True
    assert starts[0] + durs[0] == 2400, "the last caption must reach the speech end"


def test_only_the_last_phrase_is_extended():
    """Stretching an interior phrase would overlap the next one, and its end is a
    real measurement worth keeping."""
    starts, durs, _ = phrase_spans(PHRASES, PERFECT, speech_end_ms=9000)
    assert starts[0] + durs[0] == 900, "phrase 1 keeps its measured end"
    assert starts[-1] + durs[-1] == 9000, "only the last one is held"


def test_speech_end_never_shortens_a_caption():
    """It is a floor, not a clamp. A last word that genuinely runs past the
    detected speech end keeps its own timing rather than being cut."""
    _, durs, _ = phrase_spans(PHRASES, PERFECT, speech_end_ms=100)
    assert durs[-1] == 1400, "measured span survives a smaller speech_end"


def test_omitting_speech_end_keeps_the_old_behaviour():
    a = phrase_spans(PHRASES, PERFECT)
    b = phrase_spans(PHRASES, PERFECT, speech_end_ms=None)
    assert a == b


def test_the_extension_does_not_resurrect_a_failed_match():
    """A transcript too sparse to trust still returns matched=False, so the
    caller omits the sidecar entirely. speech_end must not paper over that."""
    _, _, matched = phrase_spans(PHRASES, [{"word": "zzz", "start_ms": 0, "end_ms": 1}],
                                 speech_end_ms=9000)
    assert matched is False
