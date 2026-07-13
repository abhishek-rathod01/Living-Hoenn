# Living Hoenn
### an AI-powered Pokémon Emerald — live LLM dialogue, pinned personas & a world that reacts

NPCs in Pokémon Emerald speak **LLM-generated dialogue live during emulation**
and carry **pinned personalities** derived from their vanilla lines — all
driven by a local model, wired into the decompiled engine's actual internals
(not screenshots). **Confirmed working on real hardware:** persona-driven,
contextually-reactive NPC dialogue renders in-game.

```
 mGBA + Emerald ROM                          Python                 local LLM
┌─────────────────────┐  TCP, newline JSON ┌──────────────────┐   ┌───────────┐
│ lua/mgba_hook.lua   │ ── game state ───► │ dialogue_bridge_ │ ─►│ Ollama    │
│  trigger: field msg │    npc/map/party/  │ server.py        │   │ qwen2.5:7b│
│  reads RAM (party,  │    bag/badges      │  personas pinned │   └───────────┘
│  bag, flags, npc id)│ ◄── dialogue ──────│  once per NPC,   │
│  encodes + injects  │                    │  fresh LLM call  │
│  text into the box  │                    │  per conversation│
└─────────────────────┘                    └──────────────────┘
```

**Safety rule that makes it work:** model text is encoded through a
source-verified charmap and injected ONLY as dialogue-box text. Game-state
changes exist solely in the optional quest mode, where the LLM must emit
strict JSON validated against a source-verified item whitelist (Master Ball
is denylisted); free model text NEVER drives memory writes.

## Start here
0. **docs/ARCHITECTURE.md** — the full educational walkthrough of how Emerald,
   mGBA, and this system work. The best single file in the repo.

1. `python run_all_tests.py` — proves the whole Python layer on your machine.
2. **docs/HOME_SETUP.md** — the complete walkthrough: downloads, build, every
   command, expected outputs, troubleshooting.
3. docs/VERIFICATION_REPORT.md — every memory offset with HOW it was verified.
4. docs/ACTION_PLAN.md — the phased build order.
5. docs/POKENAV_ADDRESSES.md — Match Call / PokeNav symbols (Phase 3 prep).

## Files
| File | Role |
|---|---|
| bridge/dialogue_bridge_server.py | **Main server**: dialogue-only, personas pinned via PersonaStore |
| bridge/persona_engine.py | Pinned per-NPC personality cards |
| bridge/step1_dialogue_ollama.py | Prompt building + Ollama call |
| bridge/quest_bridge_server.py | Optional/legacy: personas + quests (`--echo` = no model) |
| bridge/quest_engine.py | Quest state machine + validation gate (used by quest mode) |
| bridge/advisor.py | Professor advisor system |
| bridge/broadcast.py | World reactions: TV news / quiz |
| bridge/world_tables.py | World-reaction data tables |
| bridge/bridge_server.py | Minimal dialogue server (simplest fallback) |
| bridge/mock_mgba_client.py | Full quest demo, no emulator needed |
| bridge/items_table.py | Item IDs generated from pokeemerald source |
| lua/mgba_hook.lua | Emulator side: triggers, reads, encoding, injection (v4) |
| lua/party_reader.lua | Address validator + live party reader (run before the hook) |
| lua/trainer_info.lua | Trainer/save-block reads |
| lua/species_names.lua, lua/charmap.lua | Generated from game source |
| extract_addresses.py | Pulls the ADDR_* values from your pokeemerald.map |
| watchdog.py | Supervisor: restarts the bridge, stops at limit |
| run_all_tests.py | One-command regression suite (13 tests) |

## Status (honest)
- ✅ **Live LLM NPC dialogue confirmed on real hardware** — persona-driven,
  reacts to party/context; injection pipeline is reload-safe and
  stale-reply-guarded (see mgba_hook v4 commit for the debugging story).
- ✅ Python layer: fully tested — `run_all_tests.py`: 13 passed, 0 failed.
- ✅ Lua logic: verified against simulated hardware AND live in-game
  (encrypted bag round-trip, flag math, species decode across all 24
  orderings, timeout recovery, charmap collision resolution).
- ✅ Every offset/symbol verified two independent ways (pokeemerald.map
  cross-checked with arm-none-eabi-nm on the built elf).
- ⬜ Quest mode (item rewards / flag writes) is fully tested in Python +
  simulation but has NOT been exercised on hardware; the dialogue-only
  server is the current default by design.
- Next up: fresh per-conversation "chatter" for known NPCs, a decomp-mined
  NPC knowledge base, multi-box dialogue, PokeNav two-way calls (Phase 3).

Models: **qwen2.5:7b** (fits a 6 GB GPU fully) for personas/quests;
llama3.2:3b for fast plumbing iteration. Requires mGBA 0.10+, Python 3.10+,
Ollama, and a legally dumped Emerald ROM. Prior art exists for FireRed with a
similar socket architecture; this project's differentiator is the
decomp-verified method (see VERIFICATION_REPORT.md).

## License & legal
Code is [MIT licensed](LICENSE). This repository contains **no ROM, no
Nintendo assets, and no copyrighted game data** — you must build pokeemerald
yourself and legally dump your own Emerald cartridge. Not affiliated with or
endorsed by Nintendo, Game Freak, or The Pokémon Company.
