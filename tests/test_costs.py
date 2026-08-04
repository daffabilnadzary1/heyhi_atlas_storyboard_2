"""
app/costs.py — pricing arithmetic and the run rollup.

Cost bugs are invisible: nothing crashes, the number is just wrong, and you find
out from an invoice. The rates themselves cannot be tested (they are transcribed
from provider pricing pages), but everything around them can — that the right
rate is applied to the right unit, that an unpriced model degrades to a visible
gap rather than a silent zero, and that the rollup adds up.
"""
from __future__ import annotations

import json

import pytest

from app.costs import (
    COST_LOG, PRICING, UnknownRate, load, price, record, record_tokens,
    summarize, usage_from_response,
)


# ---------------------------------------------------------------- pricing
def test_token_rates_are_per_million():
    """$0.30 per 1M input tokens."""
    assert price("gemini-2.5-flash", "token_in", 1_000_000) == pytest.approx(0.30)
    assert price("gemini-2.5-flash", "token_out", 1_000_000) == pytest.approx(2.50)


def test_veo_priced_per_second_by_tier():
    assert price("Veo 3.1 Fast", "second", 8) == pytest.approx(0.80)
    assert price("Veo 3.1 Lite", "second", 8) == pytest.approx(0.40)


def test_broll_floor_costs_a_full_four_seconds():
    """Veo will not emit under 4s, so a 1s B-Roll is generated AND billed at 4s.
    This is why cost does not track finished video length."""
    assert price("Veo 3.1 Lite", "second", 4) == pytest.approx(0.20)


def test_kie_credits_converted_to_usd():
    assert price("kie.ai", "credit", 60) == pytest.approx(0.30)


def test_audio_rates():
    assert price("azure-tts", "second", 100) == pytest.approx(0.0412)
    assert price("eleven_multilingual_sts_v2", "second", 8) == pytest.approx(0.0264)


def test_lyria_priced_per_call():
    assert price("lyria-3-clip-preview", "call", 1) == pytest.approx(0.04)


def test_images_priced_per_image():
    assert price("gemini-2.5-flash-image", "image", 3) == pytest.approx(0.117)


def test_image_tokens_are_not_priced():
    """Deliberate: the text model's output rate applied to an image's ~1290
    tokens gives ~$0.003 against an observed ~$0.039, so those rates plainly do
    not apply. Recorded for information, priced per image."""
    with pytest.raises(UnknownRate):
        price("gemini-2.5-flash-image", "token_out", 1290)


def test_unknown_model_raises_rather_than_returning_zero():
    """A renamed model must not silently cost nothing."""
    with pytest.raises(UnknownRate):
        price("veo-4-ultra", "second", 8)


def test_negative_quantity_clamps_to_zero():
    assert price("Veo 3.1 Fast", "second", -5) == 0.0


# ---------------------------------------------------------------- recording
def test_record_writes_one_jsonl_line(tmp_path):
    record(tmp_path, layer="L5", provider="gemini", model="Veo 3.1 Fast",
           unit="second", quantity=8, measured=True, scene_id="s1")

    lines = (tmp_path / COST_LOG).read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["cost_usd"] == pytest.approx(0.80)
    assert rec["measured"] is True
    assert rec["scene_id"] == "s1"


def test_records_append_rather_than_overwrite(tmp_path):
    """Append-only JSONL: a crash mid-run must not lose the history so far."""
    for i in range(3):
        record(tmp_path, layer="L5", provider="gemini", model="Veo 3.1 Lite",
               unit="second", quantity=4, scene_id=f"s{i}")
    assert len(load(tmp_path)) == 3


def test_unpriced_usage_is_still_recorded(tmp_path):
    """A pricing gap must never lose the record of something already paid for —
    the quantity survives so the run can be re-priced once the rate is known."""
    rec = record(tmp_path, layer="L5", provider="gemini", model="veo-4-ultra",
                 unit="second", quantity=8)
    assert rec["cost_usd"] is None
    assert rec["quantity"] == 8


