# Living Hoenn
### an AI-powered Pokémon Emerald — runtime LLM dialogue, quests & a world that reacts

NPCs in Pokémon Emerald speak **LLM-generated dialogue live during emulation**,
carry **pinned personalities** derived from their vanilla lines, and offer
**LLM-designed side quests** with real item rewards — all driven by a local
model, wired into the decompiled engine's actual internals (not screenshots).

```
 mGBA + Emerald ROM                          Python                 local LLM
┌─────────────────────┐  TCP, newline JSON ┌──────────────────┐   ┌───────────┐
│ lua/mgba_hook.lua   │ ── game state ───► │ quest_bridge_    │ ─►│ Ollama    │
│  trigger: field msg │    npc/map/party/  │ server.py        │   │ qwen2.5:7b│
│  reads RAM (party,  │    bag/badges      │  personas (once  │   └───────────┘
│  bag, flags, npc id)│ ◄─ "acts|dialogue"─│  per NPC) +      │
│  executes actions,  │                    │  quest engine +  │
│  injects text       │                    │  validation gate │
└─────────────────────┘                    └──────────────────┘
```

**Safety rule that makes it work:** the LLM designs quests/personas as strict
JSON, validated against a source-verified item whitelist (Master Ball is
denylisted); free model text NEVER drives memory writes.

## Start here
0. **docs/ARCHITECTURE.md** — the full educational walkthrough of how Emerald,
   mGBA, and this system work. The best single file in the repo.

1. `python run_all_tests.py` — proves the whole Python layer on your machine.
2. **docs/HOME_SETUP.md** — the complete walkthrough: downloads, build, every
   command, expected outputs, troubleshooting.
3. docs/VERIFICATION_REPORT.md — every memory offset with HOW it was verified.
4. docs/ACTION_PLAN.md — the phased build order.

## Files
| File | Role |
|---|---|
| bridge/quest_bridge_server.py | Main server: personas + quests (`--echo` = no model) |
| bridge/quest_engine.py | Quest state machine + validation gate |
| bridge/persona_engine.py | Pinned per-NPC personality cards |
| bridge/bridge_server.py | Minimal dialogue-only server (simpler fallback) |
| bridge/step1_dialogue_ollama.py | Prompt building + Ollama call |
| bridge/mock_mgba_client.py | Full quest demo, no emulator needed |
| bridge/items_table.py | Item IDs generated from pokeemerald source |
| lua/mgba_hook.lua | Emulator side: triggers, reads, actions, injection |
| lua/party_reader.lua | Address validator (run this before the hook) |
| lua/species_names.lua, lua/charmap.lua | Generated from game source |
| run_all_tests.py | One-command regression suite |

## Status (honest)
- ✅ Python layer: fully tested (engine, personas, sockets, protocol).
- ✅ Lua logic: verified against simulated hardware (encrypted bag round-trip,
  flag math, species decode across all 24 orderings, timeout recovery).
- ✅ Every offset/symbol verified against pokeemerald + mGBA source.
- ⬜ Unproven on real hardware: Phase 3 injection *timing* (text printer
  re-render) — the one step that needs live tuning. Everything else should
  light up once the 8 `ADDR_*` values are filled from your `pokeemerald.map`.

Models: **qwen2.5:7b** (fits a 6 GB GPU fully) for personas/quests;
llama3.2:3b for fast plumbing iteration. Requires mGBA 0.10+, Python 3.10+,
Ollama, and a legally dumped Emerald ROM. Prior art exists for FireRed with a
similar socket architecture; this project's differentiator is the
decomp-verified method (see VERIFICATION_REPORT.md).
