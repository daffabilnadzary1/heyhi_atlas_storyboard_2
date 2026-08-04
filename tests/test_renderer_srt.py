"""
renderer.build_srt — L6 per-scene timings -> cues on the merged timeline.

build_srt is pure GIVEN probe data: callers may pass `scenes=` as a list of
(scene_id, path, probe) tuples, so these tests hand it fabricated durations and
never touch ffprobe or a real mp4.

The one thing to hold on to: cue offsets accumulate PROBED durations, not
blueprint lengths. L6 trimmed every speaking scene to its own voice track, so
the blueprint's numbers are stale by the time subtitles are built.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline.renderer import _srt_ts, build_srt


def _scenes(*specs):
    """(scene_id, duration_seconds) -> the (id, path, probe) shape build_srt wants."""
    return [(sid, Path(f"{sid}.mp4"), {"duration": dur}) for sid, dur in specs]


def _write_timings(run, scene_id, phrases, starts_ms, durs_ms):
    tts = run / "tts"
    tts.mkdir(parents=True, exist_ok=True)
    (tts / f"{scene_id}_timings.json").write_text(
        json.dumps({"phrases": phrases, "starts_ms": starts_ms, "durs_ms": durs_ms}),
        encoding="utf-8")


def _cues(srt_path: Path):
    """Parse an SRT into [(index, timing_line, text), ...]."""
    blocks = [b for b in srt_path.read_text(encoding="utf-8").split("\n\n") if b.strip()]
    out = []
    for b in blocks:
        lines = b.strip().split("\n")
        out.append((lines[0], lines[1], "\n".join(lines[2:])))
    return out


# ---------------------------------------------------------------- timestamps
def test_srt_timestamp_format():
    """Comma before the milliseconds — SRT, not WebVTT (which uses a period)."""
    assert _srt_ts(0) == "00:00:00,000"
    assert _srt_ts(3_661_001) == "01:01:01,001"


def test_negative_timestamps_clamp_to_zero():
    assert _srt_ts(-500) == "00:00:00,000"


# ---------------------------------------------------------------- cue building
def test_per_phrase_cues_from_the_l6_sidecar(tmp_path):
    bp = {"scenes": [{"id": "s1", "text": "Hello there. How are you?"}]}
    _write_timings(tmp_path, "s1", ["Hello there.", "How are you?"], [0, 1000], [900, 1400])

    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 3.0))))
    assert len(cues) == 2
    assert cues[0][1] == "00:00:00,000 --> 00:00:00,900"
    assert cues[0][2] == "Hello there."
    assert cues[1][1] == "00:00:01,000 --> 00:00:02,400"


def test_whole_scene_caption_when_no_sidecar(tmp_path):
    """The graceful-degrade path. If diarization was too sparse for L6 to write
    timings, the scene still gets a caption — one for the whole scene."""
    bp = {"scenes": [{"id": "s1", "text": "Hello there. How are you?"}]}
    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 3.0))))
    assert len(cues) == 1
    assert cues[0][1] == "00:00:00,000 --> 00:00:03,000"


def test_broll_produces_no_cues(tmp_path):
    bp = {"scenes": [{"id": "b1", "text": ""}]}
    assert _cues(build_srt(tmp_path, bp, _scenes(("b1", 4.0)))) == []


def test_offsets_accumulate_across_the_timeline(tmp_path):
    """Sidecar timings are per-scene; the merged video is one continuous
    timeline. Scene 2's cues must be pushed out by scene 1's duration."""
    bp = {"scenes": [
        {"id": "b1", "text": ""},
        {"id": "s1", "text": "First line."},
        {"id": "s2", "text": "Second line."},
    ]}
    _write_timings(tmp_path, "s1", ["First line."], [0], [1000])
    _write_timings(tmp_path, "s2", ["Second line."], [0], [1000])

    cues = _cues(build_srt(tmp_path, bp, _scenes(("b1", 4.0), ("s1", 3.0), ("s2", 3.0))))
    assert cues[0][1].startswith("00:00:04,000")     # after the 4s B-Roll
    assert cues[1][1].startswith("00:00:07,000")     # after B-Roll + s1


def test_short_cue_is_floored_to_the_minimum(tmp_path):
    """A one-word phrase would otherwise flash on screen for 80ms."""
    bp = {"scenes": [{"id": "s1", "text": "Yes."}]}
    _write_timings(tmp_path, "s1", ["Yes."], [0], [80])
    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 3.0))))
    assert cues[0][1] == "00:00:00,000 --> 00:00:00,500"     # MIN_CUE_MS


def test_cue_cannot_run_past_the_end_of_its_scene(tmp_path):
    bp = {"scenes": [{"id": "s1", "text": "Hello."}]}
    _write_timings(tmp_path, "s1", ["Hello."], [0], [9000])   # longer than the clip
    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 2.0))))
    assert cues[0][1].endswith("00:00:02,000")


def test_overlapping_cues_are_separated(tmp_path):
    """Two captions must never be on screen at once. Overlapping phrase spans —
    which align_starts can produce — are resolved by clamping the earlier cue's
    end to the later cue's start."""
    bp = {"scenes": [{"id": "s1", "text": "One. Two."}]}
    _write_timings(tmp_path, "s1", ["One.", "Two."], [0, 500], [2000, 1000])

    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 5.0))))
    ends = [c[1].split(" --> ")[1] for c in cues]
    starts = [c[1].split(" --> ")[0] for c in cues]
    assert ends[0] <= starts[1], "cue 1 must end no later than cue 2 begins"


