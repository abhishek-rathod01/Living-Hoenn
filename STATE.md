# STATE.md — overnight session live state

**Branch:** `overnight/harness-and-audit` (also mirrored to
`claude/overnight-harness-audit-wtd1rm`, the harness-designated branch).
**Never touched:** `main`.

**Session started:** 2026-09-04 (cloud session, `CLAUDE_CODE_REMOTE=true`).
No emulator, no ROM, no Ollama. Nothing below is live-verified in-game.

---

## Current phase

**Phase 2 — first pass DONE.** (Phases 0, 1, 1.5 done, see below.)

---

## Phase log

### Phase 0 — CHARMAP/SPECIES/TRAINER_ID_BY_KEY load-path bug — DONE

**Confirmed the bug reproduces before touching anything.** `run_all_tests.py`
from the repo root crashed:

```
Traceback (most recent call last):
  File "/home/user/Living-Hoenn/run_all_tests.py", line 829, in <module>
    t_encode_unmapped_glyphs()
  File "/home/user/Living-Hoenn/run_all_tests.py", line 589, in t_encode_unmapped_glyphs
    assert b[2] == 0xD2 and b[3] == 0x00 and b[4] == 0xD3, [hex(x) for x in b]
AssertionError: ['0xfc', '0xf', '0x0', '0x0', '0x0', '0xfb', '0xff']
```

All-zero body bytes = `CHARMAP` was `{}`. Root cause exactly as briefed.

**Fix, two additive layers:**

1. `lua/mgba_hook.lua` — `loadTable()` now tries `"lua/" .. relPath` between
   the absolute Windows path and the bare relative name. On the real machine
   the absolute path still wins on the first attempt, so real-machine
   behaviour is unchanged.
2. `run_all_tests.py` — new `_in_lua_dir()` contextmanager (`os.chdir(LUA)`,
   restored in a `finally`). Applied at all five lupa load sites: `t_lua`,
   `t_encode_unmapped_glyphs`, `t_hook_choice`,
   `t_hook_skip_and_trainer_flag`, `t_trainer_defeated_tristate`.

The briefed warning was checked and is correct: the lupa tests execute the
hook as an in-memory string via `lua.execute()`, so `debug.getinfo()` has no
real file path to introspect. CWD is the only available lever.

**Verification (a) — from the repo root:**

```
19 passed, 0 failed, 0 skipped
```

**Verification (b) — via full path from an unrelated directory:**

```
$ cd /tmp/.../scratchpad/elsewhere
$ python /home/user/Living-Hoenn/run_all_tests.py
  [PASS] lua syntax (all 6 files compile)
  [PASS] encodeEmerald unmapped multi-byte glyph -- one clean fallback byte,
         no locale-dependent word-split corruption
  [PASS] hook choice loop (A press -> choice:1 over the wire)
  [PASS] hook skip sentinel (zero writes for signs) + Jasmine trainer-flag read
  [PASS] trainer_defeated tri-state (unknown NPC omits the field, not 0)

19 passed, 0 failed, 0 skipped
```

**Verification (c) — direct table-size probe, the strongest of the three.**
Rather than trusting that the assertions pass, this counts the entries
actually loaded into the three tables under three different CWDs:

```
cwd=repo root  (new layer-1 path)        SPECIES,CHARMAP,TRAINER = 386,312,14
cwd=lua/       (old bare-relative)       SPECIES,CHARMAP,TRAINER = 386,312,14
cwd=/          (neither: expect 0,0,0)   SPECIES,CHARMAP,TRAINER = 0,0,0
```

Before the fix the repo-root row read `0,0,0` — that is the whole bug. The
`cwd=/` row still reads `0,0,0`; that is the pre-existing designed
"paste inline" fallback, not a regression, and it is why the silent-`{}`
diagnostic gap is logged in REVIEW_QUEUE.md rather than papered over.

**Environment note:** `lupa` and `ollama` were not installed in this cloud
container, so the baseline run reported 15 tests, not 19 (5 lupa tests
crashed/skipped, 1 failed on a missing `ollama` import). Both were pip-installed
by hand. There is no `requirements.txt`, so `scripts/claude-setup.sh` had
nothing to install. Logged for Phase 2.

---

### Phase 1 — evaluation harness — DONE (structurally)

`docs/EVAL_HARNESS_SPEC.md` committed first (it existed only outside the repo;
confirmed absent from `git log --all`). Everything under `eval/` implements it.

**Built and tested:**

