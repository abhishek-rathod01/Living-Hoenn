# LIVING HOENN — HANDOVER 2 (paste this as the first message in the new chat,
# or point Claude Code at this file and tell it to read it first)

Status tags: **[VERIFIED ×2]** confirmed two independent ways · **[APPLIED,
TESTED]** code changed, tests pass · **[APPLIED, CONFIRMED LIVE]** tested in
the actual running game · **[APPLIED, PENDING LIVE CONFIRM]** committed,
tests pass, but not yet confirmed in-game this session · **[OPEN]** known
issue, not fixed · **[DEFERRED]** deliberately not built yet.

This supersedes LIVING_HOENN_HANDOVER.md (docs/) for anything that conflicts;
that file is still valid background for everything it covers that this one
doesn't repeat (Lua hook v4 fixes, charmap collision fix, backend list, etc).

---

## 1. What happened this session, in order

1. **Bug fix, pushed:** backend exceptions (Gemini 503 etc.) were being
   serialized as raw error text and injected straight into the dialogue box.
   Fixed — `handle_request` now catches exceptions and returns a safe
   fallback line. **[APPLIED, CONFIRMED LIVE]** (seen in the `ServerError:
   503 UNAVAILABLE` screenshot before the fix; not yet re-screenshotted
   after, but the commit is in and tests cover it).
2. **Persona role-lock fix, pushed:** `PERSONA_SYSTEM` now forces well-known
   service roles (Nurse Joy, shop clerk, Officer Jenny, Day Care attendant,
   PC clerk, Move Tutor/Deleter) to their real archetype with hard
   constraints (a healer never battles/trades). `quirk` demoted from
   catchphrase to occasional flavor. **[APPLIED, TESTED]** — not yet
   re-confirmed live after Nurse Joy's cache was cleared (see next item).
3. **Nurse Joy's stale cached persona (key `0:5:19` in `npc_profiles.json`)
   deleted.** Her card predated the fix above, so the fix couldn't apply
   retroactively. **[OPEN — needs live re-test]**: talk to her again and
   confirm no battle offer, in-character healer dialogue only. This was
   never actually confirmed this session — do it first thing.
4. **git hygiene incident:** two live API keys (Gemini, Groq) were pasted
   into this chat and briefly staged in a `CLAUDE.md` diff. **Confirmed via
   `git log --all -S"<exact key string>"` that neither key ever entered git
   history** — caught before commit. Both keys should still be rotated
   regardless (pasted into a chat transcript is its own exposure surface,
   separate from git) — confirm this was actually done; it was advised but
   not verified back to me.
5. **Phase A — decomp-mining pilot: done, verified, committed, pushed.**
   Extracted 103 object events across 5 maps (Slateport City, Fortree City,
   Lilycove City, Route 110, Slateport PC 1F) into
   `extraction/npc_dialogue_table.json`, keyed `map_group:map_num:local_id`.
   185 dialogue lines, 100% resolved from source `.string` blocks by an
   independent parser (not subagent transcription). 16 trainer objects with
   full parties cross-checked against `trainer_parties.h`. 7 gifts detected,
   2 correctly flagged `DYNAMIC` rather than guessed. **I independently
   re-verified Jasmine's entry against live pret/pokeemerald master this
   session** (party, sprite constant, script line) — all correct.
   Commits: `a5dbe3b`, `6fc5065`, `077a59b`, `c22b4db` (line-ending
   normalize + `.claude/` tracking), `efdb97b` (handover doc added).
   **[VERIFIED ×2, hand-checked, committed, pushed]**
6. **Phase B — wire mined data into the bridge (scoped to the 5 pilot
   maps only): done, committed, pushed, NOT yet live-confirmed.**
   Commits `24c735a` (wiring) + `b0cc31e` (tests). 15/15 tests green
   (was 14/14 before). Key behaviors per Claude Code's own report:
   - NPCs outside the 5 mined maps: byte-identical fallback to pre-Phase-B
     behavior (tested).
   - NPCs inside the 5 mined maps: richer grounding (resolved vanilla
     lines capped at 5, gift status, ambient map_type/weather).
   - **Trainer awareness (your explicit choice this session):** trainer
     NPCs get a factual party summary (species + level only, no raw IVs)
     injected as grounding the LLM must acknowledge but can't invent past.
     Jasmine-specific test passes.
   - **Renown tier:** rookie / respected / awed, computed from
     `game_clear` OR `legendary ≥ Lv50` — **the same two triggers ported
     verbatim from the existing (unused-here) `build_world_notes` awe
     logic**, not imported as a module (dialogue bridge stays
     broadcast-free by design). A test pins the two trigger-sets equal.
   - **Honest, load-bearing caveat, verbatim from Claude Code's report:**
     *"the Lua hook has no don't-inject sentinel — `handleReply` writes the
     reply unconditionally. Since the hook is off-limits this session,
     'skip' means echoing the vanilla text re-rendered, possibly with the
     known extra-A-press. A true no-op needs a one-line hook change
     later."* This is a real, not-yet-closed gap. **[OPEN, small, scoped]**
   **[APPLIED, PENDING LIVE CONFIRM — this is the most important open item]**