def test_empty_phrases_are_skipped(tmp_path):
    bp = {"scenes": [{"id": "s1", "text": "Hello."}]}
    _write_timings(tmp_path, "s1", ["Hello.", "   "], [0, 1000], [900, 500])
    assert len(_cues(build_srt(tmp_path, bp, _scenes(("s1", 3.0))))) == 1


def test_malformed_sidecar_falls_back_rather_than_crashing(tmp_path):
    """_load_timings swallows parse errors on purpose — a corrupt sidecar must
    degrade to a whole-scene caption, not fail the whole render."""
    (tmp_path / "tts").mkdir()
    (tmp_path / "tts" / "s1_timings.json").write_text("{not json", encoding="utf-8")
    bp = {"scenes": [{"id": "s1", "text": "Hello there."}]}
    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 3.0))))
    assert len(cues) == 1


def test_srt_is_written_to_the_run_directory(tmp_path):
    bp = {"scenes": [{"id": "s1", "text": "Hello."}]}
    out = build_srt(tmp_path, bp, _scenes(("s1", 2.0)))
    assert out == tmp_path / "subs.srt"
    assert out.is_file()


def test_cues_are_numbered_from_one(tmp_path):
    bp = {"scenes": [{"id": "s1", "text": "One. Two."}]}
    _write_timings(tmp_path, "s1", ["One.", "Two."], [0, 1000], [900, 900])
    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 3.0))))
    assert [c[0] for c in cues] == ["1", "2"]


# ------------------------------------------------- cues too close to read (#29)
def _dur_ms(timing_line: str) -> int:
    def to_ms(ts):
        h, m, rest = ts.split(":")
        s, ms = rest.split(",")
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)
    a, b = [x.strip() for x in timing_line.split("-->")]
    return to_ms(b) - to_ms(a)


def test_phrases_sharing_a_start_are_merged_not_silently_dropped(tmp_path):
    """REGRESSION GUARD, from run_77d71eba (open-questions #29).

    When the diarizer's transcript runs short, phrase_spans gives every unmatched
    trailing phrase the SAME start — the last word it did match. The old code
    sorted, then clamped each cue's end to the next cue's start with a floor of
    a+1, so two cues sharing a start produced a ONE MILLISECOND cue. It was in
    the SRT and never reached the screen: "dan Helpdesk" was timed
    00:00:09,840 --> 00:00:09,840 and the words were simply lost.

    They must now be merged into one readable caption, keeping every word.
    """
    bp = {"scenes": [{"id": "s1", "text": "dan Helpdesk memberikan akses cepat."}]}
    _write_timings(tmp_path, "s1",
                   ["dan Helpdesk", "memberikan akses cepat."],
                   [5840, 5840],            # identical starts — the failure mode
                   [60, 60])                # and unusably short

    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 8.0))))

    assert len(cues) == 1, "two cues at the same instant are one caption"
    assert "dan Helpdesk" in cues[0][2] and "memberikan akses cepat." in cues[0][2], \
        "no phrase may be dropped"
    assert _dur_ms(cues[0][1]) >= 500, "the merged cue must be readable"


