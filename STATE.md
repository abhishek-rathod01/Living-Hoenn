# STATE.md — overnight session live state

**Branch:** `overnight/harness-and-audit` (also mirrored to
`claude/overnight-harness-audit-wtd1rm`, the harness-designated branch).
**Never touched:** `main`.

**Session started:** 2026-09-04 (cloud session, `CLAUDE_CODE_REMOTE=true`).
No emulator, no ROM, no Ollama. Nothing below is live-verified in-game.

---

## Current phase

**Phase 0 — DONE.**

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

## Next

Phase 1 — build the evaluation harness per the spec embedded in the session
prompt (`docs/EVAL_HARNESS_SPEC.md` to be committed first).

## Blockers

None so far.
