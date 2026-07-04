# AI-Powered Pokémon Emerald — Runtime LLM Dialogue Bridge

An LLM generates NPC dialogue **live, during emulation**, based on real game
state (your party, location, the NPC you're talking to). The player plays
Emerald normally; the words NPCs say are generated on the fly instead of read
from fixed text tables.

---

## Models — what to use

**For the proof-of-concept: `llama3.2` (3B) via Ollama.** Local, free, no API key,
no rate limits. Runs on ~4 GB RAM and is fast enough that the emulator pause is
barely noticeable. The POC is about proving the *plumbing* (game ↔ bridge ↔
model), not dialogue quality — so a small local model is the right call.

Upgrade paths (all one-line changes in `generate_dialogue()`):
- **Better local writing, if you have a GPU:** `ollama pull llama3.1:8b` or `qwen2.5:7b`, then change `MODEL` in `step1_dialogue_ollama.py`.
- **Best quality later:** swap Ollama for Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) — cheap and fast, ideal for frequent short calls. Needs a paid API key; keep the key in an env var, never in code.

## Tools — the full list

| Tool | Role | Install |
|------|------|---------|
| **Ollama** | Runs the LLM locally | https://ollama.com/download, then `ollama pull llama3.2` |
| **Python 3.10+** | The bridge server | you likely have it |
| `ollama` (pip) | Python client for Ollama | `pip install ollama` |
| **mGBA 0.10+** | Emulator with Lua + sockets | https://mgba.io/downloads.html |
| **pokeemerald** | Decomp — source of memory addresses | https://github.com/pret/pokeemerald |
| A legal **Emerald ROM** | The game itself | dump from your own cartridge |

Nothing else. `socket`, `json`, `argparse` are Python standard library.

---

## Architecture

```
  ┌─────────────────────┐   TCP (localhost:8888)    ┌──────────────────────┐
  │  mGBA + Emerald     │   newline-delimited JSON   │  bridge_server.py    │
  │  mgba_hook.lua      │ ───── game state ───────►  │  (Python)            │
  │                     │                            │        │             │
  │  frame callback     │                            │        ▼             │
  │  reads memory,      │                            │   Ollama (llama3.2)  │
  │  sends context      │  ◄──── dialogue ─────────  │   local LLM          │
  │  'received' cb      │                            │                      │
  │  injects text       │                            └──────────────────────┘
  └─────────────────────┘
```

**Why it doesn't freeze the emulator:** the LLM call happens in Python. mGBA
fires its request and keeps running frames; its `received` callback delivers the
reply once it's ready (mGBA checks socket events once per frame). The only
emulator-side blocking is the initial localhost connect, which is sub-millisecond.

---

## Build order & current status

| # | Step | Status |
|---|------|--------|
| 1 | Offline LLM harness (`step1_dialogue_ollama.py`) | ✅ built & verified |
| 2 | Bridge server + socket protocol (`bridge_server.py`) | ✅ built & verified |
| — | Mock client to test 1+2 with no emulator (`mock_mgba_client.py`) | ✅ built & verified |
| 4 | Real LLM wired into the bridge | ✅ built & verified (stubbed test) |
| 3 | Memory reads in Lua (`readContext`) | ⬜ skeleton — needs your symbol map |
| 5 | Text injection in Lua (`injectDialogue`) | ⬜ skeleton — needs charmap + script hook |

Steps 3 and 5 are deliberately left as clearly-marked skeletons because they
depend on **your** pokeemerald build's addresses and Emerald's character
encoding — that's the part your decomp knowledge makes tractable, and it can't
be hardcoded from outside.

---

## Run it (do these in order)

**A. Prove the LLM works alone**
```bash
pip install ollama
ollama pull llama3.2
python step1_dialogue_ollama.py
```

**B. Prove the full Python pipeline works (two terminals, no emulator yet)**
```bash
# terminal 1 — start with --echo to test wiring even before pulling a model
python bridge_server.py --echo      # then re-run without --echo for real dialogue
# terminal 2
python mock_mgba_client.py
```
You should see generated dialogue come back for each fake event.

**C. Bring in the emulator**
1. Open your Emerald ROM in mGBA.
2. Tools → Scripting… → load `mgba_hook.lua`. It connects to the bridge and logs that it's waiting for triggers.
3. Fill in the `ADDR_*` values in the Lua from your `pokeemerald.map`, then implement `readContext` and `injectDialogue` (both flagged with `<<< TODO`).

---

## What was verified while building this

- Ollama Python API (`ollama.chat` → `response.message.content`) — checked against the installed SDK.
- mGBA socket + memory API (`socket.connect`, `sock:add("received", …)`, `sock:receive`, `sock:send`, `emu:read8/write8`, `callbacks:add("frame", …)`) — checked against mGBA's official scripting docs.
- The socket protocol, newline framing, multi-message handling, and malformed-input resilience — checked by running the bridge against the mock client over a real socket.
- Lua script — compiles cleanly (syntax verified); game-specific logic is stubbed pending your addresses.