7. **Nothing in `bridge/dialogue_bridge_server.py` outside these two
   commits, and nothing in `lua/` or the quest engine, was touched** —
   confirmed via `git diff --stat` before each commit. Scope held.
8. **Ollama model swap started:** removed `qwen2.5:7b-instruct-q4_0`,
   `qwen2.5:7b`, `llama3.2:latest`. Installed `qwen3:8b` (verified via
   Ollama's own official library page as the real same-weight-class
   successor; Qwen's own benchmarks claim Qwen3-8B ≈ Qwen2.5-14B quality).
   **[OPEN]**: qwen3 defaults to "thinking mode," which was making replies
   slow. Fix identified but **not yet applied to code**: add `think=False`
   as a sibling kwarg to both `ollama.chat(...)` calls in `make_llm()`
   (persona_designer and chatter), e.g.:
   ```python
   resp = ollama.chat(model=model, think=False, options={...}, messages=[...])
   ```
   Also recommended: `pip install -U ollama --break-system-packages` first,
   since some Ollama/qwen3 version combos have had `think=False` silently
   ignored (seen in real GitHub issues against ollama/ollama). **Verify
   after editing that replies actually got faster and no `<think>` tags
   leak into output** — don't just trust the flag worked.
9. **Party Reader "mismatch" — investigated, was never actually broken.**
   User's screenshot showed `#151`/`#150`/`#410` etc. instead of names.
   **[VERIFIED ×2 this session against live pret/pokeemerald master]**: all
   six species IDs are correct **internal Hoenn indices** (not National Dex
   — this exact trap is already documented in the project's own
   VERIFICATION_REPORT.md). The only real issue is cosmetic: names aren't
   showing because `species_names.lua` isn't loading (same failure mode
   already listed in HOME_SETUP.md's troubleshooting table — check same
   folder, then check console for a `dofile` warning, then paste inline if
   needed). **No decode logic is broken.** Not yet fixed/confirmed by user.
10. **Distribution vision discussed (not started) — call it Phase E.** See
    §4 below.

---

## 2. Immediate next steps, in order (do these before anything else)

1. **Apply the `think=False` fix** to both `ollama.chat()` calls in
   `dialogue_bridge_server.py`'s `make_llm()`. Restart bridge, confirm
   faster replies, confirm no `<think>` leakage into the dialogue box.
2. **Fix `species_names.lua` loading** for Party Reader (cosmetic only,
   not urgent, but cheap): confirm same folder as `party_reader.lua`,
   check console for `dofile` warning, paste inline if needed.
3. **Confirm the two rotated API keys** (Gemini, Groq) were actually
   regenerated at their dashboards — this was advised earlier but never
   confirmed back.
