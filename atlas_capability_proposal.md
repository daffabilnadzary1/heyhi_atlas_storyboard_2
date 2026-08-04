# Proving Training Works: A Capability-Measurement Proposal for Atlas

**Prepared for:** Leadership review
**Status:** Ideas for the incoming product manager's roadmap. Nothing here requires approval today.
**Basis:** A hands-on review of Course, PALS and CBL as an end user, plus feature comparison against Duolingo, Quizlet, Quizizz and TalentLMS. No customer research or usage data behind this yet — treat it as a structured first pass, not a validated backlog.

---

## 1. The problem our buyers have

Every LMS on the market reports **consumption**: courses completed, hours logged, streaks maintained. Atlas does this too, and does it competently.

But consumption is activity, not capability. When our customer's L&D lead goes into their annual budget review, they can say *"94% of staff completed the compliance track."* And then someone asks the only question that matters — **"and did anything actually change?"** — and they have nothing.

So they renew on faith. Faith is a weak foundation for a renewal, and a weak position in a competitive bid.

> **Every LMS can tell a business that its people finished the course. None can show that they got better.**

## 2. Why Atlas is unusually well placed to solve it

The reason nobody solves this well is that quizzes can't. A quiz measures recall — whether you can identify the right answer from four options. It says nothing about whether you can *do* the thing under pressure.

**Atlas already has something better: CBL scenario roleplay puts a learner into an observable, repeatable performance situation.** That is not a quiz. It is a work sample.

This matters competitively. A platform whose assessment layer is multiple-choice questions and progress bars *cannot* build what follows, no matter how much they want to — they have no instrument to measure with. We do.

## 3. The idea: capability benchmarking

1. **Month 1 — baseline.** The learner completes a scenario roleplay against an AI counterpart. Say: a negotiation.
2. **They train.** Normal Atlas usage.
3. **Month 3 — re-measure.** A *different* scenario built to the same difficulty specification.
4. **Compare** both sessions against one fixed rubric, and surface the difference — with excerpts from the actual transcripts as evidence.

The output is a page a customer can put in front of their own CFO:

> *Objection handling: 2/5 → 4/5.*
> *Month 1: "Okay, I can do 15% off."*
> *Month 3: "Before we discuss price — what's driving the timeline on your side?"*

**Be clear about what this is and isn't.** It is not a dollar ROI figure; we cannot honestly attribute revenue to a training course. It is *evidence of behavior change* — which is what a training buyer actually needs to defend a budget, and considerably more than they get today.

**Honest positioning:** I could not find an LMS doing this well, but I have not surveyed the market systematically. Some competitors may have adjacent features. The claim to make is "rare and hard," not "nobody has thought of it."

## 4. What makes the comparison credible

The obvious objection — *"maybe the second scenario was just easier"* — is the one that decides whether this is a real product or a demo trick. Three things answer it:

- **The rubric is the constant, not the scenario.** 4–6 dimensions per skill, each with behavioral anchors (*"1 = accepts the first counter-offer without probing; 5 = uncovers the underlying interest before conceding"*). Every session, forever, is scored against the same rubric. **The rubric is the product; scenarios are just content.**
- **Parallel forms, not repeats.** Reusing the identical scenario measures memory of that scenario. Using an unrelated one isn't comparable. Instead, scenarios are generated from a *specification* that pins what actually drives difficulty — counterpart resistance, information asymmetry, concession room, turn limit, stakes — and varies only surface detail: industry, product, names, personality.
- **A cheap calibration check.** Have a small group run two different forms back-to-back with no training in between. If scores land close, the forms are equivalent. If everyone scores a point higher on Form B, it's easier and the spec gets fixed. One afternoon, not a research programme.

**The known weakness:** AI judging is not perfectly repeatable — the same transcript can score slightly differently on two runs. Anchor examples and averaging across rubric dimensions dampen this, but the honest design conclusion is that **the transcript excerpts carry the claim and the score is only an index.** A proposal built on the number alone invites an accuracy argument we would lose.

## 5. A principle worth committing to

**The business gets the evidence. The individual keeps the score.**

Individual scores are visible to the learner alone. The business sees cohorts only:

