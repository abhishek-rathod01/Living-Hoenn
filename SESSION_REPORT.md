# SESSION_REPORT.md — unattended overnight run

> **Status note (2026-10-15, base 38177ea) -- point-in-time report of the
> 2026-09-04 overnight run; the body is kept as written. Superseded or
> re-checked since:**
> - **Test count:** "19 -> 23 passed" is no longer current: `python
>   run_all_tests.py` reports 26 passed, 0 failed, 0 skipped as of 2026-10-15
>   (38177ea; run, and `t_*` functions counted). The 23 -> 26 step is the three
>   tests added with the local-work capture (demo trace, bridge crash recovery,
>   demo dashboard).
> - **"Never touched `extraction/`" / "extraction out of scope"** describes that
>   run only; the 2026-10-15 sync did not edit extraction data either.
> - **R-entries:** R3 (suite abort) and R5 (requirements.txt) were fixed as
>   stated and still hold. R8 (no CI running the suite) is still true: the only
>   workflow is `.github/workflows/claude.yml`. The draft test workflow the
>   table mentions lives inside `REVIEW_QUEUE.md` R8, not as a file. See the
>   later R11-R25 entries in `REVIEW_QUEUE.md`.
> - **"The five live cbcc26c checks" are outstanding** except the sign/skip-
>   sentinel one, which `docs/LIVING_HOENN_HANDOVER_5.md` section 4 records as
>   confirmed in-game (self-reported); the repo records no result for the other
>   four (UNVERIFIABLE FROM THE REPO).
> - **"No orphaned modules"** no longer holds literally: `lua/trainer_info.lua`
>   is not loaded by the hook; the only test touching it is `t_lua`'s compile-only
>   syntax check (`git grep`, 2026-10-15).
> - **Hardcoded-path count** ("12 hits"): `git grep -n -E 'C:[/\]+Users[/\]+abhis'`
>   gives 15 lines in 11 files on 2026-10-15; the number depends on the pattern
>   used, and the code hits (hook, merge script) are unchanged.
> - Still true (re-checked): 103 NPCs, 5 maps, 185 lines, 16 trainers, 377 items,
>   482 maps, 66 trainer classes; 200-entry eval set with hash
>   `ff185eadf75eba7f`; no TODO/FIXME/XXX/HACK comments in code.

**Branch:** `overnight/harness-and-audit` (also pushed to
`claude/overnight-harness-audit-wtd1rm`, the harness-assigned name — same
commits, see R1). **`main` was never checked out, pushed to, or merged into.**

**Environment:** Claude Code cloud session. No emulator, no ROM, no Ollama.

> **Nothing in this report is live-verified.** Every claim below is
> code-verified against the test harness. The five in-game checks from
> cbcc26c still need you at the machine, and no cloud session can do them.

**Test suite: 19 passed at session start → 23 passed, 0 failed, 0 skipped.**
Verified four ways: from the repo root, from an unrelated working directory
by full path, from a virtualenv built only from the new `requirements.txt`,
and with the eval metric tests run standalone (32/32).

---

## What you should do first, in order

1. **Read `REVIEW_QUEUE.md`.** Ten entries, nothing in it was acted on. The
   two that gate real work are **R4** (the frozen eval set was generated
   without the human sample review the spec requires) and **R7** (the M2
   constraint rules are uncalibrated, so no M2 number belongs in the README
   yet).
2. **Run `pip install -r requirements.txt` then `python run_all_tests.py`.**
   Expect `23 passed, 0 failed, 0 skipped`. Check for **`0 skipped`**, not
   just the exit code — without lupa the five Lua tests skip and the suite
   still exits 0.
3. **Do the five live cbcc26c checks** (a sign, the PC, a defeated trainer's
   post-battle line, Nurse Joy four times consecutively, a trainer outside
   the lookup table). Savestate first. This has been outstanding since 21
   July and remains the project's real blocker. **Phase 0 changed
   `lua/mgba_hook.lua`**, so re-check a sign specifically.
4. **Run the eval harness for real:**
   `python eval/run_eval.py --backend ollama --model qwen3:8b`. It has only
   ever been run against the `echo` backend. That produces the project's
   first actual quality numbers.
5. **Decide R6** (whether the C0/C1 ablation conditions should keep the
   object-type gate on) before running the five-condition grid, because it
   changes what the grid's numbers mean.
6. **Merge or delete the branch.** Nothing was merged for you.

---

## What got fixed

Every fix below was mutation-tested: a deliberate defect was injected and the
new test confirmed to catch it. A test that passes alongside working code
proves nothing on its own.

| Commit | Fix |
|---|---|
| `5ef10bd` | **Phase 0.** `SPECIES`/`CHARMAP`/`TRAINER_ID_BY_KEY` silently loaded as `{}` outside one exact machine+CWD. An empty charmap makes `encodeEmerald` emit `0x00` for every character. Two additive layers; real-machine behaviour unchanged. |
| `20d9192` | A persona-designer failure degraded to `"..."` with **nothing logged**, while the identical failure in `chatter()` logged. Both now report a reason. |
| `1dad6bb` | A failing Lua test **aborted the whole suite** — later tests never ran, and the summary line and exit code were never reached. |
| `acc5462` | No `requirements.txt`, so the cloud setup hook installed nothing and the suite reported a misleading 15 tests. |
| `742f781` | Stale test counts in five files (all said 19 or 15). Each now also tells the reader to check `0 skipped`. |
| `825758f` | The "hardened JSON parser", a headline README claim, had **no test at all**. |
| `da68d4c` | The gift fanfare gate `_is_obtain_box`, on the live default path, had no test. |
| `dc0621d` | The Windows-encoding test's docstring claimed to cover "every file-open call in this codebase" but checked **seven hardcoded filenames**, omitting the live default bridge. |
| `35b8d2b` | The Lua syntax check listed its six files instead of discovering them, and announced "all 6 files compile" as a string literal. |