| File | What |
|---|---|
| `eval/species_lexicon.py` | Species vocabulary, parsed from the generated `lua/species_names.lua`. 386 names. Never hand-written. |
| `eval/dataset.py` | Frozen eval-set builder, seeded (`SEED=20260904`). |
| `eval/eval_set.json` | 200 entries, hash `ff185eadf75eba7f`. npc 90, object 25, service 23, sign 30, trainer 32. |
| `eval/metrics/grounding.py` | M1a possession claims, M1b out-of-context mentions. |
| `eval/metrics/constraints.py` | M2: fourth_wall, offers_transaction, role_break, format, non_ascii. |
| `eval/metrics/repetition.py` | M3, 4-gram Jaccard vs the previous k=3 lines per NPC. |
| `eval/metrics/skip.py` | M4, skip-sentinel correctness (bridge half only). |
| `eval/test_metrics.py` | 32 unit tests. Every M2 rule has a true positive AND a true negative, per spec section 7. |
| `eval/run_eval.py` | Entry point, all five C0-C4 ablation conditions. |

`run_all_tests.py` is now **20 passed, 0 failed, 0 skipped** (was 19;
`t_eval_metrics` is new and runs the 32 metric tests in-process).

**Deliberately NOT built:** `eval/metrics/latency.py` (M5) needs a live
backend to time; `eval/metrics/judge.py` (M6) needs a hosted judge model
independent of the model under test. Neither is reachable from this cloud VM.

**Bugs caught in my own code before they shipped** (recorded because the
pattern matters more than the fixes):
1. `species_lexicon.normalize` collapsed both Nidoran genders onto one key and
   returned the male form for both. Now mapped to `f`/`m` before punctuation
   is stripped, with an import-time guard that raises on any future collision.
2. The M2 word cap was `> 35`. The bridge prompt says "under 35 words", so 35
   is already a violation; it is now `>= 35`.
3. A full echo run scored the vanilla Devon Scope line as a fourth-wall
   violation, because `{PLAYER}` contains the word "player" and the bridge had
   echoed Nintendo's own text. Fixed twice: M2 strips `{...}` control codes,
   and passthrough replies leave the M1-M3 denominator.
4. The neutral `"..."` fallback was counted as generated prose, padding the
   denominator with 22 lines that cannot violate anything.

Items 3 and 4 were found by RUNNING the harness, not by reading it. That is
the argument for the reply-kind census below.

**End-to-end evidence (echo backend, 200 entries):**

```
144 generated + 30 skip sentinel + 22 neutral fallback + 4 passthrough = 200
M4 skip correctness   100.0% on exactly the 30 sign entries
M3 repetition rate     29.5%   (expected: echo returns an identical line)
M1a violation rate      0.0%   (expected: echo never names a Pokemon)
```

These numbers describe the ECHO backend, i.e. canned text. They are a proof
that the plumbing measures something, **not** a quality claim about any model.

**5 sample entries** for the spec section 7 review, which nobody was awake to
do — logged as R4 in REVIEW_QUEUE.md. Two are reproduced here; run
`python eval/dataset.py --sample 5` for all five:

```
built 200 entries  seed=20260904  hash=ff185eadf75eba7f
strata: {'npc': 90, 'object': 25, 'service': 23, 'sign': 30, 'trainer': 32}

------------------------------------------------------------------------
{
  "id": "eval_0000",
  "stratum": "npc",
  "player_state": "early_rookie",
  "context": {
    "npc_id": 1,
    "map_group": 0,
    "map_num": 1,
    "original_line": "Whew… I'm just bushed… I hiked over from MAUVILLE CITY. But, boy, this city's huge. If I'd known this, I would've ridden my BIKE here.",
    "party": [
      "Torchic:8"
    ],
    "badges": 0,
    "game_clear": 0,
    "trainer_defeated": null
  },
  "ground_truth": {
    "is_trainer": false,
    "trainer_party": [],
    "player_party_species": [
      "Torchic"
    ],
    "archetype_hint": null,
    "map_name": "SlateportCity",
    "vanilla_lines": [
      "Hey! Are you watching? Am I on TV?",
      "Whew… I'm just bushed… I hiked over from MAUVILLE CITY. But, boy, this city's huge. If I'd known this, I would've ridden my BIKE here."
    ],
    "object_type": "person",
    "expect_skip": false
  }
}

------------------------------------------------------------------------
{
  "id": "eval_0001",
  "stratum": "npc",
  "player_state": "early_ordinary",
  "context": {
    "npc_id": 10,
    "map_group": 0,
    "map_num": 1,
    "original_line": "GABBY: I see, I see. You've had a most invaluable experience…",
    "party": [
      "Marshtomp:19",
      "Zigzagoon:12",
      "Taillow:14"
    ],
    "badges": 2,
    "game_clear": 0,
    "trainer_defeated": null
  },
  "ground_truth": {
    "is_trainer": false,
    "trainer_party": [],
    "player_party_species": [
      "Marshtomp",
      "Zigzagoon",
      "Taillow"
    ],
    "archetype_hint": null,
    "map_name": "SlateportCity",
    "vanilla_lines": [
      "GABBY: I see, I see. You've had a most invaluable experience…"
    ],
    "object_type": "person",
    "expect_skip": false
  }
}

```

