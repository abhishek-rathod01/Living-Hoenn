# File guide — what every tracked file does

mGBA runs a Lua hook (`lua/mgba_hook.lua`, v4) that notices when an NPC's text box opens, reads game state from
emulator memory, and sends it as JSON over TCP (127.0.0.1:8888) to a Python bridge
(`bridge/dialogue_bridge_server.py`). The bridge asks an LLM (Ollama by default, Gemini or Groq optional) for an
in-character line, using a pinned persona per NPC plus a table mined from the decomp, and sends the text back; the
hook encodes it into Emerald's character set and re-renders the box. A quest system exists but is parked, not part
of the default path. Everything below is a tracked file; the "Status" column marks what is on the live path, what is
parked, and what is legacy.

## Repo root
| File | What it is |
|---|---|
| `README.md` | Overview: what it is, features, file table, status, how to start |
| `CLAUDE.md` | Project rules and context loaded by Claude Code sessions (commands, hard rules, current frontier) |
| `AGENTS.md` | Same content as `CLAUDE.md`, for Codex; the two are kept identical by hand |
| `LICENSE` | MIT licence |
| `requirements.txt` | `lupa` (runs the Lua hook inside tests) and the `ollama` client; optional `google-genai`, `groq` |
| `.gitignore` | Keeps ROMs, saves, logs, the persona store, transcripts and demo traces out of git |
| `run_all_tests.py` | One command that runs all the checks (no emulator or model needed) |
| `watchdog.py` | Restarts a crashed command with backoff; logs its own events |
| `extract_addresses.py` | Reads a `pokeemerald.map`/`.sym` and prints the Lua `ADDR_*` block |
| `START_DEMO.bat`, `STOP_DEMO.bat`, `RESTART_BRIDGE.bat` | Double-click launchers that call `demo/demo.ps1` |
| `REVIEW_QUEUE.md` | Open decisions and uncertainties for the maintainer (append-only) |
| `SESSION_REPORT.md` | Report of the 2026-09-04 overnight run |
| `STATE.md` | Live log of that overnight run |
| `SUPERSEDED.md` | Lists the old Anthropic-API dialogue script that is deliberately not tracked |

## `bridge/` — the Python side
| File | What it does | Status |
|---|---|---|
| `dialogue_bridge_server.py` | TCP server; persona designer and chatter prompts, three backends, mined-table grounding, skip sentinel, timeout, trace, Ollama preflight | live |
| `persona_engine.py` | Stores one validated persona card per NPC (`npc_profiles.json`) plus the last two lines said | live |
| `world_tables.py` | Generated map-id to area-name and trainer-class tables | live (data) |
| `quest_bridge_server.py` | Older bridge: personas plus LLM-designed quests with item rewards | parked |
| `quest_engine.py` | Quest validation gate and state machine | parked |
| `items_table.py` | Generated item-id table and reward whitelist | parked (data) |
| `advisor.py` | "Ask the Professor" progression tips (SELECT held) | parked |
| `broadcast.py` | TV news bulletins and "Who's that Pokemon?" quiz | parked |
| `bridge_server.py` | Minimal dialogue-only server, the original fallback | legacy |
| `step1_dialogue_ollama.py` | Original step-1 prompt and Ollama call | legacy |
| `mock_mgba_client.py` | Fake emulator that plays the quest lifecycle against a quest bridge | legacy / demo |

## `lua/` — the emulator side
| File | What it does |
|---|---|
| `mgba_hook.lua` | Hook v4: detects text boxes, reads party/bag/badges/flags, sends context, receives replies, encodes and re-renders text; stale-reply guard and reload guard |
| `party_reader.lua` | Standalone tool to check the party addresses before wiring the full hook |
| `trainer_info.lua` | Reads a trainer's class and name from ROM; groundwork for PokeNav calls, not used yet |
| `trainer_flags.lua` | Generated: Route 110 NPC key to trainer id, used for the already-defeated flag |
| `charmap.lua`, `species_names.lua` | Generated lookup tables (text bytes; internal species names) |

## `eval/` — the evaluation harness
| File | What it does |
|---|---|
| `dataset.py` | Builds the frozen evaluation set from the mined table |
| `eval_set.json` | The frozen set itself (generated; do not hand-edit) |
| `run_eval.py` | Replays the set against a backend under ablation conditions C0 to C4 |
| `species_lexicon.py` | Species vocabulary parsed from `lua/species_names.lua` |
| `metrics/grounding.py` | M1: does the NPC claim Pokemon it does not own |
| `metrics/constraints.py` | M2: fourth-wall breaks, fake offers, role breaks, format, non-ASCII |
| `metrics/repetition.py` | M3: near-repeat lines per NPC |
| `metrics/skip.py` | M4: do signs get the skip sentinel (bridge half only) |
| `metrics/__init__.py`, `runs/.gitkeep` | Package marker; keeps the empty run-output folder |
| `test_metrics.py` | Unit tests for the metrics |

## `extraction/` — the decomp-mined NPC table
| File | What it does |
|---|---|
| `merge_npc_tables.py` | Merges per-map raw files into one table, re-deriving map ids and resolving text from the decomp (needs a local pokeemerald clone) |
| `npc_dialogue_table.json` | The generated table the bridge loads (contains verbatim game text) |
| `raw/raw_*.json` | Per-map extraction output: Fortree, Lilycove, Route 110, Slateport, Slateport Pokemon Center 1F |
| `COVERAGE_REPORT.md` | What the pilot extraction covers and what it could not parse |

## `demo/` — open-day kit
| File | What it does |
|---|---|
| `demo.ps1` | Launcher: Ollama, model preload, tests, bridge under the watchdog, dashboard, mGBA |
| `dashboard.py` | Local web dashboard (port 8890) that follows the bridge's trace file; standard library only |
| `dashboard.html` | The dashboard page (offline, no external requests) |
| `README.md` | How to use the kit, crash-recovery behaviour, troubleshooting |

## `docs/`
| File | What it is |
|---|---|
| `HOME_SETUP.md` | Step-by-step runbook for a local machine |
| `ARCHITECTURE.md` | How the whole system works, with parked-quest sections flagged |
| `ACTION_PLAN.md` | Phased build plan and status |
| `VERIFICATION_REPORT.md` | Every memory offset and symbol, and how it was verified |
| `EVAL_HARNESS_SPEC.md` | Specification for the evaluation harness (metrics M1 to M6, conditions) |
| `POKENAV_ADDRESSES.md` | Symbols for the deferred PokeNav / Match Call idea |
| `CLOUD-NOTES.md` | How the cloud-session setup hook works |
| `FILE_GUIDE.md` | This file |
| `LIVING_HOENN_HANDOVER.md` to `LIVING_HOENN_HANDOVER_5.md` | Five point-in-time session handovers (July to September 2026), each with a dated status note |
| `LIVING_HOENN_MASTER_PLAN.md` | Integrated plan from 1 September 2026 |

## Claude Code and CI configuration
| File | What it does |
|---|---|
| `.claude/rules/cloud-and-local.md` | Rules for working locally versus in a cloud session (generated by claude-cloud-kit) |
| `.claude/settings.json` | Permission allow/deny/ask lists and the SessionStart hook |
| `.claude/agents/map-extractor.md` | Read-only subagent used to extract one map |
| `scripts/claude-setup.sh` | SessionStart hook; installs dependencies only in cloud sessions |
| `.github/workflows/claude.yml` | Responds to `@claude` mentions from the repository owner only |

<!-- last-verified: 2026-10-15 against 5ed3e71 -->
