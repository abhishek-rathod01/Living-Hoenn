# LIVING HOENN — MASTER PLAN
### Reconciled from every project conversation (29 Jun - 31 Aug 2026) and all 17 project files
### Compiled 1 September 2026

This supersedes HANDOVER_4 as the current planning document. HANDOVER_3
remains the technical reference. Nothing here is new work invented from
scratch — it is the accumulated plan, deduplicated, with dead threads closed
and one ordering imposed.

NOTE added by tonight's overnight session: several items below (marked
[NEEDS YOUR ANSWER] or describing cbcc26c/trainer_defeated as unresolved)
were resolved earlier tonight, before this overnight run started. Left
verbatim below for historical accuracy — do not re-do work this document
describes as open if Phase 0 of tonight's prompt already covers it.

Status tags: **[DONE]** · **[DONE, UNVERIFIED LIVE]** · **[OPEN]** ·
**[PARKED]** deliberately · **[LOST]** was planned, never happened ·
**[STALE]** document contradicts reality.

---

## §0 — What I could and couldn't recover

**Recovered in full:** the original Fable four-phase plan (4 Jul), the
Fable-orchestrated decomp-mining plan (11-14 Jul), the three-fix session and
cbcc26c (21 Jul), the repo audit and trainer_defeated bug (23 Aug), the
faculty outreach and positioning session (31 Aug).

**Could NOT recover:** the verbatim text of the four drafted-unsent emails
from 31 Aug. Descriptions exist, not the actual prose.

**Not recoverable by me at all:** anything done at the PC that was never
reported back into a chat.

---

## §1 — The Fable plan: where it actually stands

There were two Fable plans, and both are further along than the handovers
suggest.

### Plan 1 — the original four phases (Fable, 4 July)

| Phase | What | Status |
|---|---|---|
| 0 | Prove the Python + LLM half, no emulator | [DONE] |
| 1 | mGBA -> bridge connection only | [DONE] |
| 2 | Real memory reads (party, map, badges, trigger byte) | [DONE] — 8 addresses grepped from your own pokeemerald.map, confirmed live 5 Jul |
| 3 | Injection — "the hardest step" | [DONE] — confirmed live 5 Jul, including the awe system firing on a legendary |

Fable's own framing was that Phase 3 was where the difficulty lived and that
you should scope it to one cooperative NPC. **You went well past that** — it
generalised to the whole field-message pipeline.

### Plan 2 — the decomp-mining rollout (Fable as orchestrator, 11-14 July)

| Phase | What | Status |
|---|---|---|
| A | 5-map pilot extraction via parallel map-extractor subagents | [DONE] — 103 object events, 185 lines, 16 trainer parties, pushed |
| B | Wire mined data into the bridge (trainer grounding, renown tiers, object-type gating) | [DONE] — pushed, live-verified, surfaced three bugs |
| B.1 | Fix the three live-observed bugs | [DONE, UNVERIFIED LIVE] — cbcc26c, 16/16 tests, never live-verified as of this writing. NOTE tonight: pushed 28 July per direct fetch check; trainer_defeated specifically was NOT actually fixed despite the commit message, and IS now fixed tonight. |
| C | Full ~400-map rollout | [LOST] — deferred pending B.1 live verification, which still has not happened as of tonight (code is now correct, but nobody has stood at the emulator). The map-extractor subagent config still exists and is reusable as-is. |

### The other genuinely lost thread

**The quest engine.** quest_bridge_server.py and quest_engine.py were
intentionally parked on 11 July. A diagnostic-first prompt was written and
never run. Recommendation: close it, don't revive it — the dialogue-only
bridge is the demonstrable thing, and reviving the quest engine competes
directly with the evaluation work for the same hours.

---

## §2 — File status: what's current, what's stale

(NOTE: this table is from 1 September and is now largely resolved by an
earlier session tonight — dialogue_bridge_server.py, README, ACTION_PLAN,
HOME_SETUP, CLAUDE.md, ARCHITECTURE.md were all fixed before this overnight
run started. Left verbatim for history; do not redo.)

