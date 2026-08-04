"""
app/utils/text_utils.py — pure text helpers (no I/O).

Pure text helpers for phrase splitting and lenient JSON parsing.
"""
from __future__ import annotations

import json
import re

# Sentence-ending punctuation (ASCII + CJK).
_ENDERS = ".!?。！？"
# ASCII and CJK comma characters.
_COMMAS = ",，、"

_PHRASE          = re.compile(rf"[^{_ENDERS}{_COMMAS}]*[{_ENDERS}{_COMMAS}]+|\S[^{_ENDERS}{_COMMAS}]*$")
_PHRASE_NO_COMMA = re.compile(rf"[^{_ENDERS}]*[{_ENDERS}]+|\S[^{_ENDERS}]*$")


def split_phrases(text: str, split_on_comma: bool = False) -> list[str]:
    """Split text into phrases.

    By default, only sentence endings split phrases. Set
    `split_on_comma=True` to also split on commas.
    """
    text = (text or "").strip()
    if not text:
        return []
    pat = _PHRASE if split_on_comma else _PHRASE_NO_COMMA
    out = []
    for m in pat.finditer(text):
        # drop a trailing comma (it is a split point, not part of the phrase);
        # keep sentence punctuation, which carries intonation for TTS
        p = m.group().strip().rstrip(_COMMAS).strip()
        if p:
            out.append(p)
    return out


def parse_json_lenient(text: str):
    """Parse JSON, ignoring optional Markdown code fences.

    Raises json.JSONDecodeError on invalid input.
    """
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        t = t[4:] if t.lower().startswith("json") else t
    return json.loads(t)