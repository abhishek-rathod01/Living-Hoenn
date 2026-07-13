# Living Hoenn — Architecture & Field Guide

*How a 2004 GBA cartridge learned to talk: a complete walkthrough of the
Emerald internals, the emulator bridge, and the LLM layer — written to teach,
not just to document. If you read one file in this repo, read this one.*

---

## 0. What this is, in one loop

You walk up to an NPC in Pokémon Emerald and press A. Instead of the same
1,000-times-read line, the game **pauses the text box**, ships everything it
knows about the moment — who you are, where you are, your team, your badges,
what this NPC was originally going to say — to a Python process, which asks a
local LLM to answer *in that NPC's pinned personality*, validates the result,
and injects it back into the running game. NPCs invent side quests with real
item rewards, sailors sell you passage to event islands the cartridge normally
locks behind promotional events, TVs broadcast news about things *you actually
did*, and the whole region reacts when a Lv70 Rayquaza is standing behind you.

The player never leaves the game. The LLM never touches memory directly.
Everything between them is verified, validated, and tested.

> **Note (July 2026):** the diagram below shows the full quest-era design,
> which is still the best way to LEARN the system. The current default
> runtime is `bridge/dialogue_bridge_server.py` -- same hook, same TCP
> protocol, same persona pinning, but dialogue-only (no actions, no quest
> engine) and with three interchangeable LLM backends
> (`--backend ollama|gemini|groq`) plus decomp-mined NPC grounding for the
> 5 pilot maps. Quest mode is parked, not deleted. Current state:
> docs/LIVING_HOENN_HANDOVER.md.

```
   mGBA (the game, running)                Python bridge                local LLM
 ┌──────────────────────────┐   TCP    ┌─────────────────────┐   HTTP  ┌─────────┐
 │ mgba_hook.lua            │ ───────► │ quest_bridge_server │ ──────► │ Ollama  │
 │  • detect dialogue open  │  JSON    │  • persona cards    │         │ qwen2.5 │
 │  • read RAM: party, bag, │          │  • quest engine     │ ◄────── │  :7b    │
 │    flags, map, NPC id    │ ◄─────── │  • validation GATE  │         └─────────┘
 │  • execute actions       │ acts|txt │  • news/quiz/advisor│
 │  • inject text           │          │  • transcripts      │
 └──────────────────────────┘          └─────────────────────┘
```

---

## Part I — How Pokémon Emerald actually works

You cannot safely modify a running game you don't understand. Everything below
was verified against the `pret/pokeemerald` decompilation — a matching-source
reconstruction of the retail ROM — and most of it twice, in different ways.

### I.1 The GBA memory map (the 60-second version)

The Game Boy Advance has no OS and no memory protection. Everything lives at
fixed bus addresses:

| Region | Address range | What lives there |
|---|---|---|
| ROM | `0x08000000+` | The cartridge: code, scripts, text, **gTrainers** table |
| EWRAM | `0x02000000+` | 256 KB work RAM: **party, save blocks, text buffers** |
| IWRAM | `0x03000000+` | 32 KB fast RAM: hot state, some pointers |

C globals get placed at **link time** and never move afterwards. That's why
`gPlayerParty` or `gStringVar4` have single, stable addresses for a given ROM
build — and why this project asks you to grep *your own* `pokeemerald.map`
instead of trusting numbers from the internet: rebuild the ROM with any change
and the linker may re-place everything.

### I.2 The one thing that DOES move: save blocks (Emerald's mini-ASLR)

Ruby/Sapphire kept save data at fixed addresses, and cheat devices feasted on
it. Emerald fights back: the save data's backing buffers are literally named
`SaveBlock1ASLR` in the source, and `SetSaveBlocksPointers()` places the live
data at `base + (random offset)` — re-randomized during play.

The escape hatch: the *pointers* `gSaveBlock1Ptr` / `gSaveBlock2Ptr` are
ordinary fixed globals. So the access pattern everywhere in this project is:

```lua
local sb1 = emu:read32(ADDR_SAVEBLOCK1_PTR)   -- pointer is fixed
local mapGroup = emu:read8(sb1 + 0x04)        -- data is wherever it is today
```

Everything inside SaveBlock1 (map location `+0x04/+0x05`, bag pockets, the flag
array at `+0x1270`) and SaveBlock2 (the bag **encryption key** at `+0xAC`) is
reached this way.

### I.3 A Pokémon in memory: 100 bytes, 24 shuffles, one XOR

Each party slot is a 100-byte `struct Pokemon` (proven by compiling the real
struct: `sizeof == 100`). Two facts make it fun:

