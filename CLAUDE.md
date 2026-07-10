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

## TextInputHost.exe freeze (learned this session)
- Symptom: all mouse clicks stop landing system-wide, keyboard still partly
  works. Cause: textinputhost.exe hangs after Win+C (Copilot) or Win+V
  (Clipboard History) opens its panel — a known Windows 11 24H2 bug, not a
  security block on automation. It would freeze a physical user's mouse too.
- Immediate fix: Task Manager (Ctrl+Shift+Esc) or
  `taskkill /IM textinputhost.exe /F` from an ordinary (non-admin) shell —
  it is NOT elevated, don't assume it needs admin rights without checking.
- Permanent prevention: Settings > System > Clipboard > Clipboard History
  OFF. Settings > Bluetooth & devices (or Personalization > Text input) >
  Copilot key/shortcut OFF.
- Standing rule: treat any confident technical explanation for a failure
  as an unverified hypothesis until backed by an actual check.

## Remote monitoring (learned this session)
- AnyDesk set up for unattended access. Interactive Access set to "Never
  show incoming session requests" (requires Unattended Access password set
  first — verify the button reads "Remove password", meaning one is set).
- PC power plan set to never sleep while plugged in — Wake-on-LAN is
  unreliable over weak/cellular connections (confirmed via AnyDesk's own
  docs plus independent user reports of WoL failing remotely).

## Ollama keep-alive (learned this session)
- Default: Ollama unloads a model from memory 5 minutes after the last
  request (confirmed via Ollama's own FAQ and its Go source). This is
  controlled by OLLAMA_KEEP_ALIVE, default 5m, set to -1 for indefinite.
- Setting this in a terminal session does nothing — the Ollama server runs
  as its own process with its own environment. Must be set as an actual
  Windows environment variable, then Ollama fully quit (system tray, not
  just the window closed) and relaunched to pick it up.
- Verify via `ollama ps`: the UNTIL column should read "Forever", not a
  countdown.

## Current frontier
Live LLM dialogue is CONFIRMED on real hardware (persona-driven, reload-safe,
stale-reply-guarded -- see mgba_hook v4). Python layer and Lua logic fully
tested (run_all_tests: 13/13). Quest mode remains hardware-unexercised and is
intentionally parked; dialogue_bridge_server.py is the default entry point.
Next: per-conversation "chatter" for already-known NPCs, decomp-mined NPC
knowledge base from data/maps/*/scripts.inc, multi-box dialogue via 0xFB,
PokeNav two-way calls (Phase 3, after injection timing stays stable).
