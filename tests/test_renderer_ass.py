"""
The ASS subtitle file (open-questions #23) — structure, not pixels.

These tests never call ffmpeg. What they check is the thing that is easy to get
wrong and hard to see: whether the generated .ass is well-formed and whether the
box actually scales flat. Whether it LOOKS right is a visual check on real
output, which no test can do.
"""
from __future__ import annotations

import re

import pytest

from app.pipeline.renderer import (
    DEFAULT_STYLE, SubtitleStyle, _ass_rounded_rect, _ass_text_esc, _ass_time,
)


# ---------------------------------------------------------------- primitives
@pytest.mark.parametrize("secs,expected", [
    (0.0, "0:00:00.00"),
    (1.5, "0:00:01.50"),
    (61.25, "0:01:01.25"),
    (3661.0, "1:01:01.00"),
    (-5.0, "0:00:00.00"),        # clamped, never a negative timestamp
])
def test_ass_timestamps(secs, expected):
    """ASS wants centiseconds and an unpadded hour — SRT's H:MM:SS,mmm is not
    accepted and fails as a silently unrendered line, not an error."""
    assert _ass_time(secs) == expected


def test_braces_in_a_caption_cannot_open_an_override_block():
    """`{` starts a style override in ASS. Unescaped, a caption containing one
    would swallow the rest of the line and the viewer would see it vanish."""
    out = _ass_text_esc("use {curly} braces")
    assert "\\{" in out and "\\}" in out
    assert re.search(r"(?<!\\)\{", out) is None


def test_newlines_become_hard_breaks():
    assert _ass_text_esc("line one\nline two") == "line one\\Nline two"


# ---------------------------------------------------------------- the shape
def test_rounded_rect_is_a_closed_path_with_four_corners():
    d = _ass_rounded_rect(400, 60, 12)
    assert d.startswith("m ")
    assert d.count(" b ") == 4, "one bezier per corner"
    assert all(tok in d for tok in ("m ", "l ", "b "))


def test_radius_is_clamped_to_the_box():
    """A radius larger than half the box would produce a self-crossing path,
    which libass renders as an inside-out blob rather than an error."""
    d = _ass_rounded_rect(20, 10, 999)
    assert "-" not in d, "no negative coordinates"


def test_zero_radius_degrades_to_a_plain_rectangle():
    assert _ass_rounded_rect(100, 40, 0) == "m 0 0 l 100 0 l 100 40 l 0 40"


# ---------------------------------------------------------------- the file
def _build(tmp_path, monkeypatch, cues, style=None, w=1280, h=720):
    """Run _burn_ass_boxed far enough to write subs.ass, with ffmpeg stubbed."""
    from app.pipeline import renderer

    monkeypatch.setattr(renderer, "_parse_srt", lambda p: cues)
    monkeypatch.setattr(renderer, "probe",
                        lambda p: {"w": w, "h": h, "has_audio": True})
    calls = {}

    def fake_ffmpeg(args, **kw):
        calls["args"] = args
    monkeypatch.setattr(renderer, "_ffmpeg", fake_ffmpeg)

    srt = tmp_path / "subs.srt"
    srt.write_text("")
    renderer._burn_ass_boxed(tmp_path, tmp_path / "in.mp4", srt,
                             tmp_path / "out.mp4", style or DEFAULT_STYLE)
    return (tmp_path / "subs.ass").read_text(encoding="utf-8"), calls["args"]


CUES = [(0.0, 2.0, "Hello there."), (2.5, 5.0, "How are you?")]


def test_the_file_has_the_three_required_sections(tmp_path, monkeypatch):
    ass, _ = _build(tmp_path, monkeypatch, CUES)
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]"):
        assert section in ass
    assert "PlayResX: 1280" in ass and "PlayResY: 720" in ass


def test_every_cue_becomes_a_box_line_and_a_text_line(tmp_path, monkeypatch):
    ass, _ = _build(tmp_path, monkeypatch, CUES)
    box = [l for l in ass.splitlines() if l.startswith("Dialogue: 0,")]
    text = [l for l in ass.splitlines() if l.startswith("Dialogue: 1,")]
    assert len(box) == len(text) == 2
    assert all("\\p1" in l and "\\p0" in l for l in box), "box lines are drawings"
    assert "Hello there." in text[0] and "How are you?" in text[1]