def test_a_run_of_fragments_becomes_readable_captions(tmp_path):
    """The comma-splitting symptom, in SRT terms: 6 fragments inside 3 seconds.
    Every surviving cue must clear the readability floor, and no text is lost."""
    phrases = ["PowerOne tiles", "termasuk Salesforce", "Epicor Mobile",
               "AI Desktop", "Pico Concierge", "Partners"]
    starts = [400, 1440, 2560, 3460, 4400, 5300]
    _write_timings(tmp_path, "s1", phrases, starts, [380, 440, 320, 520, 780, 280])
    bp = {"scenes": [{"id": "s1", "text": " ".join(phrases)}]}

    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 8.0))))

    assert all(_dur_ms(c[1]) >= 500 for c in cues), \
        f"unreadable cue: {[(_dur_ms(c[1]), c[2]) for c in cues]}"
    joined = " ".join(c[2] for c in cues)
    for p in phrases:
        assert p in joined, f"lost {p!r}"


def test_well_spaced_cues_are_left_alone(tmp_path):
    """The merge must not swallow normal sentence-level captions — that would
    turn every scene into one long block."""
    _write_timings(tmp_path, "s1", ["One.", "Two.", "Three."],
                   [0, 2000, 4000], [1500, 1500, 1500])
    bp = {"scenes": [{"id": "s1", "text": "One. Two. Three."}]}
    cues = _cues(build_srt(tmp_path, bp, _scenes(("s1", 6.0))))
    assert len(cues) == 3


# --------------------------------------------------- caption wrapping (#29)
from app.pipeline.renderer import _CAPTION_WIDTH, _display_width, _wrap_caption  # noqa: E402

LONG = ("PowerOne tiles, termasuk Salesforce, Epicor Mobile, AI Desktop, "
        "Pico Concierge, Partners, dan Helpdesk, memberikan akses cepat.")


@pytest.mark.parametrize("text", [
    LONG,
    "Employees receive 30 calendar / running days of annual leave, including Fridays and Saturdays.",
    "员工每年享有30个日历日的年假，其中包括周五和周六。",
    "日历日或连续日意味着周末也计入假期，而不仅仅是工作日。",
])
def test_no_wrapped_line_runs_off_the_frame(text):
    """The reason wrapping exists. Nothing else in the renderer breaks lines —
    _burn_boxed clamps the BOX to frame width but never the text, and the ass
    method uses WrapStyle 2 (explicit breaks only). An unwrapped 127-column
    caption is drawn straight off the edge of the picture."""
    for line in _wrap_caption(text).splitlines():
        assert _display_width(line) <= _CAPTION_WIDTH, f"overflows: {line!r}"


def test_cjk_is_measured_in_display_columns_not_characters():
    """A CJK glyph is two columns wide, so len() understates a Chinese caption by
    half. This one is 35 characters and 70 columns — under the limit by len(),
    over it by actual width. Measured wrongly it would be left on one line and
    drawn past the edge of the frame."""
    zh = "员工每年享有三十个日历日的年假其中包括周五和周六并且需要提前申请批准"
    assert len(zh) < _CAPTION_WIDTH < _display_width(zh)
    assert len(_wrap_caption(zh).splitlines()) > 1, "must wrap on display width"


def test_a_normal_chinese_caption_fits_on_one_line():
    """At the 64-column width a typical Chinese sentence is a single line —
    which is what it should look like. Pins the width choice from the caller's
    side, so lowering it back to 42 fails here with a reason attached."""
    zh = "员工每年享有30个日历日的年假，其中包括周五和周六。"
    assert "\n" not in _wrap_caption(zh)


def test_cjk_wraps_without_spaces_to_break_on():
    """Chinese has no word spaces, so word wrapping cannot apply — the text is
    chunked by display width instead."""
    zh = "员工每年享有三十个日历日的年假其中包括周五和周六并且需要提前申请批准"
    assert " " not in zh
    assert len(_wrap_caption(zh).splitlines()) > 1


def test_lines_are_balanced_not_greedy():
    """Greedy wrapping fills each line then strands the remainder — '...akses' /
    'cepat.' — which reads as a mistake. Lines should come out even."""
    widths = [_display_width(l) for l in _wrap_caption(LONG).splitlines()]
    assert max(widths) - min(widths) < _CAPTION_WIDTH // 2, f"uneven: {widths}"


def test_short_captions_are_left_on_one_line():
    assert "\n" not in _wrap_caption("Short enough to fit.")


def test_build_srt_wraps_what_it_writes(tmp_path):
    """Wrapping has to happen in build_srt, not only as a helper — subs.srt is a
    deliverable in its own right and every burn method reads it back."""
    _write_timings(tmp_path, "s1", [LONG], [0], [4000])
    srt = build_srt(tmp_path, {"scenes": [{"id": "s1", "text": LONG}]},
                    _scenes(("s1", 8.0)))
    body = _cues(srt)[0][2]
    assert "\n" in body
    for line in body.splitlines():
        assert _display_width(line) <= _CAPTION_WIDTH
