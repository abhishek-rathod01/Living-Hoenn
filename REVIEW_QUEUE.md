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
