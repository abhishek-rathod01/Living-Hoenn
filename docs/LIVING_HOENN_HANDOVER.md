# LIVING HOENN — HANDOVER (paste this as the first message in the new chat,
# or point Claude Code at this file and tell it to read it first)

This document is the state of the project as of this session. Read it fully
before touching anything. Status tags used throughout:
**[VERIFIED ×2]** confirmed two independent ways · **[APPLIED, TESTED]** code
changed and passed automated tests · **[APPLIED, UNTESTED ON HARDWARE]**
changed but not yet confirmed live · **[OPEN]** known issue, not yet fixed ·
**[DEFERRED]** deliberately not built yet.

---

## 1. What Living Hoenn is (unchanged from the original pitch)

An AI-powered Pokémon Emerald ROM hack: mGBA runs a Lua hook that detects NPC
dialogue, ships game state over TCP to a Python bridge, which asks an LLM to
generate in-character dialogue and injects it back into the running game.
Solo portfolio project, originally "runs entirely locally, no cloud" — **that
claim is no longer fully true** (see §3). Standing rule, still in force:
**verify every game fact two independent ways before trusting it** — against
the real pokeemerald decomp or mGBA source, not memory. State clearly what's
confirmed vs. hypothesis in all technical discussion.

---

## 2. THE QUEST ENGINE IS INTENTIONALLY DISABLED [APPLIED, TESTED]

`quest_bridge_server.py` (items, quests, take/give actions, the REWARDED-state
"Thanks again for the help!" trap) is **no longer used**. Deliberately parked
to focus effort, not abandoned — revisit later if wanted.

**Current bridge: `bridge/dialogue_bridge_server.py`** — pinned-persona,
dialogue-only. No `quest_engine`/`advisor`/`broadcast` imports. No actions are
ever emitted (no take_item/give_item/set_flag/await_choice — everything is
bare dialogue). Personas are pinned once per NPC (same `npc_profiles.json`
file/format as before, key `map_group:map_num:npc_id`) from the NPC's vanilla
`original_line` + location; a **fresh** line is generated every single talk,
so there's no more permanent repetition trap.

