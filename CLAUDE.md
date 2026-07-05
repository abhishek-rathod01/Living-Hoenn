# CLAUDE.md — project context for Claude Code sessions

You are working on an **AI-powered Pokémon Emerald bridge**: mGBA runs a Lua
hook that detects NPC dialogue, ships game state over TCP to a Python bridge,
which uses a local LLM (Ollama) to generate persona-driven dialogue and
validated side quests, then injects text and item rewards back into the
running game.

## Read these before doing anything
1. `docs/HOME_SETUP.md` — the phased runbook (what's done, what's next)
2. `docs/VERIFICATION_REPORT.md` — every memory offset + HOW it was verified
3. `docs/ACTION_PLAN.md` — build phases and current status

## Commands
- `python run_all_tests.py` — full regression, no emulator/LLM needed. Run
  this FIRST in any session and after any change. Exit 0 = healthy.
- `python bridge/quest_bridge_server.py --echo` — quest bridge, no model
- `python bridge/mock_mgba_client.py` — full quest lifecycle demo, no emulator

## Hard rules (do not violate)
- **Verify against source, not memory.** Any new memory offset, symbol, or
  game mechanic must be grepped from the local `pokeemerald` clone (or mGBA
  source) before use, then cross-checked a second way (compile a struct, test
  a decoder, or find a second source). This project's entire method is
  source-verified facts; keep it that way.
  - **Unattended/remote sessions must be fully non-interactive.** Every shell
  command that can prompt (pacman, apt, npm, etc.) must carry its
  non-interactive flag explicitly (`--noconfirm`, `-y`, etc.) — never rely on
  a default being safe. Long-running commands must redirect output to a log
  file (e.g. `command 2>&1 | tee somefile.log`) so progress is checkable
  without attaching to the session. This rule exists because two earlier
  sessions hung indefinitely on an unanswered pacman `[Y/n]` prompt.
- **Never request, read, echo, or store credentials** (GitHub tokens, API
  keys). Pushes happen with credentials typed by the user in their own
  terminal only.
- **Savestate before any test that writes game memory** (items, flags,
  dialogue). Remind the user every session.
- **LLM output never drives memory writes directly.** Quests/personas must
  pass `quest_engine.validate_quest` / `persona_engine.validate_persona`.
  The reward denylist (Master Ball etc.) in `items_table.py` is intentional.
- **Lua must stay 5.1-portable**: no native bitwise operators (`~ & | << >>`)
  anywhere in `lua/` — mGBA may link Lua 5.1/5.2/LuaJIT where they are
  load-time syntax errors. Use the existing `u32()`/`bxor()` helpers.
- **Don't hand-edit generated files** (`lua/species_names.lua`,
  `lua/charmap.lua`, `bridge/items_table.py`) — regenerate from pokeemerald
  source (generation method is in the git history / report).
- **`ADDR_*` values come only from the user's own `pokeemerald.map`** (or,
  for a vanilla ROM, from two independent documentation sources that agree).
  Never invent or "remember" addresses.
- Commit style: atomic commits, imperative messages, and for fixes include
  the BUG/FIX/verification pattern used throughout this repo's history.

## Current frontier
Python layer and Lua logic are fully tested (see run_all_tests + history).
The one hardware-unproven step is Phase 3 **injection timing** (text-printer
re-render in `lua/mgba_hook.lua`) — expect to tune when the printer restart
fires. The user must be able to SEE the mGBA window for that step (they use
remote desktop when away); everything else is terminal-drivable.
