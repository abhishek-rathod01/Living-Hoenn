# HOME SETUP — the complete walkthrough

Follow top to bottom. Every step says what to run and what you should see.
Where two sources exist for a fact, cross-check both (the report shows how each
offset was verified — hold new info to the same standard).

---

## 1. Install (one-time, ~30 min + pokeemerald build time)

**Python 3.10+** — you likely have it. Then:
```
pip install ollama
pip install lupa        # optional: enables the Lua checks in run_all_tests.py
```

**Ollama** — https://ollama.com/download → install → then:
```
ollama pull qwen2.5:7b      # main model: personas + quests (~5 GB, fits your 6 GB GPU)
ollama pull llama3.2        # small model for fast iteration (~2 GB)
ollama run qwen2.5:7b "say hi"    # smoke test, then /bye
ollama ps                   # PROCESSOR column should say "100% GPU"
```
If `ollama ps` shows a CPU/GPU split, use `qwen2.5:7b-instruct-q4_0` or fall
back to `llama3.2`.

**mGBA 0.10 or newer** — https://mgba.io/downloads.html. Must be 0.10+ (that's
when Lua scripting + sockets landed). Check: Tools menu should show
"Scripting…".

**pokeemerald** (for your `.map` file):
```
git clone https://github.com/pret/pokeemerald
```
Then follow its INSTALL.md for your OS (needs devkitARM/agbcc — the repo's
instructions are current; budget 30–60 min first time). The build produces
**pokeemerald.map** — that file is why we're building.
*Path B (no build):* for a vanilla US Emerald ROM the addresses are documented
online (e.g. datacrystal). If you go this route, cross-check every address
against TWO independent pages before trusting it, and note vanilla != your
own rebuilt ROM.

**Your ROM:** a legally dumped Pokémon Emerald `.gba` from your own cartridge.

---

## 2. Get the project onto the PC

Download `pokemon-llm-bridge-with-history.zip` from the chat → unzip. Inside
`gitrepo/` is a real git repo (24+ commits). First command, always:
```
cd gitrepo
python run_all_tests.py
```
Expected: `6 passed, 0 failed` (5 if you skipped lupa). If this passes, the
entire Python layer works on your machine — any later failure is emulator/
address territory, not code.

**Convenience:** copy `bridge/items_table.py, quest_engine.py,
persona_engine.py, step1_dialogue_ollama.py, quest_bridge_server.py,
mock_mgba_client.py` and `run_all_tests.py` into one working folder, or just
run from `bridge/` (imports are same-directory).

---

## 3. Phase 0 — prove the pipeline, no emulator (10 min)

Terminal 1:
```
python quest_bridge_server.py --echo
```
Terminal 2:
```
python mock_mgba_client.py
```
Expected transcript: quest offered → reminder → berries "picked" → NPC takes 2
Oran Berries + gives 1 Potion → thanks. That is the ENTIRE quest lifecycle.

Then kill the server, restart WITHOUT `--echo` (Ollama must be running) and run
the mock again — now a persona and quest are invented by qwen2.5:7b. Run it
twice: the personality stays identical (that's `npc_profiles.json` doing its
job). Delete `quests.json`/`npc_profiles.json` any time to reset the world.

---

## 4. Phase 2 — addresses (the first emulator step)

From your pokeemerald build directory:
```
grep -w gPlayerParty pokeemerald.map
grep -w gPlayerPartyCount pokeemerald.map
```
Each prints a hex address like `0x02024284  gPlayerParty`. Put those two into
`lua/party_reader.lua` (top of file), put `species_names.lua` in the SAME
folder, open your ROM in mGBA, load a save with a team, then
Tools → Scripting… → File → Load script → `party_reader.lua`.

Expected: a "Party Reader" buffer listing your real team with correct names and
levels, refreshing live. Garbage or `#0` = wrong address, nothing else (the
logic is pre-verified). Fix before proceeding.

Then grep the remaining six:
```
grep -w gStringVar4 pokeemerald.map
grep -w gSaveBlock1Ptr pokeemerald.map
grep -w gSaveBlock2Ptr pokeemerald.map
grep -w gSpecialVar_LastTalked pokeemerald.map
grep -w sTextPrinters pokeemerald.map
grep -w sFieldMessageBoxMode pokeemerald.map
```
(The last two are statics — if `-w` misses them, grep without `-w`; they may be
listed with file scope near text.o / field_message_box.o.)

---

## 5. Phases 3+4 — the real thing

1. Fill all 8 `ADDR_*` values at the top of `lua/mgba_hook.lua`.
2. Keep `mgba_hook.lua`, `species_names.lua`, `charmap.lua` in one folder.
   (`dofile` resolves relative to mGBA's working directory — if the console
   warns it couldn't load them, paste each table inline where the warning says.)
3. **SAVESTATE FIRST** (Shift+F1). Item/flag writes touch real save memory;
   a savestate makes every experiment reversible. Do this every session.
4. Terminal: `python quest_bridge_server.py --echo` (echo first — always debug
   plumbing and prose separately).
5. mGBA: load ROM → load `mgba_hook.lua` → console says "connected to bridge".
6. Walk to any NPC and talk.

Expected: box opens blank → bridge terminal shows the context arrive (npc id,
your party, bag, badges) → box fills with the quest intro. Go get 2 Oran
Berries → talk again → berries leave your bag, a Potion appears, completion
line shows. **That moment is your portfolio demo.** Then swap to the real
model (no `--echo`) for LLM personas.

The one expected rough edge: injection *timing*. If text flickers, double-
prints, or shows the original line first, the fix lives in `onFrame`/
`restartPrinter` ordering — delay the restart by a frame or two. This is the
known-unproven step; everything around it is pre-verified.

---

## 6. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Hook: "no bridge at 127.0.0.1:8888" | Server not running / firewall → start server first; allow localhost |
| Party Reader shows garbage | Wrong address → re-grep; confirm you built the ROM you're running |
| Names show as `#282` etc. | species_names.lua not loaded → same folder or paste inline |
| Box blanks then "..." after ~10 s | Bridge up but LLM stalled → check Ollama; echo mode to isolate |
| Reply arrives, box stays blank | sTextPrinters/gStringVar4 address wrong, or timing (see §5) |
| Items don't appear/wrong counts | gSaveBlock2Ptr wrong (encryption key) → verify; reload savestate |
| mGBA console: "couldn't dofile" | Working-directory issue → paste tables inline |
| Bridge crashes on script reload | Shouldn't (tested) — if it does, capture the traceback |
| Same NPC changes personality | npc_profiles.json deleted/moved → keep it next to the server |

**If stuck, gather:** mGBA scripting console output, bridge terminal output,
the exact `.map` lines for your 8 symbols. That triple identifies almost any
failure.

---

## 7. Ship it

Demo recording: OBS or phone; show a talk → quest → fetch → reward loop, then
`npc_profiles.json` in an editor to prove pinned personas, then one glimpse of
the bridge terminal. 60–90 seconds is plenty.

GitHub (no tokens in any chat, ever): create the repo on github.com in your
browser → Add file → Upload files → drag the `gitrepo` folder contents. Or,
from the PC, `git remote add origin <url> && git push -u origin main` —
credential typed in YOUR terminal only. The commit history is part of the
portfolio piece: it shows real bugs found, diagnosed, and fixed.
