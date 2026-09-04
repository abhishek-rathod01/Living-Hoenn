# LIVING HOENN — HANDOVER 5
### Session date: 2-3 September 2026 (ran past midnight)
### Compiled at end of session. Supersedes HANDOVER_4 for state; MASTER_PLAN remains the planning document.

**Session headline:** The Aarbaz supervision email was **SENT** with a
16-minute demo attached. That was the highest-value unsent item in the project
and it had been outstanding for roughly six weeks. Additionally: the skip
sentinel was confirmed working live in-game for the first time since 21 July,
two new bugs were found and diagnosed, and a formal supervision route via
Safia Barikzai was identified.

---

## §1 — What actually happened this session

### 1.1 Documents produced (6 new files)

| File | Purpose |
|---|---|
| LIVING_HOENN_TECHNICAL_STANDPOINT.md | Honest engineering assessment, interview defence pack, FYP proposal skeleton |
| LINKEDIN_STRATEGY.md | Profile rebuild, draft copy, visibility strategy, application timing |
| LIVING_HOENN_MASTER_PLAN.md | Integrated plan reconciling all prior sessions; **the current planning document** |
| LIVING_HOENN_EVAL_HARNESS_SPEC.md | Implementable spec for Track A1 — hand this to Claude Code |
| LIVING_HOENN_EMAILS.md | Four faculty emails |
| LIVING_HOENN_SCREEN_ONLY_RUN_OF_SHOW.md | Recording runbook (screen-only variant) |

### 1.2 The recording

- **Format changed** from camera+PiP to **screen-only**. This removed three
  blockers at once: Poly Studio auto-framing, lighting/one-sitting constraint,
  camera framing drift. Only the Aarbaz Section 1 camera take from the prior
  session is now orphaned footage.
- **Structure improved mid-session** on Abhishek's initiative: added a
  **before/after controlled comparison** — same ROM, same savestate, same NPC,
  vanilla line first, then load the Lua hook, then the generated line. One
  variable changed. This is methodologically the strongest thing in the video
  and it was his idea, not mine.
- **Recorded from cold start** including bridge startup and mGBA launch.
- **Final runtime: ~16 minutes.** Longer than the 6-8 minute target. Judged
  acceptable *for Aarbaz specifically* (domain peer who asked for it); **not**
  acceptable for senior admin or LinkedIn.
- **Uploaded** to LSBU OneDrive. Link is in the sent email.

### 1.3 Email status — CHANGED THIS SESSION

| Recipient | Status |
|---|---|
| **Aarbaz Alam** | **SENT** with demo link, apology for delay, supervision ask, both his conditions addressed |
| **Safia Barikzai** | Drafted, **not sent** — send next |
| **Dr Daqing Chen** | Courtesy note drafted, **not sent** — send after Safia |
| **Dr Rory Summerley** | Drafted, not sent. Reframed: decline hardware, ask for games students as human raters for eval M6 |
| **Dr Brahim El Boudani** | Drafted, not sent. Methodology questions only, deliberately no resource ask |

---

## §2 — NEW INFORMATION recovered this session

### 2.1 The Safia Barikzai route — previously unknown to me

**[NEW]** An exchange with Dr Chen occurred outside any conversation I have
access to. Sequence per Abhishek's account:

1. Abhishek emailed Chen about workstation access
2. Chen replied "ask your supervisor"
3. Abhishek clarified it's solo self-directed work with no supervisor
4. **Chen referred him to Safia Barikzai to have a supervisor assigned**

**Why this matters:** this is a referral from the UG Course Leader, not a cold
approach. That's institutional standing you didn't have. The Safia email must
**lead with Chen's name in the first line** — it's the reason it gets read.

**Correct spelling: Barikzai**, not Barzai. **[UNVERIFIED]** Her exact title
(Mrs/Ms/Dr) has not been confirmed — check the LSBU staff directory before
sending. Getting a senior person's title wrong in a first email is an
avoidable own goal.

**Two routes now run in parallel:** informal (Aarbaz agrees directly) and
formal (Safia assigns someone). These are complementary, not redundant. If
Aarbaz agrees first, the formal process ratifies a choice already made rather
than assigning a stranger.

### 2.2 The repo path was wrong in every document

**[CONFIRMED THIS SESSION]** The path recorded in CLAUDE.md and every
handover — C:\\Users\\abhis\\Desktop\\Living hoenn\\living-hoenn-COMPLETE-backup\\ — **is not
the repo root.** Running git commands there fails with "not a git repository".

**Actual working path (confirmed — the bridge launched successfully from it):**

C:\\Users\\abhis\\Desktop\\Living hoenn\\living-hoenn-COMPLETE-backup\\living-hoenn-COMPLETE-backup\\gitrepo

Git Bash form:
/c/Users/abhis/Desktop/Living hoenn/living-hoenn-COMPLETE-backup/living-hoenn-COMPLETE-backup/gitrepo

Note living-hoenn-COMPLETE-backup appears **twice**, with gitrepo inside.
**Every document containing the short path needs correcting.** This wasted
real time this session.

