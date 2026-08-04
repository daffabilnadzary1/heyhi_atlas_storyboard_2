"""
Narration comes back in the requested language (open-questions #28).

The failure this guards against is the expensive kind: run_77d71eba asked for
Indonesian, got English narration, and was otherwise a perfectly valid blueprint.
Nothing complained, so it would have been discovered by watching the finished
video — after the entire Veo bill had been paid.

The check is a heuristic (English function-word frequency), so these tests are
mostly about its EDGES: it must not fire on genuine non-English text, on short
text, or on English runs. A false positive costs a director retry; a false
negative costs a whole video.
"""
from __future__ import annotations

import pytest

from app.config import DirectorConfig
from app.pipeline.director import (
    _ENGLISH_MARKER_THRESHOLD, _english_marker_ratio, check_output_language,
    validate_blueprint,
)


def _bp(base, texts):
    """The golden blueprint with its speaking scenes' text replaced."""
    bp = base.model_copy(deep=True)
    it = iter(texts)
    for s in bp.scenes:
        if s.type == "video-with-audio":
            s.text = next(it, "")
    return bp


ENGLISH = [
    "PowerOne tiles include Salesforce, Epicor Mobile and Helpdesk for quick access.",
    "Clicking a tile like Helpdesk takes you directly into the related service portal.",
    "Using these pages ensures you follow the same documented procedures as everyone else.",
]
INDONESIAN = [
    "Tile PowerOne mencakup Salesforce, Epicor Mobile, dan Helpdesk untuk akses cepat.",
    "Mengklik tile seperti Helpdesk akan membawa Anda langsung ke portal layanan internal.",
    "Menggunakan halaman ini memastikan Anda mengikuti prosedur yang sama seperti perusahaan.",
]


# ---------------------------------------------------------------- the ratio
def test_english_scores_far_above_the_threshold():
    ratio, n = _english_marker_ratio(ENGLISH)
    assert n > 20
    assert ratio > 2 * _ENGLISH_MARKER_THRESHOLD, f"english scored only {ratio:.2f}"


@pytest.mark.parametrize("name,texts", [
    ("indonesian", INDONESIAN),
    ("malay", ["Jubin PowerOne termasuk Salesforce dan Helpdesk untuk akses pantas.",
               "Mengklik jubin seperti Helpdesk membawa anda terus ke portal dalaman.",
               "Menggunakan halaman ini memastikan anda mengikuti prosedur yang sama."]),
    ("french", ["Les tuiles PowerOne comprennent Salesforce et Helpdesk pour un accès rapide.",
                "Cliquer sur une tuile comme Helpdesk vous amène directement dans le portail.",
                "L'utilisation de ces pages garantit que vous suivez les mêmes procédures."]),
    ("spanish", ["Los mosaicos de PowerOne incluyen Salesforce y Helpdesk para un acceso rápido.",
                 "Al hacer clic en un mosaico accede directamente al portal de servicio interno.",
                 "El uso de estas páginas garantiza que sigue los mismos procedimientos."]),
    ("german", ["Die PowerOne Kacheln umfassen Salesforce und Helpdesk für schnellen Zugriff.",
                "Ein Klick auf eine Kachel führt Sie direkt zum internen Serviceportal.",
                "Die Nutzung dieser Seiten stellt sicher, dass Sie dieselben Verfahren befolgen."]),
])
def test_other_latin_languages_score_near_zero(name, texts):
    """The marker list deliberately excludes words shared with Romance languages
    ("a", "on", "as", "or", "in", "at"). Put them back and French starts failing
    as English — which is why they are not in there."""
    ratio, _ = _english_marker_ratio(texts)
    assert ratio < _ENGLISH_MARKER_THRESHOLD, f"{name} would false-positive at {ratio:.2f}"


def test_product_names_do_not_make_text_look_english():
    """The real content is full of Salesforce, Helpdesk, Epicor. Non-English
    narration carrying English product names must still pass."""
    ratio, _ = _english_marker_ratio(
        ["Buka Salesforce, Epicor Mobile, AI Desktop, Pico Concierge, dan Helpdesk."])
    assert ratio < _ENGLISH_MARKER_THRESHOLD


# ---------------------------------------------------------------- the check
def test_english_narration_under_a_non_english_config_is_reported(bp):
    problems = check_output_language(_bp(bp, ENGLISH * 3), "indonesian")
    assert len(problems) == 1
    msg = problems[0]
    # the message is a prompt fragment aimed at the model — it has to say what
    # to change, and what NOT to change
    assert "indonesian" in msg
    assert "text" in msg and "prompt" in msg


def test_correct_language_passes(bp):
    assert check_output_language(_bp(bp, INDONESIAN * 3), "indonesian") == []


@pytest.mark.parametrize("language", [
    "English", "english", "EN-GB", "Bahasa Inggris", "", None,
])
def test_english_runs_are_never_checked(bp, language):
    """No-op for English, including the labels a front-end might send. The check
    only knows how to spot English, so on an English run it has nothing to say."""
    assert check_output_language(_bp(bp, ENGLISH * 3), language) == []


def test_too_little_text_is_not_judged(bp):
    """Under 20 words there is not enough signal, and a false positive costs a
    full director retry. Staying quiet is the cheaper error."""
    assert check_output_language(_bp(bp, ["Hello there."]), "indonesian") == []


def test_broll_only_blueprint_is_not_judged(bp):
    assert check_output_language(_bp(bp, []), "indonesian") == []


def test_the_check_is_aggregate_not_per_scene(bp):
    """One scene of mostly product names scores low on its own; the blueprint as
    a whole still reads as English. Judging per scene would let this through."""
    mixed = ["PowerOne Salesforce Epicor Helpdesk Pico Concierge Partners."] + ENGLISH * 2
    assert check_output_language(_bp(bp, mixed), "indonesian") != []


# ---------------------------------------------------------------- wiring
def test_validate_blueprint_reports_it(bp, cfg):
    """It has to run inside validate_blueprint, not beside it — that is what
    feeds it back to the model through the retry loop."""
    import dataclasses
    wrong = _bp(bp, ENGLISH * 3)
    id_cfg = dataclasses.replace(cfg, language="indonesian")
    assert any("indonesian" in p for p in validate_blueprint(wrong, id_cfg))


def test_the_golden_blueprint_still_validates_clean(bp, cfg):
    """cfg.language is English, so adding this check must not disturb any
    existing run. Guards against the check firing where it should be a no-op."""
    assert validate_blueprint(bp, cfg) == []