1. **Level is plaintext** at offset **84** — no decryption needed. One byte.
2. **Species is encrypted.** Bytes 32–79 hold four 12-byte "substructs" whose
   *order* is chosen by `personality % 24` and whose contents are XOR'd with
   `personality ^ otId`. Reading species = read PID and OTID, compute the key,
   look up which physical slot holds the Growth substruct (a 24-entry table
   transcribed from `GetSubstruct()`), XOR one 32-bit word, keep the low 16
   bits. Our decoder was tested against **12,000 synthetic Pokémon** across
   all 24 orderings — zero failures.

One trap worth internalizing: the species value is Emerald's **internal Hoenn
index**, not the National Dex number (Blaziken is 282 here, not 257). Our
`species_names.lua` is generated from the game's *own* name table so the
numbering can never disagree.

### I.4 Text: the game speaks its own alphabet

Emerald text isn't ASCII. `charmap.txt` in the decomp maps glyphs to bytes
(`'A' = 0xBB`, space = `0x00`, …) with `0xFF` terminating every string. Our
`charmap.lua` is generated from that file and the encoder is byte-tested
(`"Hi!"` → `C2 DD AB FF`). Whatever the LLM says gets transcoded before it
touches game memory — and hard-capped at 250 bytes, because the target buffer
(`gStringVar4`) is 1000 bytes and adjacent EWRAM would silently corrupt if we
ever ran past it.

### I.5 The dialogue pipeline (and where we tap it)

Every scripted `message`/`msgbox` in the game funnels through one function:
`ScrCmd_message → ShowFieldMessage(msg)`, which expands the text **into
`gStringVar4`** and flips a state byte, `sFieldMessageBoxMode`, from `HIDDEN`
(0) to a non-zero mode. Two consequences power this whole project:

- **The trigger**: watch that one byte each frame; a 0→nonzero edge means "a
  dialogue box just opened" — for NPCs, signs, *and TVs* alike.
- **The injection point**: whatever sits in `gStringVar4` is what renders.

Rendering is done by a text-printer state machine (`sTextPrinters[0]` for
field messages; element stride 0x28... no — 0x24; fields verified by 32-bit
compile: `currentChar` at +0x00, `active` at +0x1B, `state` at +0x1C, where
state 0 = `RENDER_STATE_HANDLE_CHAR`, the "start printing" state). Lua can't
call ROM functions, so injection is a pure-memory trick: write the new bytes
into `gStringVar4`, point `currentChar` back at its start, set `active=1,
state=0` — the printer redraws our text as if the game had asked it to. The
*timing* of that restart is the single piece of this system never proven on
real hardware; everything else is.

### I.6 Flags, badges, and the doors they open

Progress in Emerald is a bit-array: `flags[id/8] |= 1 << (id%8)` at
SaveBlock1+0x1270 (mirrored exactly, in portable arithmetic, by our Lua).
Badges are flags `0x867–0x86E`; "beat the game" is `0x864`; **376 flags are
unused** — free real estate for persistent quest state. Best of all, the
event-island ferries are gated by four flags (`FLAG_ENABLE_SHIP_*`,
`0x8B3/0x8D5/0x8D6/0x8E0`) that Lilycove's own harbor script checks with
`goto_if_unset`. Set the flag, hand over the ticket item, and the ferry
destination appears *through the game's own script* — no hack visible.

### I.7 The bag: three pockets and an XOR

Bag pockets are ItemSlot arrays inside SaveBlock1 (Items `+0x560`×30, **Key
Items `+0x5D8`×30**, Berries `+0x790`×46; slot = `{u16 id, u16 qty}`), and
quantities are stored XOR'd with the low 16 bits of the SaveBlock2 encryption
key. Get the key wrong and you don't crash — you silently corrupt inventory,
which is why every item write in this repo is round-trip tested and why the
runbook says *savestate first*. Event tickets are Key Items, so item grants
carry an optional pocket tag (`give_item:371:1:key`) and key items are capped
at quantity 1.

### I.8 Identity: who am I even talking to?

`gSpecialVar_LastTalked` holds the local ID of the object the player
interacted with — set in `field_control_avatar.c` for NPCs, reset to
`LOCALID_NONE` (**0**) every input, and *never set* for background events. So
`npc_id > 0` = a person (stable quest/persona key when combined with the map),
and `npc_id == 0` = a sign or TV — which is exactly how broadcasts get their
own route. Trainer NPCs additionally have ROM records (`gTrainers`, 0x28 bytes
each: class at +0x01, name at +0x04) readable via `trainer_info.lua`.