def test_record_tokens_writes_both_directions(tmp_path):
    record_tokens(tmp_path, layer="L2", model="gemini-2.5-flash",
                  usage={"input_tokens": 1000, "output_tokens": 2000})
    units = {r["unit"] for r in load(tmp_path)}
    assert units == {"token_in", "token_out"}


def test_missing_token_counts_record_nothing(tmp_path):
    """An absent count must not be written as zero — a call whose usage the SDK
    did not report is unknown, not free."""
    record_tokens(tmp_path, layer="L2", model="gemini-2.5-flash", usage=None)
    record_tokens(tmp_path, layer="L2", model="gemini-2.5-flash", usage={})
    assert load(tmp_path) == []


# ---------------------------------------------------------------- usage parsing
class _Meta:
    prompt_token_count = 1234
    candidates_token_count = 567


class _Resp:
    usage_metadata = _Meta()


def test_usage_extracted_from_response():
    assert usage_from_response(_Resp()) == {"input_tokens": 1234, "output_tokens": 567}


def test_unrecognised_response_shape_yields_nothing():
    """The most version-sensitive surface in the SDK. Losing a token count must
    never break generation."""
    assert usage_from_response(object()) == {}
    assert usage_from_response(None) == {}


# ---------------------------------------------------------------- rollup
def _populate(run):
    record(run, layer="L2", provider="gemini", model="gemini-2.5-flash",
           unit="token_in", quantity=1_000_000)
    record(run, layer="L4", provider="gemini", model="gemini-2.5-flash-image",
           unit="image", quantity=2)
    record(run, layer="L5", provider="gemini", model="Veo 3.1 Fast",
           unit="second", quantity=8)
    record(run, layer="L7", provider="gemini", model="lyria-3-clip-preview",
           unit="call", quantity=1)


def test_summary_totals_every_layer(tmp_path):
    """The whole point: L2, L4 and L7 used to be invisible."""
    _populate(tmp_path)
    s = summarize(tmp_path)
    assert s["total_usd"] == pytest.approx(0.30 + 0.078 + 0.80 + 0.04)
    assert set(s["by_layer"]) == {"L2", "L4", "L5", "L7"}
    assert s["events"] == 4


def test_summary_of_a_run_with_no_spend(tmp_path):
    assert summarize(tmp_path)["total_usd"] == 0.0
    assert summarize(tmp_path)["events"] == 0


def test_unpriced_usage_surfaces_in_the_summary(tmp_path):
    """total_usd is an undercount when this list is non-empty, and the caller
    needs to be able to tell."""
    _populate(tmp_path)
    record(tmp_path, layer="L5", provider="gemini", model="veo-4-ultra",
           unit="second", quantity=8)
    s = summarize(tmp_path)
    assert len(s["unpriced"]) == 1
    assert s["unpriced"][0]["model"] == "veo-4-ultra"


def test_informational_records_are_not_counted_as_unpriced(tmp_path):
    """Image token counts are recorded on purpose and priced on purpose — they
    must not look like a pricing gap."""
    record(tmp_path, layer="L4", provider="gemini", model="gemini-2.5-flash-image",
           unit="token_out", quantity=1290, priced=False)
    assert summarize(tmp_path)["unpriced"] == []


def test_torn_final_line_does_not_lose_the_rest(tmp_path):
    """A process killed mid-write leaves a partial line. The records before it
    are still valid and must survive."""
    _populate(tmp_path)
    with (tmp_path / COST_LOG).open("a", encoding="utf-8") as f:
        f.write('{"layer": "L5", "cost_us')
    assert len(load(tmp_path)) == 4


def test_every_pricing_entry_is_self_consistent():
    """The unit key and the unit recorded in the tuple must agree, or price()
    would look up a rate under a name nothing writes."""
    for model, table in PRICING.items():
        for unit, (tuple_unit, rate) in table.items():
            assert unit == tuple_unit, f"{model}: {unit} != {tuple_unit}"
            assert rate > 0, f"{model}/{unit} has a non-positive rate"