> *"42 sales reps completed the negotiation track. Average objection handling moved 2.3 → 3.6 over three months. 31 of 42 improved by at least one level. Weakest dimension across the cohort: concession discipline."*

No names, no per-person rows, no leaderboards, no individual export, and no breakdown below a minimum cohort size — otherwise "the three people in the Jakarta office" is de-anonymisation with extra steps.

This is not only an ethical position, it is a **data-quality** one. The moment learners suspect these sessions feed performance reviews, they will play it safe, game the scenarios, and the measurement becomes worthless. It is also the only defensible posture while an AI is doing the judging, and it keeps us clear of automated-employee-evaluation scrutiny in regulated markets.

*Flagged for the PM:* some buyers will ask for per-manager visibility. That should remain a deliberate, contractual, consent-gated decision — not something quietly added in a later sprint because one customer asked.

## 6. What it would take

| Piece | Notes |
| --- | --- |
| **Scenario roleplay in CBL** | Already on the improvement list as a "nice to have." It is in fact the measurement instrument — nothing else here works without it. |
| **A rubric per skill** | The genuinely hard design work. Everything else is plumbing. |
| **AI scoring against the rubric** | Fixed prompt, anchor exemplars, transcripts logged for human spot-check. |
| **Flashcard right/wrong tracking** | See §7 — cheap, wanted anyway, and it produces a second evidence stream for free. |
| **A place to store all this** | See §8. |

Version 1 does not need generated scenario banks or formal test equating: one rubric, two or three hand-written parallel scenarios, AI scoring with human review of the comparison report. That is demoable. Presenting the full version as the proposal makes it read as a research programme and it gets parked.

## 7. Two supporting themes from the same review

These are worth doing on their own merits, and one of them feeds §3 directly.

**Theme A — The learning loop is incomplete.**
Flashcards don't distinguish what the learner knows from what they don't, so nothing is re-drilled. Quizlet and Duolingo build their entire retention model on exactly this loop. *(vs. Quizlet, Duolingo)*

The strategic point: **right/wrong per card, over time, is a retention curve.** "4 of 12 cards wrong in month 1, 1 of 12 at month 3" is hard knowledge-retention data, collected as a free byproduct of a feature we want regardless. It pairs with the softer rubric evidence to make the capability story much harder to dismiss.

**Theme B — Interaction feels static.**
One quiz format throughout, and minimal feedback at the moment of answering. Quizizz and Duolingo treat the answer moment as the product's emotional peak; we treat it as a state change. Concretely: more answer/feedback motion, and format variety — matching, fill-in-the-blank. CBL scenarios would also benefit from imagery to make the situation feel real. *(vs. Quizizz, Duolingo, Quizlet)*

*Also observed:* our written content is presented inconsistently — some with clear heading/body structure, some as flat text. The likely cause is authoring history rather than design intent (content brought in from elsewhere arriving unstructured). Worth confirming, because if that's right, the fix is in how content is ingested, not in editing pages one at a time. That connects directly to §8.

## 8. One connection worth flagging: xAPI

I have separately been asked to look into improving SCORM and xAPI support. Early observation, with research still ongoing:

**The capability-measurement idea and the xAPI work need the same infrastructure.** Everything in §3 and §7 has to be recorded somewhere: *learner attempted scenario X, scored 3/5 on objection handling, at month 3*; *learner answered flashcard 7 incorrectly*. That is precisely what xAPI is — statements of the form `actor – verb – object`, stored in a Learning Record Store. The aggregate dashboard in §5 is a query over that store.

If these are planned as two separate projects, we will build a bespoke data model for capability tracking and then rebuild it on xAPI later. Planned together, the standards work delivers the foundation the measurement feature needs.

*(SCORM is the adjacent, separate question: importing customers' existing content libraries, and exporting Atlas content to run inside their existing LMS. Two different builds, both commercially relevant. Test packages are being trialled against Atlas now.)*

## 9. The ask

None, today. This is offered as input for the incoming product manager's roadmap, and I'd rather it be argued with than accepted.

If any one thing survives this meeting, it should be this: **we are one feature away from being able to demonstrate that our training works, and almost nobody else can.** The feature is scenario roleplay in CBL, which is already on the list — currently marked as a low priority.