4. **Do the Phase B live verification checklist — this is the one that
   actually matters, everything above is small stuff:**
   - Savestate first (Shift+F1), every time.
   - Talk to **Nurse Joy** (Pokémon Center, key `0:5:19`'s location) —
     confirm no battle offer, no repeated exact quirk phrase, no 4th-wall
     language, in-character healer dialogue.
   - Talk to **Jasmine, Route 110** — confirm her line naturally
     references her real Magnemite/Voltorb party without becoming a stat
     dump.
   - Open a **Route 110 item ball** (Dire Hit / Rare Candy / Elixir,
     entries `0:25:19/20/35`) — confirm fanfare text renders cleanly.
     Specifically watch for double-print or needing an extra A-press,
     given the open "no true skip sentinel" caveat from §1.6.
   - Talk to an **NPC outside the 5 mined maps** — confirm zero regression
     from pre-Phase-B behavior.
   - If reachable, the **rival encounter** (Lilycove or Route 110) —
     confirm it stays generic across the 6 gender×starter variants, never
     claims a specific party.
   - Report back what you actually observe at each step — screenshots of
     mGBA + the bridge terminal together are what actually let me catch
     real issues earlier in this session (the honeymoon-couple and
     Nurse-Joy-PC screenshots were genuinely useful; plain descriptions
     are not as reliable).

Only once all of §2 is confirmed should Phase C, quest-bridge work, or
Phase E distribution work start.

---

## 3. Quest bridge — status, and the plan for fixing it

**What I actually know, verified, as of this handover:** the quest engine
(`quest_bridge_server.py`, `quest_engine.py`) was deliberately parked, not
because it was found broken in this session, but because — per the
project's own prior documentation — "running quest logic and dialogue
quality simultaneously created too many failure modes to debug in
parallel." The user has now stated it is "very much absolutely broken with
a lot of issues," which is **new information this session did not
independently verify** — no specific bugs were reproduced, reported, or
diagnosed here. Anything below that isn't tagged [VERIFIED] is a
recommendation about *how to find out*, not a diagnosis of what's wrong.

**Known, documented design risk (from ARCHITECTURE.md, not new):** the
REWARDED-state "Thanks again for the help!" trap — once a quest is
complete, the state machine has one more line and then loops on
"after-line" forever, which reads as repetitive/broken if a player revisits
that NPC many times. This is a plausible candidate for at least one of the
"lot of issues," but it's a design limitation, not confirmed as *the*
current issue.

**Recommended first move — diagnose before fixing, same standard as
everything else in this project:**

Suggested first prompt for the next Claude Code session (separate from the
dialogue-bridge work, do this as its own scoped session):

```
Read CLAUDE.md and docs/LIVING_HOENN_HANDOVER.md and
docs/LIVING_HOENN_HANDOVER_2.md fully first.

Do NOT fix anything yet. Run a diagnostic pass on the quest bridge only
(quest_bridge_server.py, quest_engine.py, mock_mgba_client.py) and report,
with source line references for each:

1. Run run_all_tests.py -- which quest-related tests currently pass vs fail,
   if any fail.
2. Start quest_bridge_server.py --echo and run mock_mgba_client.py -- does
   the full quest lifecycle (offer -> reminder -> fetch -> reward) complete
   without errors, matching what HOME_SETUP.md section 3 describes as
   expected?
3. Read quest_engine.py's validate_quest and the state machine
   (ACTIVE -> REWARDED -> after-line) end to end. List every state
   transition and flag anything that looks like a dead end, an infinite
   loop, a missing guard, or a place where LLM output could reach
   emu:write-equivalent action grammar without passing the validation gate.
4. Compare quest_bridge_server.py's structure against the now-more-mature
   dialogue_bridge_server.py (hardened JSON parsing via _json_of/
   _finish_persona, the three-backend structure, the exception-safety fix
   from this session) -- list every place quest_bridge_server.py is missing
   an equivalent safeguard.
5. Do NOT assume old claims are still true. If ACTION_PLAN.md or
   ARCHITECTURE.md claims something is "tested" or "verified," re-check it
   against the actual current code, not the doc's word for it.

Output: a numbered list of concrete, reproduced-or-quoted-source issues --
not general impressions -- so the next session can prioritize real fixes
instead of guessing.
```

**Why diagnostic-first:** the dialogue bridge's robustness (which the user
correctly identifies as strong) came specifically from *iterating against
real observed failures* (the raw-error injection, the stale persona cache,
the EOS-vs-PROMPT_CLEAR bug) — not from a blind rewrite. The quest engine
deserves the same treatment: find out what's actually wrong, with evidence,
before deciding whether to patch it, partially rebuild it, or leave it
parked and extend the dialogue-only bridge with quest-like features
instead (a real third option worth considering once the diagnostic is in —
e.g., could "gift-aware" dialogue from the Phase A mining data cover some
of what quests were meant to do, without reintroducing the REWARDED-state
trap at all?).

---

## 4. Distribution vision (Phase E) — discussed, not started

Two goals raised this session, both are real and roughly achievable, with
one hard technical constraint discovered:

**Mobile/remote play — mGBA has no native Android app; only a RetroArch
core exists, and the Lua scripting console is a desktop-Qt feature
[VERIFIED ×2: GBAtemp community + mgba.io scripting docs].** So "phone runs
the game+hook, PC runs the LLM" is not currently possible without forking
mGBA. Real options instead, ascending effort:
1. **Streaming today, zero code changes:** PC runs everything, phone is a
   screen+controller via Moonlight/Sunshine, Parsec, or the AnyDesk setup
   already configured.
