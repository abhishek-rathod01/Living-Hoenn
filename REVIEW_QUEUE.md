# REVIEW_QUEUE.md — needs Abhishek's eyes

Written by the unattended overnight session on branch
`overnight/harness-and-audit`. Nothing here was acted on; every entry is a
decision, a risk, or an uncertainty deliberately left for a human.

Ordering is roughly by importance, not by discovery time.

---

## R1 — Branch name differs from the one the harness assigned

**Not a code issue; read this first so the branch situation is not confusing.**

The session prompt's first instruction was
`git checkout -b overnight/harness-and-audit`. The Claude Code harness had
independently assigned a different development branch,
`claude/overnight-harness-audit-wtd1rm`, and had already checked it out.

**What I did:** created and worked on `overnight/harness-and-audit` as
instructed, and pushed the identical commits to *both* branch names so
whichever one you look for exists and is current. Neither is `main`; `main`
was never checked out, pushed to, or merged into.

**What you may want to do:** delete whichever branch you do not want. They
point at the same commits, so deleting either loses nothing.

---

## R2 — `loadTable()` still fails silently outside mGBA (root cause only half-addressed)

**Confidence: high that this is real. Deliberately not fixed.**

Phase 0 fixed the *path resolution*. It did not fix the *silence*. If all
three `dofile` attempts fail, `loadTable()` calls `console:warn(...)` and
returns `{}`. Outside mGBA, `console` is a test stub whose `warn` is a no-op,
so the failure produces no output anywhere — which is exactly why this bug
survived undetected long enough to reach a live recording session.

Verified directly: with CWD set to `/`, the three tables load as
`SPECIES=0, CHARMAP=0, TRAINER_ID_BY_KEY=0` and nothing is printed.

**Why I did not fix it:** making `loadTable()` hard-error on an empty table
changes documented behaviour. The "paste the table inline instead" fallback is
an intentional escape hatch documented in the hook's own warning string, and
I cannot verify from here whether you have ever relied on it on the real
machine. Turning a soft degrade into a hard failure in the live game-memory
hook is not an unattended call.

**Suggested fix, if you agree:** keep returning `{}` but also set a module-level
flag, and have the hook refuse to *encode* (rather than refuse to load) while
`CHARMAP` is empty — an empty charmap makes `encodeEmerald` emit `0x00` for
every character, which is worse than emitting nothing. A one-line guard at the
top of `encodeEmerald` would do it.

---

## R3 — Five Lua tests are invoked outside `check()`, so one failure aborts the whole run

**Confidence: high, directly observed. Fix is Bucket A but flagged here too
because it changes what a green run means.**

In `run_all_tests.py`'s `__main__` block, 14 tests go through `check()` (which
catches, records, and continues) but the five lupa tests are called bare:

```python
t_lua()
t_encode_unmapped_glyphs()
t_hook_choice()
t_hook_skip_and_trainer_flag()
t_trainer_defeated_tristate()
```

Observed consequence this session: `t_encode_unmapped_glyphs` raised, the
process died with a traceback, and the three tests after it never ran and were
never reported as anything. The summary line and the exit code were never
reached either — so the run failed *without* printing `N passed, M failed`.

This is triaged in the Phase 2 section of STATE.md; see SESSION_REPORT.md for
whether it was fixed.

---

## R4 — Eval-set sample entries have NOT been human-reviewed

Spec §7 requires showing the eval-set builder's output on 5 sample entries
*before* generating all ~200. Nobody was awake to review them.

**What I did instead:** wrote the 5 samples into STATE.md, then generated the
full set anyway so the rest of Phase 1 was not blocked.

**What this means:** `eval/eval_set.json` is committed and frozen, but it is
frozen *unreviewed*. Read the 5 samples in STATE.md before you trust any number
the harness produces from it. If the samples are wrong, regenerate — do not
hand-edit the JSON.

---

## R5 — No `requirements.txt`, so the cloud setup hook installs nothing

`scripts/claude-setup.sh` installs Python dependencies only if
`requirements.txt` or `pyproject.toml` exists. Neither does. Consequence
observed this session: `lupa` and `ollama` were both absent, so the first
`run_all_tests.py` run reported a misleading 15-test result (5 Lua tests
crashed or skipped, `t_prompt` failed on `ModuleNotFoundError: ollama`).

Triaged as Bucket A; see SESSION_REPORT.md for whether it was fixed and what
was pinned.

---

## R6 — C0/C1 ablation conditions also disable the object-type gate, not just grounding

**Confidence: high that the behaviour is real. It is a design judgment call,
so it was not "fixed".**

Spec section 6 defines C0 and C1 as turning off the mined `original_line` and
the trainer grounding. In the bridge, all three of those things plus the
**object-type gate** come from the same source: the mined table. So
`_mined_for("C0", ...)` hands `handle_request` an empty table, and the
object-type gate stops firing along with everything else.