**Three interchangeable backends**, all tested (unit tests mock the real SDK
shapes, not hand-waved fakes):
- `--backend ollama` (default) — local, `--model llama3.2:3b` or
  `qwen2.5:7b-instruct-q4_0`. Free, no internet needed, slower/lower quality
  on the 3b model, better on the 7b quant (~4-6s/reply on the dev's 3060 laptop).
- `--backend gemini` — Google `google-genai` SDK, needs `GEMINI_API_KEY` env
  var (aistudio.google.com/app/apikey, free tier). Default model
  `gemini-3.5-flash` — **note: `gemini-2.5-flash` was deprecated for new API
  keys mid-project and had to be swapped out; if this happens again, check
  ai.google.dev/gemini-api/docs/deprecations before assuming it's a bug.**
  Free tier can return `503 UNAVAILABLE` under high demand — not a code bug.
- `--backend groq` — `groq` SDK (OpenAI-compatible), needs `GROQ_API_KEY`
  (console.groq.com/keys, free tier). Default model
  `llama-3.3-70b-versatile`. Added specifically as an independent fallback
  when Gemini's free tier was overloaded — different infra, won't share an
  outage.

All three share one hardened JSON parser (`_json_of`/`_finish_persona` in
`dialogue_bridge_server.py`) that tolerates markdown-fenced JSON, single-
quoted Python-dict-style output, and clips (doesn't reject) over-length
fields — because smaller/free models routinely produce all three, and the
original strict parser silently swallowed every failure, making "..." show
up for every NPC with zero diagnostic info. **If replies ever silently
degrade to "..." again, check the terminal for a
`persona designer produced unusable output: ...` or `missing field(s)` line
first — that's the fix for exactly that failure mode, don't re-diagnose from
scratch.**

**API keys**: never paste one into any chat, ever, with any AI assistant.
Set via `[System.Environment]::SetEnvironmentVariable("KEY_NAME", "value",
"User")`, close/reopen PowerShell. If one is ever accidentally pasted
somewhere, revoke and regenerate immediately, don't just "be more careful."

---

## 3. THE LUA HOOK (`mgba_hook.lua`) — v4, several real bugs found and fixed

All verified against the actual pokeemerald/mGBA source this session, not
memory. Full mGBA restart (not just script-reload) required after any hook
edit — see the reload-guard note below for why.

- **[VERIFIED ×2] Reload-without-restart used to stack two live hook
  instances.** `ScriptingController::loadFile()`/`load()` re-run the script
  on the same Lua engine without deiniting it; only the separate "Reset"
  menu action does that. Fixed: a reload guard (`_G.__livingHoenn` sentinel)
  now detects and tears down a prior instance's frame callback + socket
  before registering new ones. Still restart mGBA properly when you can —
  this is a safety net, not a replacement for that habit.

- **[VERIFIED, critical] A bare string ending in EOS (0xFF) finishes the
  printer INSTANTLY with no player input required** (`text.c`:
  `case EOS: return RENDER_FINISH;`). `Task_DrawFieldMessage` flips
  `sFieldMessageBoxMode` back to HIDDEN the instant the printer goes
  inactive. Only `CHAR_PROMPT_CLEAR` (0xFB) / `CHAR_PROMPT_SCROLL` (0xFA)
  actually make the printer wait for an A-press. **This was the real cause
  of the entire "blank box that never resolves" saga** — every reply was
  being marked stale by our own FIFO guard within a couple of frames of
  being sent, regardless of how long the player actually waited. Fixed:
  `encodeEmerald` now appends `0xFB` before every terminator. **Known minor
  side effect, not fully root-caused**: this may require one extra A-press
  to fully dismiss a box compared to vanilla — flagged as low priority,
  not yet deeply investigated, don't remove the 0xFB without a replacement
  fix or the blank-box bug returns.

- **FIFO stale-reply guard**: replaced a single `awaitingReply` boolean with
  a small queue; when the dialogue box closes, all still-pending requests
  are marked stale, and a stale reply is discarded instead of injected into
  whatever box happens to be open later. Integration-tested (real
  `onFrame`/`onReceived` closures driven through open→send→close→late-reply
  sequences).

- **REVCHARMAP collision fix**: 61 of 251 bytes in `charmap.lua` have two
  characters mapped to the same byte (Latin vs. kana/fullwidth-Japanese,
  since the shared GBA charmap data covers both regional charsets). Fixed
  via "shorter UTF-8 byte length wins" — verified against all 61 real
  collisions, resolves 60 correctly, 1 explicit tie-break (harmless
  ellipsis-variant synonym).

- **`decodeGameString` control-code handling**: now skips `EXT_CTRL_CODE`
  (0xFC) sequences by their exact verified byte-length (table derived from
  `string_util.c`'s real parser: most sub-codes take 1 extra arg byte,
  `COLOR_HIGHLIGHT_SHADOW` takes 3, `PLAY_BGM` takes 2, several take 0)
  instead of feeding those bytes through the charmap as if they were text.
  0xFE/0xFA/0xFB decode to a real `\n` now, not literal `\l`/`\n` text.
  Note: `PLACEHOLDER_BEGIN` (0xFD, e.g. `{PLAYER}`) is already expanded to
  real name bytes by the game *before* `gStringVar4` is populated
  (`StringExpandPlaceholders`, verified in `string_util.c`) — so the
  placeholder-decoding path in the hook is defensive-only, shouldn't
  normally fire.

- **Word-wrap at 40 chars**, UTF-8-aware (reads whole codepoints via the
  leading-byte length, not raw bytes — fixes multi-byte charmap entries like
  `…“”‘’♂♀¥` being shredded into fallback spaces). 40 is empirically measured
  against 496 real lines from 5 vanilla map scripts, not guessed.

- **`INTERCEPT_SIGNS` flag exists** (top of `mgba_hook.lua`), defaults
  `true`. Setting it `false` stops the hook touching any `npc_id==0` box
  (signs, TVs) — they'd show vanilla text untouched. **[APPLIED, UNTESTED
  live]** — asked for, built, never actually confirmed working in-game yet.

- **Pokémon Center PC exclusion**: requested (PCs aren't `npc_id==0`, so the
  sign flag doesn't cover them; the hook currently tries to generate a
  persona for a PC object, which is nonsense). **[OPEN, blocked]** — needs
  the actual `npc_id` from the console log next time a PC is used, then a
  skip-list needs adding to the bridge. Not built yet, just waiting on data.

---

## 4. CHATTER/PERSONA PROMPT — tightened once, needs a live-test confirm

After live testing surfaced three real problems (Nurse Joy offering to
battle; a repetitive NPC reciting the same "quirk" almost verbatim every
visit; another NPC breaking the 4th wall — "my clipboard notes suggest your
team has impressive diversity"), `PERSONA_SYSTEM` and `CHATTER_SYSTEM` in
`dialogue_bridge_server.py` were rewritten to:
- explicitly name known Pokémon service roles (Nurse Joy, shop clerk,
  Officer Jenny, Day Care attendant, PC clerk, Move Tutor/Deleter) that carry
  hard behavioral constraints (a healer never battles/trades),
- explicitly ban 4th-wall language ("notes", "records", "data", "algorithm",
  anything sounding like an outside narrator),
- explicitly demote the cached "quirk" field from catchphrase to occasional
  flavor, and instruct varying phrasing across repeat visits.

**[APPLIED, NOT YET RE-TESTED LIVE]** — this was the very last code change
before this handover was written. The next thing to do, before anything
else, costs nothing: **go re-talk to Nurse Joy and those same two NPCs and
confirm the fix actually worked** before building anything further on top of
an unconfirmed assumption.

---

## 5. THE NEXT FEATURE: decomp-mined NPC knowledge base (PILOT SCOPE ONLY)

This is the real, structural fix for persona/dialogue quality (as opposed to
prompt-patching symptoms after the fact) — it's also literally an item
already flagged as deferred in this project's own `ACTION_PLAN.md` before
this session started, so it's not scope creep.

### The actual insight from this session, corrected from an earlier wrong claim
Trainer party-awareness was earlier told to the user as "out of scope,
needs unverified live memory addresses." **That was wrong.** `scripts.inc`
files use a `trainerbattle` macro that names the exact trainer constant for
that object event, at the SOURCE level, resolvable via static analysis —
no live memory read needed. This means trainer-aware dialogue (an NPC that
knows its own actual battle party) is achievable via the same
generate-a-static-table-from-source method already proven for
`world_tables.py` and `items_table.py`. Correct this if it comes up again.

### Pilot scope — do NOT attempt all ~400+ maps in one pass
Pick 4-5 named maps to prove the pipeline end-to-end first (suggested:
Lilycove City, Fortree City, Slateport City, one Pokémon Center interior
map, one Route with at least one trainer). Get real, inspectable output on
these before scaling further. `scripts.inc` syntax is not perfectly uniform
across the whole decomp — a parser that works on 5 hand-picked maps is not
guaranteed to work on all 400+ without real testing against a wider sample.

### The pipeline, per map
1. Parse `data/maps/<Map>/map.json`'s `object_events` array — gives each
   NPC's local id and which script it runs.
2. Cross-reference that script in the matching `scripts.inc` — extract every
   `.string` line that NPC can say (not just the one line currently captured
   at trigger time), and detect any `trainerbattle` macro (→ trainer
   constant name).
3. Cross-reference trainer constants against `src/data/trainers.h` for
   their actual party.
4. Emit ONE generated table, keyed `map_group:map_num:npc_id` — same format
   `persona_engine.py` already uses, so it can be fed into the persona
   designer prompt as real grounding instead of one throwaway line.

### Standing rules that still apply to this feature
- Verify every extracted fact two ways (parse it, then spot-check a handful
  of entries by hand against the real `.inc` file) before trusting the
  generated table.
- Don't hand-edit the generated table — regenerate from source if wrong.
- `CLAUDE.md`'s existing hard rules (no invented addresses, Lua 5.1
  portability, savestate before hardware writes, no credentials in chat)
  are unrelated to this feature but still apply to the project as a whole.

---

## 6. Recommended tooling for this next feature

**Use Claude Code, not the chat interface, for this.** It needs to iterate
against a real, large, local file tree (the pokeemerald clone at
`C:\Users\abhis\Desktop\Living hoenn\pokeemerald`) and write/test a parser
repeatedly — that's what an agentic coding tool with persistent filesystem
access is for, not a chat sandbox.

**Model: Fable 5** (`/model fable` inside a session, or `claude --model
fable` at launch; requires Claude Code v2.1.170+, run `claude update`
first). This is a well-suited task for it — large, ambiguous ("build a
working decomp-mining pipeline," not a five-line patch), needs sustained
investigation across many files without losing the thread. Per Anthropic's
own guidance: describe the *outcome* you want and let it plan the path;
don't over-specify steps; don't bother with "remember to test this" —
it verifies its own work more than smaller models by default. It burns
usage roughly 2x faster than Opus per token, worth knowing even with a
fresh limit.

### Suggested opening prompt for that Claude Code session
> Read `CLAUDE.md` and this handover doc fully first. Then build a pilot
> decomp-mining pipeline against the pokeemerald clone at
> `C:\Users\abhis\Desktop\Living hoenn\pokeemerald`, scoped to these 5 maps
> only: Lilycove City, Fortree City, Slateport City, [pick one Pokémon
> Center interior map], and [pick one Route with a trainer]. For each NPC
> object event in those maps: extract every vanilla dialogue line it can
> say, detect if it's a trainer (via the `trainerbattle` macro) and if so
> pull its real party from `src/data/trainers.h`. Emit one generated table
> keyed `map_group:map_num:npc_id`, same format `persona_engine.py` already
> uses. Show me real output on all 5 maps — including at least one entry
> you hand-verified against the raw `.inc` file — before wiring it into the
> bridge at all. Don't touch `dialogue_bridge_server.py`, the Lua hook, or
> the quest engine in this session; this is scoped to the extraction
> pipeline only.

---

## 7. Everything else, lower priority, parked

- `INTERCEPT_SIGNS=false` — flip and confirm signs show vanilla text.
- PC exclusion — waiting on an `npc_id` from a live PC interaction.
- The extra-A-press question — minor, only chase if it keeps bothering you.
- Re-enabling the quest engine / building the "Chatter" REWARDED-state
  feature — explicitly deferred, not abandoned.
