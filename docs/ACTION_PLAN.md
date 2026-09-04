# ACTION PLAN — build order, step by step

> **STATUS: Phases 0-3 are DONE**, confirmed against git history (verified
> this session, commit 8838b36 is current tip, 73 commits total,
> `run_all_tests.py` 19/19):
> - Phase 0/1 (Python+LLM half, emulator connects): superseded by the
>   dialogue-only bridge, commit `0ee3930` ("feat: add dialogue-only bridge
>   server"). `dialogue_bridge_server.py` is now the actual entry point --
>   `step1_dialogue_ollama.py`/`bridge_server.py` below are the ORIGINAL
>   quest-era files this plan was written against; they still exist in the
>   repo but are legacy, not what a fresh setup should run today.
> - Phase 2 (address validation): the addresses below are long since wired
>   into `mgba_hook.lua` and source-verified (docs/VERIFICATION_REPORT.md).
> - Phase 3 (full hook wired, live on hardware): confirmed real, commit
>   `437b338` ("docs: bring README and CLAUDE.md frontier up to date with
>   hardware-confirmed dialogue"); the hook has since moved to v4
>   (`4de6583`, reload-safe/stale-reply-guarded/wrap-aware).
>
> Since this plan was written: dialogue confirmed on real hardware, quest
> mode parked (not abandoned -- see docs/ARCHITECTURE.md's header note),
> `dialogue_bridge_server.py` is the default, and the decomp-mined NPC table
> (Phase-6-style deferred item) has a working 5-map pilot. The step-by-step
> walkthrough below is kept as-is for historical/setup reference (the
> underlying addresses and logic are still correct), but a NEW setup should
> follow docs/HOME_SETUP.md, which targets the current entry point directly.
> Current state: docs/LIVING_HOENN_HANDOVER.md.


Do these in order. Each phase has a clear "done when" so you never debug two
unknowns at once. Phases 0–1 need no decomp work; the address work starts at 2.

---

## Phase 0 — Prove the Python + LLM half (at your PC, ~15 min)
No emulator yet. This validates everything that's already built and tested.

1. Install Ollama → https://ollama.com/download
2. `ollama pull llama3.2:3b`  (fast, actual default for dialogue_bridge_server.py)
   `ollama pull qwen2.5:7b`   (your RTX 3060 6 GB runs this on-GPU; default for
   the parked quest_bridge_server.py, and a heavier `--model` option for the
   dialogue bridge if you want richer replies)
3. `pip install ollama`
4. Current path: `python bridge/dialogue_bridge_server.py --echo` (no model)
   then drop `--echo` for real LLM dialogue -- this IS the mock/no-emulator
   check now, no separate step1 script needed.
   (Legacy path, still present and working: `python step1_dialogue_ollama.py`
   → generated dialogue; `python bridge_server.py --echo` +
   `python mock_mgba_client.py` in two terminals -- this is what quest mode,
   Phase 4 below, actually uses.)

**Done when:** you see LLM-generated dialogue print without an emulator attached.
The entire non-emulator half is now confirmed working on your machine.

---

## Phase 1 — Emulator connects to the bridge (no game data yet)

1. Install mGBA 0.10+ → https://mgba.io/downloads.html
2. Open your Emerald ROM.
3. `dialogue_bridge_server.py --echo` running (current path; legacy
   `bridge_server.py --echo` also still works, same check).
4. Tools → Scripting… → load `party_reader.lua` (see Phase 2 — it's the first
   thing that reads memory) OR just confirm `mgba_hook.lua` logs "connected to
   bridge".

**Done when:** mGBA's console logs a successful bridge connection.

---

## Phase 2 — Validate addresses with the party reader (FIRST decomp step)

This is the safe on-ramp: prove your addresses before wiring the full loop.

1. Build pokeemerald once (follow its INSTALL.md). This produces `pokeemerald.map`.
2. Grep the two addresses:
   ```
   grep gPlayerParty      pokeemerald.map
   grep gPlayerPartyCount pokeemerald.map
   ```
3. Put them into `party_reader.lua` (ADDR_PLAYER_PARTY, ADDR_PARTY_COUNT).
4. Load `party_reader.lua` in mGBA with a save that has a team.

**Done when:** the "Party Reader" buffer shows your real team with correct names +
levels. (Logic is already test-verified, so correct addresses = correct output.
Garbage = wrong address, nothing else.)

Then grep the remaining symbols for the full hook:
```
grep gStringVar4 gSaveBlock1Ptr sTextPrinters pokeemerald.map
grep sFieldMessageBoxMode pokeemerald.map      # a static; may show file scope
```
Map read (optional enrichment), fully verified offsets:
```
sav1 = read32(gSaveBlock1Ptr); mapGroup = read8(sav1+0x04); mapNum = read8(sav1+0x05)
```

---

## Phase 3 — Wire the full hook (the real thing)

1. Put all `ADDR_*` values into `mgba_hook.lua`.
2. Make sure `species_names.lua` and `charmap.lua` are loadable (same folder, or
   paste inline if your mGBA build can't `dofile`).
3. `dialogue_bridge_server.py` running (real LLM, not echo) -- current path;
   legacy `bridge_server.py` also still works.
4. Load `mgba_hook.lua` in mGBA. Walk up to an NPC and talk.

**Expected flow:** box opens blank → context (your team + the original line) goes to
the bridge → LLM reply comes back → the printer re-renders with the generated text.

**Where trouble will realistically be (all scoped, not unknown):**
- Timing of the blank-then-fill vs the printer. If the re-render flickers or
  double-prints, tune the frame at which `restartPrinter()` fires.
- `sTextPrinters` element: field messages use window 0 → element [0]. If your build
  lays the array differently, confirm the base address points at printer [0].
- Start with ONE cooperative NPC to prove the concept before generalizing.

---

## What's already proven (so you don't re-litigate it)
- Party slot 100 bytes; **level at +84 unencrypted**; species decrypt (key = PID^OTID,
  growth-slot table) — tested on 12,000 synthetic mons.
- Species names use **internal Hoenn ordering** → `species_names.lua` generated from the
  game's own table.
- Charmap → `charmap.lua`, encoder tested (`"Hi!"` → C2 DD AB FF).
- Trigger = `sFieldMessageBoxMode` (0 → non-zero); injection target = `gStringVar4`;
  re-render via `sTextPrinters[0]` currentChar/active/state.
- `party_reader.lua` itself tested end-to-end against simulated memory.

See VERIFICATION_REPORT.md for the details behind each of these.

---

## Phase 4 — LLM quests + pinned personas (BUILT & TESTED, needs Phases 0-3 first)

What exists (all tested against simulated hardware / real sockets):
- `bridge/quest_engine.py` — quest state machine + validation gate (16 tests).
  LLM output NEVER touches memory unvalidated; Master Ball etc. denylisted.
- `bridge/persona_engine.py` — persona cards generated ONCE per NPC, cached in
  npc_profiles.json; same NPC = same personality forever.
- `bridge/quest_bridge_server.py` — drop-in replacement for bridge_server.py.
  `--echo` runs the whole thing with no model.
- `lua/mgba_hook.lua` v3 — sends npc_id/map/badges/bag/party; executes
  take_item / give_item (encrypted, verified round-trip) / set_flag actions.

New symbols to grep in YOUR pokeemerald.map (besides the Phase 2 set):
  gSpecialVar_LastTalked, gSaveBlock2Ptr
Verified constants already coded: bag Items +0x560 (30 slots) / Berries +0x790
(46), ItemSlot {u16 id, u16 qty^key}, key at SaveBlock2+0xAC (lo16), flags at
SaveBlock1+0x1270, badges = flags 0x867-0x86E, game clear = 0x864.

Run order at the PC: Phase 0 unchanged -> Phase 2 party_reader -> fill ALL
ADDR_* in hook v3 -> `python quest_bridge_server.py --echo` -> talk to one NPC
-> expect quest intro; obtain the items; talk again -> reward lands in bag.
Then drop `--echo` for real LLM personas/quests (qwen2.5:7b).

## Continuing without this assistant
Everything needed to proceed is in this repo: VERIFICATION_REPORT.md holds every
offset with HOW it was verified; tests in the commit history show expected
behavior; nothing depends on any particular AI model or vendor. Any capable
assistant (or you alone, with grep) can pick up from the run order above.

---

## Phase 6 — islands, advisor, and what's deliberately deferred

BUILT & TESTED (needs Phases 0-3 first, like everything):
- Sailor island quests: in Lilycove/Slateport (the two verified event-ferry
  harbors), an NPC with no quest offers the next locked island -- fetch quest,
  ticket lands in the KEY ITEMS pocket, harbor flag set, ferry destination
  appears. One island per NPC, never re-offered once unlocked (unlocks bitmask).
- Professor hotline: hold SELECT while talking to any NPC -> deterministic
  badge-aware next-objective tip (curated table; the LLM is not in this path,
  so it cannot hallucinate the walkthrough).

DEFERRED, with the verified pieces already in hand:
- Two-way PokeNav conversations: trigger (sMatchCallState trainerId 0->nonzero),
  buffer (gStringVar4), caller identity (trainer_info.lua), and button input
  (emu:getKey) are all verified -- the remaining work is the on-hardware
  page-flip timing, same class of problem as Phase 3 injection.
- "Battle them from the call": initiating battles from Lua remains
  low-feasibility; the honest route is setting rematch state so the battle
  happens on approach. Not built.
- Real in-game choice MENUS: would require driving the window/menu system; the
  A/B-button pattern replaces it for now.