Observed directly: a 60-entry echo run under C4 produces vanilla passthroughs
for item balls and berry trees; the same run under C0 and C1 produces zero,
because those objects now fall through to the chatter path and get a
generated line instead.

**Why this matters for the ablation:** C0 is therefore not a clean "no
grounding" baseline. It is "no grounding *and* no object gating". If C0 scores
worse than C4, part of that gap is the object gate, not the grounding, and
attributing all of it to grounding would overstate the grounding's value —
which is the direction of error the spec's own "be prepared for an unwelcome
result" warning is about.

**Two defensible options, and I did not want to pick one unattended:**
1. Keep it as is, and report C0 as "no mined table at all". Honest, simplest,
   but the ablation attributes the object gate's effect to grounding.
2. Keep the object-type gate on in every condition and vary only the three
   prompt-content flags. Cleaner attribution, but it means C0 is no longer a
   true "bridge with nothing mined" baseline.

I lean toward option 2 for the published ablation, with option 1 reported
alongside as a separate row. That is a call about what the dissertation
claims, not a code cleanup, so it is yours.

---

## R7 — The M2 rule set is UNCALIBRATED, so its rates are not yet trustworthy

Spec section 4 is explicit that a detector nobody validated is the same
failure mode as the bug this harness exists to catch, and requires
hand-labelling 50 lines from `transcripts.jsonl`, then reporting the
harness's own precision, recall and F1, dropping any rule below ~0.8
precision.

**None of that happened, and it could not have.** `transcripts.jsonl` is
gitignored, so it does not exist in a cloud clone, and the hand-labelling is
explicitly your hour of work, not an agent's.

**What this means concretely:** every M2 number the harness currently prints
is an uncalibrated rate. Two rules are already visibly suspect by inspection:

- **`fourth_wall`** matches the bare words "game" and "player", which the spec
  itself lists. One false positive was already found and fixed (the vanilla
  `{PLAYER}` placeholder), but an NPC innocently saying "a game of tag" would
  still fire it.
- **`role_break`** covers exactly one archetype pair (healer offering to
  battle), so its recall is very low by construction. That is deliberate per
  the spec ("small and precise rather than broad and wrong"), but the number
  must be read as "healers offering battles", never as "role breaks".

Do not publish any M2 rate in the README until section 4's calibration has
actually been done.

---

## R8 — Nothing in CI runs `run_all_tests.py`

`.github/workflows/claude.yml` is the repository's only workflow, and it does
one thing: respond to an `@claude` mention. There is no workflow that runs the
test suite. A push that breaks all 23 tests would go unnoticed until somebody
ran them by hand.

**Why I did not just add one.** I cannot execute GitHub Actions from this VM,
so I would be committing a workflow file whose correctness I had asserted
rather than demonstrated — the precise habit this project has spent sessions
correcting. Enabling CI also spends Actions minutes on every push, which is
your decision, not an unattended agent's.

**Suggested workflow, if you want it.** Untested, and it should be treated as
a draft until a real run goes green:

```yaml
name: tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python run_all_tests.py
```

The suite exits non-zero on failure (verified this session), so no extra
assertion step is needed. Worth adding a grep for `0 skipped` too: without
lupa the Lua tests skip and the suite still exits 0.

---

## R9 — `bridge/bridge_server.py` is a documented fallback with zero test coverage

README calls it the "minimal dialogue server (simplest fallback)" and
`docs/ACTION_PLAN.md` says twice that it "also still works". Nothing imports
it and nothing tests it.

**I checked the claim rather than assuming it, and it is TRUE.** Started
`python bridge_server.py --echo`, connected a socket, sent a game-state
payload, and got back:

```
[echo] So, sailor here. That Torchic:8 looks tough. Let's battle!
```

So this is not a bug report. It is a note that the documented claim is
currently accurate but unprotected: `make_reply` and `serve_one_client` have
no test, so the next change to the shared protocol could silently break the
documented fallback.

**Not fixed because** the cheap fix (a socket regression test) adds real
wall-clock time to every suite run for a legacy path nobody uses, and I did
not want to make that trade for you unattended. If you would rather retire
the file than test it, that is probably the better answer — but retiring it
means editing README and ACTION_PLAN too, which is a documented-behaviour
change and therefore Bucket B by definition.

---

## R10 — `SUPERSEDED.md`'s origin, flagged as unclear in HANDOVER_3, is resolved

Not an action item — recorded so it stops being re-raised. HANDOVER_3 §4 and
MASTER_PLAN §11 both ask someone to "glance at it next session; origin still
unclear".

I read it. It is a short, coherent, deliberate note explaining that
`step1_dialogue_generator.py` (the original Anthropic-API dialogue harness)
was intentionally excluded from the repo in favour of
`bridge/step1_dialogue_ollama.py`, to keep the core loop free of a paid API
dependency. It is correctly named and it belongs where it is. Nothing to do.