### Current and trustworthy
| File | Note |
|---|---|
| living-hoenn-VERIFICATION_REPORT.md | Still accurate. Facts here don't decay. |
| living-hoenn-ARCHITECTURE.md | Mostly current, but described the quest engine as live (III.2-III.5) as of this writing — since fixed. |
| LIVING_HOENN_HANDOVER_3.md | Current technical state. Now committed to the repo as of tonight. |
| LIVING_HOENN_HANDOVER_4.md | Current for outreach/recording. Superseded by this document for planning. |
| LIVING_HOENN_RUN_OF_SHOW.md, _DEMO_SCRIPT.md, _PORTFOLIO_SCRIPT.md, _STARTUP_COMMANDS.txt, OBS setup doc | Current. Deliberately left uncommitted by tonight's session — personal/career content. |

### Not in the repo at all — [OPEN]
Confirmed absent from every branch as of 23 Aug: LIVING_HOENN_HANDOVER_3.md
(now committed tonight), the demo script, the startup commands doc, the OBS
setup doc, and everything after 28 July (repo HEAD at the time). Unbacked by
design: npc_profiles.json, transcripts.jsonl, *.map, *.gba, savestates.

---

## §3 — Open questions I need answers to

(NOTE: items 1 and 2 were resolved earlier tonight — see Phase 0 of this
overnight prompt. Items 3-5 remain genuinely open and are not answerable
by a coding session.)

1. Was cbcc26c ever live-verified and pushed? — pushed: yes (28 July,
   confirmed via git fetch tonight). Live-verified: still no, only the
   skip sentinel has been confirmed in-game.
2. Was the trainer_defeated one-line fix applied? — No, until tonight;
   now fixed and tested, not yet live-verified.
3. Were the Gemini and Groq API keys ever rotated? — STILL OPEN.
4. Did any of the four faculty emails get sent? — Aarbaz: yes (per
   HANDOVER_5). The other three: still open.
5. Three-year or four-year course? — STILL OPEN, not a coding question.

---

## §4 — The critical path

One ordering. Everything else waits.

TRACK 0: UNBLOCK
  Live-verify cbcc26c -> apply trainer_defeated fix (DONE tonight, code-side)
  -> push (done, to a branch) -> commit the orphaned docs (in progress tonight)
  (unblocks everything downstream)
    -> TRACK A: Evaluation harness (IN PROGRESS tonight)
    -> TRACK B: Academic (Aarbaz/FYP) — not a coding task
    -> TRACK C: Portfolio (video, README, git attribution) — mostly not a coding task tonight
    -> TRACK D: Applications (internships, LinkedIn) — not a coding task

Tracks A-D run in parallel after Track 0. Track D is the most time-sensitive
(rolling applications, open now). Track B is the highest leverage (one
email). Track A is the most work and is the one that changes what the
project *is* — and is what tonight's overnight session is building.

---

## §5 — TRACK 0: Unblock (this week, ~3 hours)