**What still needs a local machine (none of it possible from this VM):**
- A real run: `python eval/run_eval.py --backend ollama --model qwen3:8b`
- M5 latency and M6 judge implementations
- Spec section 4 calibration: hand-label 50 lines from `transcripts.jsonl`
  (gitignored, absent in a cloud clone), then report the harness's own
  precision/recall/F1 and drop any rule under ~0.8 precision. **Until this is
  done, no M2 rate belongs in the README** — see R7.
- The five-condition ablation grid, and the caveat in R6 about C0/C1 also
  disabling the object-type gate.

---

### Phase 1.5 — orphaned docs — DONE

`docs/LIVING_HOENN_HANDOVER_3.md`, `_4.md`, `_5.md` and
`docs/LIVING_HOENN_MASTER_PLAN.md` committed verbatim. Confirmed absent from
`git log --all` beforehand. Their knowingly-stale passages carry inline NOTE
annotations rather than silent rewrites — they are historical records.

Deliberately NOT committed: `LIVING_HOENN_EMAILS.md`,
`LIVING_HOENN_TECHNICAL_STANDPOINT.md`, `LINKEDIN_STRATEGY.md`, the
screen-only run of show. Personal and career content naming real third
parties; an unattended agent should not be what publishes those.

---

### Phase 2 — repo audit — FIRST PASS DONE

**Bucket A — fixed, each its own commit, each mutation-tested:**

| Commit | What |
|---|---|
| `20d9192` | Persona-designer failure degraded to `"..."` with NOTHING logged, while the identical chatter failure logged. Now both report a reason. |
| `1dad6bb` | A failing Lua test aborted the whole suite: later tests never ran, the summary line and exit code were never reached. Now recorded and counted. |
| `acc5462` | No `requirements.txt`, so the cloud setup hook installed nothing and the suite reported a misleading 15 tests. |
| `742f781` | Stale test counts in README, CLAUDE.md, AGENTS.md, HOME_SETUP, cloud-and-local rules. All said 19 or 15; all now 21 and tell the reader to check `0 skipped`. |
| `825758f` | The "hardened JSON parser" — a headline README claim — had no test at all. |
| `da68d4c` | The gift fanfare gate `_is_obtain_box`, on the live default path, had no test. |

`run_all_tests.py` is now **23 passed, 0 failed, 0 skipped** (was 19 at
session start).

**Hardcoded-path grep, as specifically requested.** 12 hits for
`C:/Users/abhis` / `C:\Users\abhis`. **None fixed, and that is the correct
outcome, not a skipped task:**
- `lua/mgba_hook.lua` (3) — the intended real-machine path, and the first
  thing `loadTable` tries. Phase 0 added fallbacks around it. Changing it
  would break the machine it is for.
- `extraction/merge_npc_tables.py` (1) — `extraction/` is out of scope.
- `CLAUDE.md` / `AGENTS.md` (1 each) — a `cd` in Abhishek's own
  often-used-commands notes. Correct as written.
- `docs/*` (4), `.claude/rules/cloud-and-local.md` (1) — historical records
  and an illustrative table cell.

**Claims checked and found TRUE** (recorded so nobody re-checks them):
- Every headline number is exact: 103 NPCs, 5 maps, 185 dialogue lines,
  16 trainers, 377 items, 482 maps, 66 trainer classes.
- `bridge_server.py --echo` really does still work, as ACTION_PLAN claims.
  Started it, connected a socket, got a reply back.
- Empty persona fields are NOT a silent failure — clipping drops them into
  the existing "missing field(s)" diagnostic. This was my hypothesis and it
  was wrong; testing it is what turned it up.
- No TODO, FIXME, XXX or HACK comments anywhere in the repo.
- No orphaned modules: every top-level file is referenced somewhere.

**Bucket B — logged, not touched:** R6 (C0/C1 ablation also disables the
object gate), R7 (M2 rules uncalibrated), R8 (nothing in CI runs the suite),
R9 (legacy bridge untested but working), R10 (SUPERSEDED.md resolved).

---

## Next

Phase 3 — one more full pass for anything the first pass's categories missed.

## Blockers

None. Pushes are being batched to the end of the session at Abhishek's
request (a mid-run push needs interactive approval, which stalls an
unattended session). Commits are local and continuous; nothing is lost if the
VM survives, and Phase 0 plus the spec are already on origin from two earlier
pushes.
