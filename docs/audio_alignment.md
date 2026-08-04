Return (start_ms_per_phrase, used_diarization).

Places each TTS phrase at the diarized start of its first word, matched by
CONTENT (difflib sequence alignment of the TTS word stream against the
diarized word stream). Robust to diarization dropping/adding words — a
single miss no longer shifts every later phrase (the positional bug).
Falls back to sequential placement (R1) when the transcript is too sparse or
the match is poor.

Starts are deliberately NOT clamped monotonic — see the design note below
before changing that.

Why CONTENT matching and not position: the original implementation took the
Nth diarized word for the Nth TTS word. One dropped or inserted word shifted
every subsequent phrase by one word's worth of time, and the drift
compounded over a clip. difflib finds the actual correspondence instead, so a
local miss stays local.

The 50% threshold is a judgement call, not a measured one: below half the
words matching, the transcript is assumed to be describing different audio
than we think and the whole alignment is thrown away rather than trusted
partially. Tune it if diarization quality changes.

`floor_ms` is the detected speech onset — nothing may be placed before the
character actually starts moving their mouth, or the voice leads the lips.
`sync_offset_ms` is a manual nudge for systematic lead/lag; 0 in practice.

NON-MONOTONIC BY DESIGN — this is the important thing to know before
"fixing" it. An earlier version of this docstring claimed "starts are clamped
monotonic"; that claim was wrong, and the absence of the clamp is deliberate.

The reason is specific to THIS path. Azure re-synthesises the text as
separate phrase clips, and Azure's delivery speed does not match the speed
Veo animated the mouth at. So the lip movement for phrase N+1 frequently
begins BEFORE the Azure audio for phrase N has finished. Each phrase is
therefore pinned to the lips it belongs to, even when that means it starts
before its predecessor ends — overlapping audio is preferred over audio that
visibly lags the mouth. Clamping monotonic would trade correct lip-sync for
tidier-looking numbers.

None of this applies to the ElevenLabs path, which does not call this
function at all: speech-to-speech preserves Veo's own timing, so there is
nothing to align. See sts_elevenlabs.process_scene.

KNOWN LIMITATION. The design assumes disorder is SMALL — the natural
overlap of a phrase starting slightly early. It cannot distinguish that from
GROSS disorder caused by a bad transcript, where a phrase lands seconds
before its predecessor and the narration plays scrambled rather than merely
overlapped. Gemini's word timings are not guaranteed monotonic;
bench/diarize_local.py counts "out-of-order word starts" as a sanity metric.
Nothing currently detects the difference. See docs/open-questions.md #12.

The trim length is unaffected either way (it uses max(), not the last
element), and subtitle cues cannot collide because renderer.build_srt sorts
and clamps overlaps independently.