def test_the_box_sits_below_the_text_layer(tmp_path, monkeypatch):
    """Layer 0 renders under layer 1. Swap them and the box hides the caption."""
    ass, _ = _build(tmp_path, monkeypatch, CUES)
    lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
    assert lines[0].startswith("Dialogue: 0,") and "\\p1" in lines[0]
    assert lines[1].startswith("Dialogue: 1,") and "\\p1" not in lines[1]


def test_cost_is_flat_in_the_number_of_cues(tmp_path, monkeypatch):
    """THE WHOLE POINT (open-questions #23). _burn_boxed adds an ffmpeg input and
    two filtergraph nodes per cue; this adds two lines to one file. 200 cues must
    produce the same command as 2."""
    _, args_small = _build(tmp_path, monkeypatch, CUES)
    many = [(float(i), float(i) + 0.5, f"caption {i}") for i in range(200)]
    ass, args_big = _build(tmp_path, monkeypatch, many)

    assert args_small.count("-i") == args_big.count("-i") == 1
    assert "-filter_complex" not in args_big
    assert len([l for l in ass.splitlines() if l.startswith("Dialogue:")]) == 400


def test_opacity_is_written_as_inverted_ass_alpha(tmp_path, monkeypatch):
    """ASS alpha runs backwards: 00 is opaque, FF invisible. Getting this the
    right way round is the difference between a subtle box and a black slab."""
    ass, _ = _build(tmp_path, monkeypatch, CUES,
                    SubtitleStyle(box_opacity=1.0))
    assert "\\1a&H00&" in ass, "fully opaque -> alpha 00"

    ass, _ = _build(tmp_path, monkeypatch, CUES,
                    SubtitleStyle(box_opacity=0.0))
    assert "\\1a&HFF&" in ass, "fully transparent -> alpha FF"


def test_colours_are_converted_to_ass_bgr(tmp_path, monkeypatch):
    """ASS stores colours BGR, not RGB. A red box written naively comes out blue."""
    ass, _ = _build(tmp_path, monkeypatch, CUES,
                    SubtitleStyle(box_hex="FF0000", primary_hex="00FF00"))
    assert "\\1c&H0000FF&" in ass, "RGB FF0000 -> BGR 0000FF"
    assert "&H0000FF00" in ass, "text RGB 00FF00 -> BGR 00FF00"


def test_the_box_is_horizontally_centred(tmp_path, monkeypatch):
    ass, _ = _build(tmp_path, monkeypatch, [(0.0, 1.0, "hi")], w=1000)
    pos = re.search(r"Dialogue: 0,.*\\pos\((\d+),(\d+)\)", ass)
    x, y = int(pos.group(1)), int(pos.group(2))
    text_pos = re.search(r"Dialogue: 1,.*\\pos\((\d+),(\d+)\)", ass)
    assert int(text_pos.group(1)) == 500, "text centres on the frame"
    assert x < 500, "box starts left of centre"


def test_the_box_respects_the_bottom_margin(tmp_path, monkeypatch):
    style = SubtitleStyle(margin_v=100)
    ass, _ = _build(tmp_path, monkeypatch, [(0.0, 1.0, "hi")], style, h=720)
    y = int(re.search(r"Dialogue: 0,.*\\pos\(\d+,(\d+)\)", ass).group(1))
    assert y < 720 - 100, "the box top is above the margin, not on it"


def test_the_font_directory_is_passed_to_libass(tmp_path, monkeypatch):
    """libass resolves fonts by family name via fontconfig. Without fontsdir a
    font outside the system directories is silently substituted, and the box —
    which was measured with the real one — comes out the wrong width."""
    _, args = _build(tmp_path, monkeypatch, CUES)
    vf = args[args.index("-vf") + 1]
    assert "fontsdir=" in vf and "subtitles=filename='subs.ass'" in vf


def test_no_cues_is_an_error_not_a_silent_pass(tmp_path, monkeypatch):
    from app.pipeline.renderer import RenderError
    with pytest.raises(RenderError):
        _build(tmp_path, monkeypatch, [])