2. **Remote bridge for friends:** the Lua socket just needs to point at a
   non-localhost address -- one line. Real work is that the protocol has
   no auth and plaintext JSON right now; tunnel via Tailscale for friends
   (no code changes, encrypted, no open ports) rather than exposing raw.
   One favorable point: the dialogue-only bridge emits no actions at all,
   so a compromised/malicious bridge can only ever send text, never write
   game memory -- this makes the current architecture safer to expose than
   the quest-engine version would be.
3. **Public hosted version:** same as #2 but on a rented VM; only worth it
   if there's real demand. Groq (not local Ollama) is the right backend
   choice here given its speed and your FIFO stale-reply guard's low
   tolerance for slow replies.

**.exe packaging for non-technical users -- the key unlock:** ship against
a **vanilla US Emerald ROM** (fingerprint via game code + CRC at startup),
whose addresses are fixed and only need verifying once (two independent
sources), instead of requiring every user to build pokeemerald and grep
their own .map file. Then: PyInstaller-frozen bridge (`--onefile`, bundle
`npc_dialogue_table.json` + world tables via `--add-data`), a portable
mGBA build alongside (MPL-2.0, redistribution permitted -- verify exact
license terms once before shipping), and a small launcher (pick ROM, pick
backend/paste a key, Play). Two open questions before designing this
further: (a) **[HYPOTHESIS, unverified]** whether mGBA supports
auto-loading a Lua script via CLI flag/config, avoiding a manual
Tools -> Scripting step for end users; (b) distributing the mined dialogue
table means distributing verbatim Nintendo text, same gray-zone status as
the pret decomp itself.

**Sequencing recommendation:** finish §2 (Phase B live verification) and
resolve the quest-bridge diagnostic first. Phase E is a real, valuable next
arc, but it's independent of and should not interrupt the dialogue-bridge
work that's mid-verification right now.

---

## 5. Things NOT to repeat / mistakes already made this session

- Never paste API keys into chat, even as part of a diff/log paste. It
  happened once this session (caught, keys not in git history, but still
  a real exposure via the chat transcript itself). Rotate immediately if
  it happens again, don't just "be more careful."
- Multi-command pastes into PowerShell/Git Bash cause garbled
  `Get-Process`/prompt-echo errors (bracket-paste artifacts) -- these are
  cosmetic, not real failures, but paste one command at a time to keep the
  terminal transcript readable and avoid confusion about what actually ran.
- `npc_profiles.json` is gitignored by design (runtime state, not source)
  -- editing/deleting entries in it needs no git commit, ever.
- Don't trust a Claude Code session's own "hand-verified" claim at face
  value -- ask it to name the exact file/line it checked, and ideally
  spot-check one yourself against the real source. This caught nothing
  wrong this session (Phase A's claims held up under independent
  re-verification), but it's the standard, not a one-time check.
- Code passing tests is not the same bar as "confirmed working" -- Phase B
  is a clean example: 15/15 green, fully committed, and still an open item
  until someone actually talks to Jasmine in the running game.

---

## 6. Quick reference -- where things are

- Bridge: `bridge/dialogue_bridge_server.py` (3 backends: ollama/gemini/
  groq; hardened JSON parsing; exception-safe; mined-table-aware for the
  5 pilot maps as of this session)
- Mined data: `extraction/npc_dialogue_table.json`,
  `extraction/COVERAGE_REPORT.md`, `extraction/raw/*.json`
- Personas: `npc_profiles.json` (gitignored, runtime state)
- Hook: `lua/mgba_hook.lua` v4 (untouched this session; the "no skip
  sentinel" gap from §1.6 lives here when someone gets to it)
- Quest engine (parked, diagnostic pending): `bridge/quest_bridge_server.py`,
  `bridge/quest_engine.py`
- Subagent config: `.claude/agents/map-extractor.md` (Sonnet-pinned,
  read-only, used for Phase A -- reusable if the full ~400-map rollout
  happens later)
- Repo: `https://github.com/abhishek-rathod01/Living-Hoenn.git`, branch
  `main`, currently at commit `efdb97b` as of this handover (confirm
  `git log origin/main --oneline -3` hasn't moved since if picking this up
  much later)