## What got built

| Commit | What |
|---|---|
| `ef9da83` | `docs/EVAL_HARNESS_SPEC.md` — existed only outside the repo, confirmed absent from `git log --all`. |
| `39b0436` | `eval/species_lexicon.py`, generated from `lua/species_names.lua`. 386 names. |
| `48f39a0` | `eval/dataset.py` + frozen `eval/eval_set.json`: 200 entries, hash `ff185eadf75eba7f`. |
| `93666f6` | Metrics M1-M4 with 32 unit tests. Every M2 rule has a true positive **and** a true negative, per spec §7. |
| `3045eea` | `eval/run_eval.py` with all five C0-C4 ablation conditions. |
| `d5d29dc` | The four orphaned handover/planning docs. |

**Deliberately not built:** `latency.py` (M5) needs a live backend to time;
`judge.py` (M6) needs a hosted judge model independent of the model under
test. Neither is reachable from a cloud VM. Writing them blind would have
produced code nobody could verify.

**Deliberately not committed:** `LIVING_HOENN_EMAILS.md`,
`LIVING_HOENN_TECHNICAL_STANDPOINT.md`, `LINKEDIN_STRATEGY.md`, the
screen-only run of show. Personal and career content naming real third
parties; an unattended agent should not be what publishes those.

---

## Four bugs I caught in my own new code before committing

Recorded because the pattern is the point, not the fixes.

1. `species_lexicon.normalize` collapsed both Nidoran genders onto one key and
   returned the male form for both. Now guarded by an import-time collision
   check that raises rather than letting a name silently win.
2. The M2 word cap was `> 35`. The bridge prompt says "under 35 words", so 35
   is already a violation.
3. A full eval run scored the vanilla Devon Scope line as a fourth-wall
   violation, because `{PLAYER}` contains the word "player" and the bridge had
   echoed Nintendo's own text back.
4. The neutral `"..."` fallback was counted as generated prose, padding the
   denominator with 22 lines that cannot violate anything.

Items 3 and 4 were found by **running** the harness, not by reading it.

---

## Claims I checked that turned out TRUE — do not re-check these

- Every headline number is exact: 103 NPCs, 5 maps, 185 dialogue lines,
  16 trainers, 377 items, 482 maps, 66 trainer classes.
- `bridge_server.py --echo` really does still work, as ACTION_PLAN claims.
  Started it, connected a socket, got a reply.
- Empty persona fields are **not** a silent failure. I suspected they were;
  testing showed clipping drops them into the existing "missing field(s)"
  diagnostic. **My hypothesis was wrong.**
- `SUPERSEDED.md`, flagged as "origin unclear" in HANDOVER_3 §4 and
  MASTER_PLAN §11, is a deliberate and correctly-named note. Resolved (R10).
- No TODO/FIXME/XXX/HACK comments anywhere. No orphaned modules.

## The hardcoded-path grep, as requested

12 hits for `C:/Users/abhis` / `C:\Users\abhis`. **None were changed, and
that is the right outcome rather than a skipped task:** three are the
intended real-machine path in `lua/mgba_hook.lua` (the first thing
`loadTable` tries, now with fallbacks around it), one is in `extraction/`
which is out of scope, two are your own `cd` command in the CLAUDE.md and
AGENTS.md notes, and the rest are historical documents. Full list in
`STATE.md`.

---

## What is in REVIEW_QUEUE.md and why

| # | Item | Why not fixed |
|---|---|---|
| R1 | Branch name differs from the harness-assigned one | Both pushed, same commits; delete either |
| R2 | `loadTable` still fails **silently** outside mGBA | Turning a documented soft degrade into a hard failure in the live hook is not an unattended call |
| R3 | (Fixed as `1dad6bb`) | — |
| R4 | **Eval set frozen without the spec-required human sample review** | Nobody was awake. 5 samples are in STATE.md |
| R5 | (Fixed as `acc5462`) | — |
| R6 | **C0/C1 ablation also disables the object-type gate** | A judgment call about what the dissertation claims |
| R7 | **M2 rules uncalibrated** | Needs `transcripts.jsonl` (gitignored, absent here) and your hand-labelling |
| R8 | Nothing in CI runs the suite | I cannot execute Actions from here; a draft workflow is included |
| R9 | Legacy bridge untested but working | Retiring it changes documented behaviour |
| R10 | `SUPERSEDED.md` origin resolved | Informational |

---

## Things I was told not to do, and did not

- Never pushed, merged, or switched to `main`.
- Never touched `quest_engine.py`, `quest_bridge_server.py`, or `extraction/`.
- No git history rewrite, no force push, no author-attribution fix — several
  of tonight's documents mention it; it is irreversible and not an unattended
  task.
- No action on any email or outreach content in those documents.
- No claim of live or in-game verification anywhere.

One deviation worth naming: **pushes were batched to the end of the session**
rather than done per phase, because you told me mid-run that each push needed
interactive approval and was stalling the session. Phase 0 and the spec had
already reached origin before that change.