---

## Part II — How mGBA lets us in

mGBA (≥0.10) embeds Lua with, crucially for us:

- `callbacks:add("frame", fn)` — run our code once per emulated frame.
- `emu:read8/16/32`, `write8/16/32` — raw memory access. `read32` returns
  **unsigned** U32 (checked in mGBA's own source); our `u32()` masks are
  defensive anyway.
- A **socket wrapper**: `socket.connect()` returns an object whose `add
  ("received", cb)` fires when data arrives — the wrapper auto-polls each
  frame, which is what makes the design non-blocking: the emulator never
  waits on the LLM; the reply just shows up.
- `emu:getKey(n)` — button state (A=0, B=1, Select=2), powering quiz answers
  and the Professor hotline.

One constraint shaped every Lua file here: mGBA may link **Lua 5.1 or
LuaJIT**, where native bitwise operators (`~ & | << >>`) are *load-time syntax
errors*. All bit math is arithmetic (`u32()`, `bxor()`), verified equal to
native ops across 5,000 cases.

---

## Part III — The system we built on top

### III.1 The context: what the game tells the bridge

On every dialogue trigger the hook sends one JSON line:

```json
{"npc_id": 7, "map_group": 24, "map_num": 7,
 "original_line": "I love berries more than anything.",
 "party": ["Blaziken:45", "Mudkip:5"], "bag": ["13:1", "139:2"],
 "player_level": 45, "badges": 5, "game_clear": 0,
 "unlocks": 1, "advice": 0}
```

`original_line` is the vanilla text the NPC *was about to say* — decoded from
`gStringVar4` before we blank it — and is the secret ingredient: personas are
derived from the character the game already gave that NPC. `unlocks` is the
island bitmask; `advice=1` means Select was held.

### III.2 The cast of brains (and which are allowed to be creative)

| Role | Model? | Job |
|---|---|---|
| **Persona designer** | LLM, once per NPC | Invent a personality card from the original line, location, progress. Cached forever in `npc_profiles.json` — same NPC, same soul, across restarts. |
| **Quest designer** | LLM, once per NPC | Emit a quest as strict JSON, *in that persona's voice*. |
| **Advisor ("Prof. Birch"/"Dad")** | **No LLM** | Curated milestone table keyed by badges/location. Deliberately deterministic so the walkthrough can never be hallucinated. |
| **News anchor** | **No LLM core** | Bulletins composed from *real* state: your completed quests (with map names), badges, champion flag, legendaries in party. |
| **Quiz host** | RNG + tables | "Who's That Pokémon?" from the real species table; A/B answered with actual buttons; a berry on a correct answer. |

### III.3 The validation gate (the design rule that makes this safe)

**The LLM is treated as untrusted input.** Its output must parse as JSON and
pass `validate_quest` / `validate_persona`: known quest types only, item IDs
that exist, quantities 1–5, reward items from a whitelist *with a denylist on
top* (the very first test run caught the keyword "Ball" smuggling **Master
Ball** into rewards — hence the explicit denylist), island unlocks only from a
four-entry registry, text length caps. Anything invalid → graceful fallback
(persona greeting, then canned small talk). Free model text can *never* reach
`emu:write` — only validated IDs travel in the action grammar:

```
take_item:ID:QTY[:pocket] ; give_item:ID:QTY[:pocket] ; set_flag:ID ; await_choice:FRAMES
        └── executed by the hook; unknown actions are logged and ignored ──┘
```

Replies are one line — `actions|dialogue` or bare dialogue — because the
transport is newline-framed, and LLMs love emitting newlines (an early bug:
multi-line replies were read as multiple messages, corrupting the protocol;
the bridge now collapses whitespace and never sends an empty frame).

### III.4 The quest state machine

Per NPC (key = `map_group:map_num:npc_id`):

```
(none) --talk--> ACTIVE(intro) --talk,incomplete--> reminder
ACTIVE --talk,complete--> REWARDED(complete line + actions)   [once, ever]
REWARDED --talk--> after-line
```

Completion checks read the *real* bag/party from the context. Fetch quests
take the items back before rewarding. Island quests swap the reward for
`give_item:TICKET:1:key + set_flag:SHIP_FLAG` and are offered only by NPCs in
Lilycove/Slateport (the two harbors whose scripts actually run the event
ferry — a wrong-port bug the test suite caught when random test coordinates
turned out to be Dewford Town). State persists in `quests.json` (atomic
writes), so the world remembers across restarts.

### III.5 A world that reacts

`build_world_notes()` injects two kinds of truth into every designer prompt:
**awe** (a legendary ≥ Lv50 in the party, or the champion flag → "react with
visible fear and reverence") and **gossip** (the map name of the most recent
completed quest → NPCs reference each other's stories). One honest limit: a
trainer cannot mechanically *forfeit* — Gen 3 battle scripts don't allow
opponent flight and we don't drive the battle engine — so fear lives where we
do have the pen: their pre-battle speech, which flows through the same field
message pipe we already own.

### III.6 Ops: built to run unattended

`watchdog.py` restarts a crashed bridge with backoff and logs; every exchange
appends to `transcripts.jsonl` (debug remotely, mine real generations for a
writeup); `CLAUDE.md` boots any Claude Code session with the project rules;
`run_all_tests.py` is the one command that proves the entire Python layer and
Lua syntax on any machine — **11 checks, no emulator, no model needed.**

---

## Part IV — The methodology (the actual lesson of this repo)

Every load-bearing fact was verified **two independent ways** before code
depended on it. A sampler:

| Claim | Check 1 | Check 2 |
|---|---|---|
| Pokémon struct layout | read the source | **compiled it**: sizeof/offsetof |
| Species decryption | read `DecryptBoxMon` | 12,000 synthetic mons, 0 failures |
| Text printer offsets | header's inline comments | 32-bit-accurate compile (a 64-bit first attempt gave wrong offsets — pointers!) |
| Charmap bytes | parsed `charmap.txt` | hand-computed `"Hi!"` byte-for-byte |
| Island ferry gating | flag definitions | the harbor **script** consuming them |
| mGBA socket API | docs | the wrapper's own embedded Lua source |

And the discipline caught *our* bugs, not just the game's: the `sTextPrinters`
symbol misname, the Lua-5.1 bitwise-operator landmine, the Master Ball
whitelist hole, the Dewford false port, a buffer overflow, a variable-scoping
bug where a function wrote a global while another read a local — each found by
a test or a cross-check *before* it could cost an evening on real hardware.
If you take one habit from this project: **when a check fails, suspect your
harness and your assumptions equally — and when a check passes suspiciously
easily, make sure you tested the real artifact, not an instrumented copy.**
(We got burned by exactly that, once. It's in the commit history.)

---

## Appendix A — Protocol reference

Request: one JSON object + `\n` (fields in §III.1; plus `{"choice": 0|1|2}`
for quiz answers). Response: `action;action|dialogue\n` or `dialogue\n`.

## Appendix B — File map

| File | One-liner |
|---|---|
| `lua/mgba_hook.lua` | Trigger, reads, action executor, injector, choice loop |
| `lua/party_reader.lua` | Address validator — run before the hook |
| `lua/trainer_info.lua` | Trainer class/name from ROM (Phase-5 groundwork) |
| `lua/species_names.lua`, `lua/charmap.lua` | Generated from game source |
| `bridge/dialogue_bridge_server.py` | **Current default**: dialogue-only, 3 backends, mined-table grounding |
| `bridge/quest_bridge_server.py` | Quest-mode router: advice/broadcast/quest/persona (parked) |
| `bridge/quest_engine.py` | State machine + THE validation gate |
| `bridge/persona_engine.py` | Pinned personalities |
| `bridge/broadcast.py` | TV news + quiz |
| `bridge/advisor.py` | Birch/Dad deterministic guidance |
| `bridge/world_tables.py`, `bridge/items_table.py` | Generated: maps, classes, items |
| `watchdog.py`, `run_all_tests.py` | Ops + the 15-check suite |

## Appendix C — Extending it (two recipes)

**New action** (e.g. `heal_party`): 1) implement + verify the memory writes in
the hook's `runAction`; 2) emit it from a validated path in the engine; 3) add
a simulated-memory test. Never skip 3.

**New quest type**: add to `QUEST_TYPES`, extend `validate_quest` (whitelist
everything), implement `is_complete`, teach the designer prompt, add lifecycle
tests. The gate grows *with* the feature, or the feature doesn't ship.

## Glossary

**Decomp** — a source reconstruction that compiles byte-identical to retail.
**EWRAM** — the GBA's main work RAM. **PID** — a Pokémon's 32-bit personality
value; seeds encryption and substruct order. **Substructs** — the four
shuffled, XOR'd 12-byte blocks holding a Pokémon's core data. **gStringVar4**
— the 1000-byte scratch buffer all field dialogue renders from. **Flag** — one
bit of persistent world state. **The gate** — the validation layer between
model output and machine state; the reason this whole thing is safe.