NOTE (added by tonight's session, since this is now stale): this path issue
was re-checked directly against the live repo and found to already be
correct in the current CLAUDE.md/AGENTS.md — likely fixed in an
undocumented session between this handover and now. Do not re-fix it
unless you independently find it's actually still wrong.

---

## §3 — NEW BUGS found this session

### 3.1 Non-ASCII / CJK leakage with no encoder fallback — **[NEW, CONFIRMED VISUALLY]**

**Observed:** an NPC line rendered as "did you need anything from the  , or
shall I fetch your usual" with a heart glyph — with a **gap**, a stray heart glyph, and the tail
("order?") **missing entirely**. The bridge log showed the model had emitted
Chinese characters for "shelf" (contextually correct for a Pokemart).

**Two stacked defects:**

**(a) Generation side.** qwen3 is Alibaba's model, trained with heavy Chinese
data. Code-switching for lower-frequency concepts is known behaviour for this
family, and temperature 0.85 makes it likelier. **Not a defect in your code.**

**(b) Render side — the more important one.** encodeEmerald() has **no
defined behaviour for unmappable input**. NOTE: tonight's session found the
real root cause is NOT the charmap fallback itself (that already safely
falls back to 0x00) but a locale-dependent word-splitter bug (%S pattern
class), already fixed and tested tonight.

**Fix, two layers:**
- Bridge (Python, lower stakes): reject and regenerate on non-ASCII output,
  max 2 retries, then canned fallback. DONE tonight in a different form
  (per-request try/except fallback to skip sentinel).
- Encoder (Lua, higher stakes): give unmappable characters a **defined**
  fallback — map to ? or drop — rather than letting arbitrary bytes reach
  control codes. DONE tonight (word-splitter fix, not charmap fallback).

**Free eval metric:** add **non-ASCII leakage rate** to M2 in the harness spec.
Detection is any(ord(c) > 127 for c in line) minus legitimate charmap
symbols. Trivial, 100% precision, no calibration needed, and it measures
something confirmed to occur.

### 3.2 Bridge exits on a single failed Ollama call — **[NEW, CONFIRMED]**

**Observed mid-recording:**
[dialogue-bridge] -> [error] ConnectionError: Failed to connect to Ollama...
[dialogue-bridge] shutting down

Not a crash — a clean exit. One failed model call propagated past the
connection loop into the shutdown path. **There is no error isolation between
"this request failed" and "stop the server."** Wrong failure mode for
something demoed live; it nearly cost the shoot.

**Two small fixes:**
- **Preflight at startup** — ping http://127.0.0.1:11434/api/tags before
  listening; fail loudly with "Ollama is not running — start it with ollama
  serve" instead of accepting a connection and dying on first use.
- **Catch per-request, not per-process** — a failed model call should return
  the fallback line to mGBA and log it while the server keeps listening.
Both DONE and tested as of tonight's session.

**Root cause of the outage itself:** quitting the Ollama **tray app** takes the
background server down with it. ollama serve (foreground) or relaunching the
tray app restores it.

---

## §4 — POSITIVE result: skip sentinel confirmed live

**[VERIFIED LIVE]** The hook log showed:
[hook] reply: <<SKIP>>
[hook] skip sentinel received -- leaving vanilla text untouched

This is **cbcc26c item 1 confirmed in-game for the first time since 21 July**.
The three-fix commit has been stalled on live verification for six weeks; one
third of it is now verified.

**Still unverified from cbcc26c:** trainer defeated-flag grounding, and
chatter continuity/variety. The full five-check protocol (sign, PC, defeated
trainer, Nurse Joy x4, out-of-table trainer) was **not** completed — recording
took priority. NOTE (tonight's session): the trainer_defeated code bug itself
IS now fixed and tested (was NOT actually fixed as of this handover, despite
cbcc26c's commit message claiming it was) — but live verification still
has not happened.

---

## §5 — FILE STALENESS AUDIT (full, all 17 project files)

### Current and trustworthy
| File | Note |
|---|---|
| living-hoenn-VERIFICATION_REPORT.md | Accurate. These facts don't decay. |
| LIVING_HOENN_HANDOVER_3.md | Current technical reference. Committed to repo as of tonight. |
| LIVING_HOENN_HANDOVER_4.md | Current for outreach. Superseded for planning by MASTER_PLAN. |
| LIVING_HOENN_RUN_OF_SHOW.md | Valid but assumes camera+PiP — superseded by the screen-only version for this shoot. |
| LIVING_HOENN_DEMO_SCRIPT.md | Content still good; format superseded. |
| LIVING_HOENN_PORTFOLIO_SCRIPT.md | Unshot. Still valid. |
| LIVING_HOENN_STARTUP_COMMANDS.txt | May contain the wrong repo path — check before using. |
| claude_LIVING_HOENN_OBS_RECORDING_SETUP.md | Current and accurate. Confirmed correct this session. |

### STALE — needs fixing (NOTE: most of this table was already fixed in a
doc-audit session earlier tonight, before this overnight run started —
do not redo it, this is left here for historical completeness only)
| File | What's wrong |
|---|---|
| dialogue_bridge_server.py | Was severely stale, already fixed tonight (docstring corrected). |
| living-hoenn-README.md | Was leading with quest engine, already fixed tonight. |
| living-hoenn-ACTION_PLAN.md | Was listing done phases as to-do, already fixed tonight. |
| living-hoenn-HOME_SETUP.md | Was showing old model install instructions, already fixed tonight. |
| living-hoenn-NEXT_CHAT_PROMPT.md | Confirmed this file never existed in the git repo at all — nothing to delete. |
| living-hoenn-CLAUDE.md | Commands section fixed tonight; repo path confirmed already correct. |
| living-hoenn-ARCHITECTURE.md | Quest engine parked-status note added tonight. |

### Historical — correct as history, superseded as state
LIVING_HOENN_HANDOVER.md, LIVING_HOENN_HANDOVER_2.md

### Not in the repo at all — [OPEN]
Confirmed absent from every branch as of the 23 Aug audit: HANDOVER_3 (now
fixed, committed tonight), demo script, startup commands, OBS setup, run of
show, portfolio script — and now also HANDOVER_4, HANDOVER_5, MASTER_PLAN
(all three being committed as part of tonight's run), EVAL_HARNESS_SPEC
(committed tonight), EMAILS, TECHNICAL_STANDPOINT, LINKEDIN_STRATEGY,
screen-only run of show (these last four remain deliberately uncommitted —
personal/career content, not for an unattended agent to commit).

**Gitignored by design but unbacked anywhere:** npc_profiles.json (every
pinned persona — lose it and every NPC gets a new soul), transcripts.jsonl
(the corpus the eval harness needs). **Copy both to OneDrive** — this is a
manual task for Abhishek, not something this session can do.

---

## §6 — Corrections made this session

Recorded so they don't get re-asserted later.

| Prior belief | Correction |
|---|---|
| "Top 5-10 of ~100 applicants" (HANDOVER_4) | Unfalsifiable and varies enormously by role. The qualitative version is defensible; the number isn't. |
| "ROM isn't in the repo so we're legally safe" | Wrong emphasis. The ROM was never the main exposure. extraction/npc_dialogue_table.json holds 185 lines of verbatim Nintendo text and is in the repo. That's the actual grey area. |
| "Fine-tune qwen3:8b to make it more creative" | Wrong on three counts, see original doc for full detail — wrong tooling, wrong VRAM fit, wrong objective. |
| Ollama CLI preload is a valid warm-up | No — CLI defaults differ from the bridge's own runtime settings, achieves nothing. |
| LinkedIn "360Brew runs the feed" | Myth, withdrawn paper, not the live system per LinkedIn's own engineering post. |
| "Record graduate job collapse, ~50%" | Direction confirmed two ways, magnitude disputed between sources. |

---

## §7 — Open questions requiring Abhishek's answer

1. Was cbcc26c ever pushed? — RESOLVED tonight: yes, pushed 28 July, confirmed via git fetch.
2. Was the trainer_defeated line-732 fix applied? — RESOLVED tonight: it was NOT applied as claimed; now actually fixed and tested tonight.
3. Were the Gemini and Groq API keys rotated? — STILL OPEN, not something this session can check.
4. Three-year or four-year course? — STILL OPEN, not a coding question.
5. Did the remaining four cbcc26c live checks pass? — STILL OPEN, requires Abhishek at the machine with the emulator.

---

## §8 — Immediate next actions, ordered (STATUS as of tonight's overnight run)

1. Send Safia Barikzai email — STILL OPEN, not a coding task.
2. Send Dr Chen courtesy note — STILL OPEN, not a coding task.
3. Push everything — code pushed to a branch tonight, not main; final merge is Abhishek's call.
4. Copy npc_profiles.json and transcripts.jsonl to OneDrive — STILL OPEN, manual task.
5. Fix the repo path — confirmed already correct, nothing to do.
6. Complete the four remaining cbcc26c live checks — STILL OPEN, requires the emulator.
7. Fix the two new bugs — DONE tonight, tested.
8. Build the evaluation harness — DONE (structurally) tonight; full run against a live backend still needs Abhishek's machine.

**Deferred but queued:** git author attribution fix — explicitly NOT to be
attempted by this overnight session (irreversible history rewrite).

---

## §9 — On publishability (asked and answered this session)

**Not publishable:** the injection mechanism, substruct decryption, "LLM NPCs" as a concept, the system as an artifact.

**Publishable — one idea:** interactive fiction generated from a decompiled
source tree admits programmatic ground truth for factual claims, and therefore
admits automated evaluation of grounding faithfulness without human raters or
an LLM judge.

**Realistic ceiling:** a workshop paper after A1+A2. Not a main-track venue.

**Current publishable output: zero.** Apparatus plus observation, no data yet — this is exactly what tonight's eval harness build starts to change.
