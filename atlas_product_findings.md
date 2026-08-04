# Atlas — Hands-On Product Findings

**Basis:** A first-pass walkthrough of Course, PALS and CBL as an end user, plus feature comparison against Duolingo, Quizlet, Quizizz and TalentLMS. No customer research or analytics behind this — these are observations, not validated findings.

**How to read this:** items are grouped by theme rather than by severity, because each theme is a coherent piece of work someone can own. Every item is tagged:

- `[bug]` — behaves incorrectly, not a matter of taste
- `[improvement]` — works as built; could be better
- `[observed]` — my own use of the product
- `[vs. X]` — a specific competitor does this differently

The strategic items from this same review are in a separate document (*Proving Training Works: A Capability-Measurement Proposal for Atlas*) — in particular scenario roleplay in CBL and flashcard right/wrong tracking, which appear there because they support a larger argument.

---

## Theme 1 — Progress tracking is unreliable

This is the most important group here: it's the only one where the product does something factually wrong, and completion state is the thing customers report on.

**1.1 Pages mark themselves complete without being read.** `[bug]` `[observed]`
Pages become "complete" without any action from me. Whatever condition triggers completion is firing on load or on scroll rather than on genuine progress.

**1.2 Un-marking a page doesn't persist.** `[bug]` `[observed]`
Setting a completed page back to incomplete appears to work, but navigating away and returning shows it complete again. The un-mark is either not written or is immediately overwritten by 1.1.

**1.3 "Next" doesn't complete the current page.** `[bug]` `[observed]`
Advancing through the course requires separately clicking "mark as complete." Moving on is the natural completion signal; requiring a second, explicit action means genuine completions go unrecorded.

*Taken together these three point at one underlying problem — the rule for "when is a page complete" is inconsistent and its persistence is unreliable. Worth fixing as one piece of work rather than three tickets. Recommend this is confirmed and routed to whoever owns the defect tracker rather than treated as a roadmap item.*

## Theme 2 — Feedback moments interrupt instead of reward

**2.1 The XP popup blocks the "Next" button.** `[bug]` `[observed]`
The bottom-right XP notification overlaps the primary navigation control and stays long enough to obstruct it. At minimum it should be dismissible; better, it should not overlap navigation at all. A reward that makes you wait to continue is a penalty.

**2.2 The answer moment is under-designed.** `[improvement]` `[vs. Quizizz, Duolingo]`
Choosing an answer, and being told it was right, are the emotional peaks of a quiz. We render them as a state change. Quizizz and Duolingo invest heavily here, and it is a large part of why their sessions feel worth continuing.

## Theme 3 — The learning loop doesn't close

**3.1 Flashcards don't separate known from unknown.** `[improvement]` `[vs. Quizlet, Duolingo]`
There is no way to mark a card right or wrong, so there is no way to re-drill the ones that were wrong. The learner reviews everything equally, including what they already know. Self-graded right/wrong feeding a focused review of missed cards is the core loop of every serious flashcard product.

*This item also has strategic value beyond engagement — see the capability proposal, §7.*

**3.2 Flashcard animation is flat.** `[improvement]` `[observed]`
Minor, but the card flip is the one piece of physicality in the feature and it's worth making satisfying.

**3.3 Quiz format variety is limited.** `[improvement]` `[vs. Quizizz, Quizlet]`
A single question format throughout. Matching pairs and fill-in-the-blank are standard elsewhere, test recall differently from multiple choice, and break the monotony of a long track.

## Theme 4 — Content presentation is inconsistent

**4.1 Some articles have clear structure; others are walls of plain text.** `[improvement]` `[observed]`
Within the same product, some content uses headings, colour and visible hierarchy, and some is undifferentiated body text. The inconsistency reads as unfinished regardless of which version is better.

**Open question, and the reason this isn't yet a proposal:** is this a deliberate editorial decision, or an artefact of how content was authored? The likely explanation is the latter — content pasted or imported from other sources arriving without structure, while natively authored content keeps it.

The distinction changes the fix entirely:

- If it's authoring history, the work is in **content ingestion** — structure it on the way in — and the existing pages are a one-time cleanup.
- If it's editorial intent, the work is a style guide and a content pass.

Either way this touches a large volume of existing material, which is why it's flagged as significant rather than minor. *Recommend confirming the cause before any work is scoped.*

## Theme 5 — Course presentation

**5.1 The course banner looks dated.** `[improvement]` `[observed]`
It reads as a background-removed image dropped onto a flat backdrop rather than a designed header. This is subjective, and worth validating before acting on it — but it is the first thing a user sees, and first impressions of quality transfer to the whole product.

**5.2 The banner detail view wastes space.** `[improvement]` `[observed]`
Large empty black regions around the image instead of the image filling the available area.

## Theme 6 — CBL

**6.1 Scenarios have no imagery.** `[improvement]` `[observed]`
Scenario-based learning depends on the learner believing the situation. Text-only scenarios ask them to do all of that work themselves. Visuals of the setting and the people involved would raise immersion substantially for what is likely modest effort.

*The related item — AI-driven roleplay within CBL scenarios — is covered in the capability proposal, where it does more work than it does here.*

---

## Suggested triage order

1. **Theme 1** — correctness. Completion data is reported to customers; if it's wrong, the reports are wrong.
2. **2.1** — a blocking overlay on primary navigation, likely a small fix.
3. **Theme 4** — confirm the cause first; the answer determines whether this is large or small.
4. **Theme 3** — real engagement value, and 3.1 supports the strategic work.
5. **Themes 5, 6, and 2.2** — polish, genuinely valuable but not urgent.
