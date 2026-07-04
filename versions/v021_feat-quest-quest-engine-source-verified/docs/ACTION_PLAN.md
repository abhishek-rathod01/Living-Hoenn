# ACTION PLAN — build order, step by step

Do these in order. Each phase has a clear "done when" so you never debug two
unknowns at once. Phases 0–1 need no decomp work; the address work starts at 2.

---

## Phase 0 — Prove the Python + LLM half (at your PC, ~15 min)
No emulator yet. This validates everything that's already built and tested.

1. Install Ollama → https://ollama.com/download
2. `ollama pull qwen2.5:7b`   (your RTX 3060 6 GB runs this on-GPU)
   `ollama pull llama3.2:3b`  (fast, for iteration)
3. `pip install ollama`
4. `python step1_dialogue_ollama.py`  → you see generated dialogue
5. Two terminals:
   - `python bridge_server.py --echo`   (then re-run WITHOUT --echo for real LLM)
   - `python mock_mgba_client.py`
   → dialogue comes back for each fake event

**Done when:** the mock client prints LLM dialogue. The entire non-emulator half
is now confirmed working on your machine.
(Optional: set MODEL = "qwen2.5:7b" in step1_dialogue_ollama.py once pulled.)

---

## Phase 1 — Emulator connects to the bridge (no game data yet)

1. Install mGBA 0.10+ → https://mgba.io/downloads.html
2. Open your Emerald ROM.
3. `bridge_server.py` running (echo mode is fine).
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
3. `bridge_server.py` running (real LLM, not echo).
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