(NOTE: 0.1-0.2 covered by Phase 0 of tonight's prompt. 0.3 requires
Abhishek at the emulator — NOT something this overnight session can do.
0.4 is a branch push tonight, final merge to main is Abhishek's call.
0.5 is Phase 1.5 of tonight's prompt. 0.6 is a manual dashboard task.)

**0.1 — Review and verify cbcc26c.**
  git show cbcc26c --stat
  git show cbcc26c -- lua/mgba_hook.lua
  python run_all_tests.py            # expect 16 passed (now 19+ after tonight)

**0.2 — Apply the trainer_defeated fix** (if not already applied).
This is a hook edit. Savestate first, full mGBA restart.

**0.3 — Live verification, savestate first (Shift+F1).** Five checks:
a sign, the PC, a defeated trainer's post-battle line, Nurse Joy x4
consecutive, and a trainer outside the lookup table. REQUIRES THE ACTUAL
EMULATOR — cannot be done by this overnight cloud session.

**0.4 — Push.** Only after all five confirm clean — Abhishek's call, not
tonight's branch-only work.

**0.5 — Commit the orphaned docs.** This is Phase 1.5 of tonight's prompt,
scoped down to four technical/planning docs rather than all six originally
listed here (the other two — demo script and OBS setup — are personal
production material, deliberately left out of an unattended run).

**0.6 — Rotate the API keys** if not already done. Manual dashboard task,
not something this session can verify or do.

---

## §6 — TRACK A: Thicken the AI layer

This is the substantive work — what tonight's overnight session is building.
Full technical spec in LIVING_HOENN_EVAL_HARNESS_SPEC.md (embedded in
Phase 1 of tonight's prompt).

**The reframe that matters:** the AI layer isn't thin because there's no
training in it. It's thin because there's no *claim being tested*.

### A1 — Evaluation harness (2-3 sessions) — IN PROGRESS tonight
Programmatic metrics against a frozen eval set.

### A2 — Ablations (1 session, once A1 exists) — NOT tonight, needs a live backend
### A3 — Cheap wins, now measurable (1-2 sessions) — NOT tonight
### A4 — Best-of-N (1 session) — NOT tonight
### A5 — Retrieval vs. static extraction (2 sessions) — NOT tonight
### A6 — Distillation (the capstone, only if A1-A5 are done) — NOT tonight, and requires careful VRAM/model-format planning (3B student, not 8B)

**Ordering is not caution.** Each step makes the next cheap and its results
interpretable.

---

## §7 — TRACK B: Academic formalisation

**One action, highest leverage in the entire plan: send the Aarbaz
supervision email.** DONE per HANDOVER_5 — sent 3 September with demo.
Not a coding task; nothing for this overnight session to do here beyond
what's already been noted.

---

## §8 — TRACK C: Portfolio surface

1. **Fix git attribution.** Explicitly OUT OF SCOPE for this overnight
   session — irreversible history rewrite, never to be attempted
   unattended.
2. **Rewrite the README.** Mostly done in an earlier session tonight
   already (doc audit pass before this overnight run).
3. **Finish the recording.** Not a coding task.
4. **Annotate the stale docs** per §2. Mostly done already tonight.

---

## §9 — TRACK D: Applications and LinkedIn

Not a coding task. Full detail in LINKEDIN_STRATEGY.md (deliberately not
committed by this overnight session — personal career content).

---

## §10 — The eight-week shape

(Reference only — a scheduling document, not something a coding session
acts on. See the original for the full week-by-week table.)

---

## §11 — Explicitly parked, with reasons

- **Quest engine revival** — archive it. Competes with Track A for the
  same hours; reintroduces the highest-bug-density subsystem.
- **Full 400-map rollout** — unblocked by Track 0, but do it *after* A1
  so you can measure whether more coverage actually improves grounding.
  NOT tonight's task even though Track 0 is now unblocked — ordering
  still matters, and tonight is building A1, not starting the rollout.
- **Phase C** (EV/IV dialogue, story-event reactivity, roamer hints) —
  verified feasible, zero code. Good post-dissertation features. Not now.
- **PokeNav two-way calls** — deferred by design.
- **Phase E distribution** (.exe, ROM fingerprinting, mobile) — mobile
  is verified impossible without forking mGBA. Park indefinitely.
- **Item ball fanfare re-test** — cosmetic, still open, low priority.
- **species_names.lua load** — cosmetic only. Fix opportunistically.
- **SUPERSEDED.md** — glance at it next time in the repo root; origin
  still unclear.

---

## §12 — The single sentence

**Live-verify cbcc26c, send the Aarbaz email, start applying — then build
the evaluation harness.** The email is sent. The evaluation harness is
what tonight's overnight session builds. Live verification of cbcc26c
still needs Abhishek at the machine — no cloud session can do that part.
