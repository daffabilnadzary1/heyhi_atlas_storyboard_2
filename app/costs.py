"""
app/costs.py — the one place spend is priced and recorded.

WHY THIS EXISTS. Cost used to be Veo-only: video_veo_client held a
COST_PER_SECOND table and appended to cost_log.jsonl, and /pipeline/scenes
summed that file and returned it as `total_cost_usd`. It was never a total —
images, TTS, speech-to-speech, diarization, the director's own retries and Lyria
were all invisible.

THE SHAPE OF THE PROBLEM. Providers bill in different units: per token, per
second of generated video, per second of synthesised audio, per image, per call,
per credit. So a record cannot just be a dollar figure — it stores the UNIT and
the QUANTITY that were actually measured, and the price is derived:

    {"layer": "L5", "provider": "gemini", "model": "Veo 3.1 Fast",
     "unit": "second", "quantity": 8.0, "cost_usd": 0.8, "measured": true}

`measured` distinguishes a quantity read from the real artifact (the length of
the mp4 on disk, the credits the provider actually deducted) from one inferred
from what we asked for. Only measured numbers are trustworthy when reconciling
against an invoice.

PRICING IS DATA, not logic. PRICING below is transcribed from cost.md. Rates
move; update the table and the date, not the code.

APPEND-ONLY JSONL, deliberately. A single JSON document would need
read-modify-write and would lose the whole run's history if the process died
mid-generation — which is exactly when the cost record matters most.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

COST_LOG = "cost_log.jsonl"

# Rates last checked 2026-08-01. Source: cost.md.
# Every entry is (unit, usd_per_unit). Keep the unit strings in sync with the
# `unit` field written by the recorders below.
PRICING: dict[str, dict[str, tuple[str, float]]] = {
    # --- L2 director + L6 diarization: token-billed -------------------------
    "gemini-2.5-flash": {
        "token_in":  ("token_in",  0.30 / 1_000_000),
        "token_out": ("token_out", 2.50 / 1_000_000),
    },
    # --- L4 images ---------------------------------------------------------
    # Billed per output image. Token counts ARE recorded when the SDK reports
    # them, but are not priced: applying the text model's $2.50/1M output rate
    # to an image's ~1290 tokens gives ~$0.003, an order of magnitude below the
    # observed ~$0.039 per image, so the text rates clearly do not apply to
    # image output. Priced per image until that is resolved. See cost.md.
    "gemini-2.5-flash-image": {
        "image": ("image", 0.039),
    },
    # --- L5 video (Gemini/AI Studio) ---------------------------------------
    "Veo 3.1 Fast": {"second": ("second", 0.10)},
    "Veo 3.1 Lite": {"second": ("second", 0.05)},
    # --- L5 video (kie.ai) -------------------------------------------------
    # kie bills credits, and scene_gen reads the balance before/after each call,
    # so the quantity here is always MEASURED rather than estimated.
    "kie.ai": {"credit": ("credit", 0.005)},
    # --- L6 audio ----------------------------------------------------------
    # Azure: per second of SYNTHESISED audio — measured before silence trimming,
    # because Azure billed for what it produced, not for what we kept.
    "azure-tts": {"second": ("second", 0.000412)},
    # ElevenLabs STS: per second of INPUT audio. The converted output is not
    # separately charged.
    "eleven_multilingual_sts_v2": {"second": ("second", 0.0033)},
    # --- L7 music ----------------------------------------------------------
    # Lyria emits a fixed ~30s clip, so per-call and per-clip are the same thing.
    "lyria-3-clip-preview": {"call": ("call", 0.04)},
}

PRICING_LAST_CHECKED = "2026-08-01"


class UnknownRate(KeyError):
    """No rate for this (model, unit). Raised only by price(); the recorders
    swallow it so a pricing gap can never lose an artifact we already paid
    for — the record is still written, with cost_usd = None."""


def price(model: str, unit: str, quantity: float) -> float:
    """usd for `quantity` of `unit` on `model`. Raises UnknownRate if untabulated."""
    table = PRICING.get(model)
    if table is None or unit not in table:
        raise UnknownRate(f"no rate for model={model!r} unit={unit!r}")
    _, per_unit = table[unit]
    return round(per_unit * max(float(quantity), 0.0), 6)


def record(run_dir: str | Path, *, layer: str, provider: str, model: str,
           unit: str, quantity: float, measured: bool = False,
           **extra) -> dict:
    """Price one usage event and append it to run_0X/cost_log.jsonl.

    Returns the record (handy in tests). Never raises on an unpriced model —
    cost_usd is left None and the quantity is still on record, so the run can be
    re-priced later once the rate is known.

    `extra` carries whatever identifies the event for debugging: scene_id,
    attempts, phrase index. It is written verbatim.
    """
    try:
        usd = price(model, unit, quantity)
    except UnknownRate:
        usd = None
    rec = {"layer": layer, "provider": provider, "model": model,
           "unit": unit, "quantity": round(float(quantity), 6),
           "cost_usd": usd, "measured": bool(measured), **extra}
    p = Path(run_dir) / COST_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def record_tokens(run_dir: str | Path, *, layer: str, model: str,
                  usage: dict | None, **extra) -> None:
    """Two records (in + out) for a token-billed call.

    `usage` is the shape produced by usage_from_response(). None or a missing
    count means the SDK did not report it — nothing is written rather than a
    zero, so an absent number never masquerades as a free call.
    """
    if not usage:
        return
    for unit, key in (("token_in", "input_tokens"), ("token_out", "output_tokens")):
        n = usage.get(key)
        if n:
            record(run_dir, layer=layer, provider="gemini", model=model,
                   unit=unit, quantity=n, measured=True, **extra)


def usage_from_response(resp) -> dict:
    """Pull token counts off a google-genai response.

    Defensive by design: this is the most version-sensitive surface in the SDK,
    and losing a token count must never break generation. An unrecognised shape
    yields {} and the caller simply records no tokens.
    """
    meta = getattr(resp, "usage_metadata", None)
    if meta is None:
        return {}
    out = {}
    for key, attrs in (
        ("input_tokens",  ("prompt_token_count", "input_token_count")),
        ("output_tokens", ("candidates_token_count", "output_token_count")),
    ):
        for a in attrs:
            v = getattr(meta, a, None)
            if v:
                out[key] = int(v)
                break
    return out


# ---------------------------------------------------------------- reporting
def load(run_dir: str | Path) -> list[dict]:
    """Every cost record for a run, oldest first. Missing log -> []."""
    p = Path(run_dir) / COST_LOG
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # a torn final line must not lose the rest
    return out


def summarize(run_dir: str | Path) -> dict:
    """Totals for a run: overall, per layer, per model, plus what could not be
    priced.

    `unpriced` is the honesty check — a non-empty list means `total_usd` is an
    undercount, not a total.
    """
    records = load(run_dir)
    total = 0.0
    by_layer: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    unpriced: list[dict] = []

    for r in records:
        usd = r.get("cost_usd")
        if usd is None:
            # priced=False marks a record kept for INFORMATION only — image
            # token counts, which are recorded but deliberately not billed. Those
            # are not evidence of an undercount, so they stay out of `unpriced`.
            if r.get("priced") is not False:
                unpriced.append({"model": r.get("model"), "unit": r.get("unit"),
                                 "quantity": r.get("quantity")})
            continue
        total += usd
        by_layer[r.get("layer", "?")] += usd
        by_model[r.get("model", "?")] += usd

    return {
        "total_usd": round(total, 6),
        "by_layer": {k: round(v, 6) for k, v in sorted(by_layer.items())},
        "by_model": {k: round(v, 6) for k, v in sorted(by_model.items())},
        "events": len(records),
        "unpriced": unpriced,
        "pricing_last_checked": PRICING_LAST_CHECKED,
    }
