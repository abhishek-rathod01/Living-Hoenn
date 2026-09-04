# LIVING HOENN — HANDOVER 3 (paste this as the first message in the new chat,
# or point Claude Code at this file and tell it to read it first)

Status tags: **[VERIFIED x2]** confirmed two independent ways · **[APPLIED,
TESTED]** code changed, tests pass · **[APPLIED, CONFIRMED LIVE]** tested in
the actual running game · **[APPLIED, PENDING LIVE CONFIRM]** committed,
tests pass, not yet confirmed in-game · **[IN PROGRESS]** Claude Code
actively working on this as of this handover · **[OPEN]** known issue, not
fixed · **[DEFERRED]** deliberately not built yet · **[UNCONFIRMED]** advised
or attempted, never verified back.

This supersedes docs/LIVING_HOENN_HANDOVER_2.md for anything that conflicts.
Read HANDOVER and HANDOVER_2 too if deeper history on a specific item is
needed — this file is the current state, not a replacement for their detail.

---

## 1. What's confirmed working, live, right now

- **Trainer-awareness dialogue** — multiple Route 110 trainers correctly
  reference their real parties (species/level) in varied in-character
  phrasing, never inventing Pokemon not on their list. Confirmed via live
  bridge terminal logs across repeated talks.
- **Renown/awe reactions** — several NPCs reacted with genuine awe to a
  Salamence, Mew, and Mewtwo in the player's party ("Your Mewtwo is in
  remarkable condition," "I've heard tales of such strength"). Renown-tier
  logic is working as designed.
- **qwen3:8b + think=False + num_ctx 2048** — **[APPLIED, CONFIRMED LIVE]**.
  Real bridge server logs show n_ctx_slot = 2048, fast total response time
  (~3s for 710 tokens), no <think> leakage, 200 OK on /api/chat. This
  was a multi-turn saga (model swap, flash-attention crash + revert, context
  tuning) — see §5 for the full story if picking this up cold.
- **Nurse Joy's persona** — correctly healer-locked (archetype: "healer",
  no battle/trade offers). Confirmed by reading her actual cached card
  after a prior misdiagnosis (see §6, "mistakes made" — the wrong NPC was
  targeted for deletion earlier in that session; the real Nurse Joy
  (9:11:1, Slateport PC 1F) turned out to already be correctly fixed).
- **MIT license + docs sync** — done via a separate Cowork session (README,
  CLAUDE.md, HOME_SETUP, ACTION_PLAN, ARCHITECTURE.md all updated to
  reflect post-pilot state). Commits b15bd45, 3356902, bf08333.

---

## 2. IN PROGRESS as of this handover — do not lose this thread

A Claude Code session was actively working on three fixes when this handover
was written, using this prompt (paste verbatim if resuming a fresh session
instead of continuing the live one):

  Read CLAUDE.md and docs/LIVING_HOENN_HANDOVER_2.md fully first.

  Three related fixes, all live-observed this session:

  1. TRUE hook-level skip (the real fix for signs/TVs/PCs, not persona
     suppression -- that part already works correctly). In mgba_hook.lua,
     when the bridge reply is exactly "..." (or introduce an explicit skip
     sentinel the bridge returns instead of literal dots), the hook must
     NOT write anything into gStringVar4 or touch sTextPrinters at all --
     let the vanilla message/menu proceed completely untouched. Verify
     against a sign, a PC, and a TV if reachable, and confirm
     INTERCEPT_SIGNS=false signs ALSO show real vanilla text with zero
     visual interruption (not even a blank-box flash).

  2. Battle-status-aware grounding for trainers. Multiple resolved vanilla
     lines (pre- and post-battle) are currently likely handed to the model
     together without indicating which applies now, causing inconsistent
     referencing (observed live: Jasmine sometimes ignoring she's already
     been defeated). Read the trainer's actual defeated flag from game
     memory (Emerald tracks this per-trainer in the flag array -- verify
     the exact mechanism/macro against pokeemerald source, two independent
     ways, before implementing -- do not guess flag numbering). Pass an
     explicit "already defeated: true/false" fact into build_grounding(),
     and filter which resolved lines are shown to match real state.

  3. Short dialogue continuity: chatter() has no memory of an NPC's last
     1-2 lines, causing near-repetition (observed live: Nurse Joy, 4 similar
     variants in a row). Store a short rolling history (last 2 lines) per
     NPC alongside its persona card in npc_profiles.json, and feed it into
     CHATTER_SYSTEM as "avoid repeating or closely paraphrasing these
     recent lines."

  Test each independently. Run run_all_tests.py before and after. Atomic
  commits, BUG/FIX/verification style, source-cited for the trainer-flag
  mechanism specifically. Do NOT touch the quest engine or extraction/.
  Show me diffs before committing -- item 1 touches the Lua hook, so be
  extra explicit about exactly what changed and why it's safe.

**Why these three, evidence for each (live-observed, not hypothesized):**
- Item 1: screenshots showed "sent context (npc 0)" -> "reply: ..." looping
  at signs, a Hoenn wall map, and a Pokemon Center PC — the bridge
  correctly returns "...", but the hook still blanks the box instead of
  leaving vanilla text/menus untouched.
- Item 2: Jasmine's post-battle chatter sometimes read as if she hadn't
  been defeated yet, despite the player having already beaten her.
- Item 3: Nurse Joy said near-identical "your Pokemon look in peak
  condition" variants four times in a row across consecutive talks.

**When this session reports done, DO NOT push before:**
1. Reading the diff yourself, especially the Lua hook change (item 1 is
   the highest-stakes edit of the three — it touches live game-memory
   interaction, not just Python).
2. Running run_all_tests.py yourself.
3. **Live-testing, savestate first (Shift+F1):** a sign (should show real
   vanilla text, zero blank-box flash), the PC, Jasmine's post-battle line
   specifically (should now consistently acknowledge the defeat), and 3-4
   consecutive talks to Nurse Joy (should show varied lines, not
   near-repeats).

Only push after all of the above confirms clean. This is a stricter bar
than prior phases specifically because of the Lua hook edit.

---

## 3. Exhaustive feature backlog — every idea raised in this project's
history, sorted honestly by real status. (Requested explicitly: "check
exhaustively" — this list is deliberately complete, not curated down to
favorites.)

### Verified feasible, zero code written yet
- **EV/IV/nature-aware dialogue.** PokemonSubstruct2 (EVs, plain bytes)
  and PokemonSubstruct3 (IVs, packed into one u32 at +0x04, 5 bits each)
  confirmed in pokeemerald's include/pokemon.h. Needs: substruct-2/3
  position tables transcribed from GetSubstruct() (same method as the
  already-proven GROWTH_POS species table) + extending the existing
  12,000-mon test harness to cover EV/IV decode. Nature is free (derivable
  from PID % 25, no extra memory read). **Nothing built.**
- **Story-event reactivity** (Team Aqua/Magma incidents, Groudon drought,
  Kyogre downpour, the Sootopolis climax fight). VAR_ABNORMAL_WEATHER_LOCATION
  (0x4037) and VAR_SOOTOPOLIS_CITY_STATE (0x405E) confirmed to exist in
  include/constants/vars.h, plus VAR_SLATEPORT_HARBOR_STATE and
  VAR_WEATHER_INSTITUTE_STATE. Needs: SaveBlock1 vars array offset
  verified via an offsetof-style harness (same method as the flags array),
  and the 0x4000+-indexing convention confirmed against event_data.c.
  **Nothing built.**
- **Roaming-Pokemon hint system.** src/roamer.c confirms #define ROAMER
  (&gSaveBlock1Ptr->roamer) and a plain static sRoamerLocation[2]
  (mapGroup, mapNum pair) — greppable from a .map file exactly like
  sFieldMessageBoxMode was. Design intent (already agreed, not yet
  built): never pass the species to the LLM at all, only "a rare Pokemon
  was sighted nearby" — so the model can't leak a name it was never given.
  **Nothing built.**
- **Full ~400+ map decomp-mining rollout.** Explicitly deferred until Phase
  B is fully confirmed working live (i.e., until §2's three fixes are
  live-verified). When it happens: Fable-as-orchestrator dispatching
  Sonnet-pinned map-extractor subagents in parallel batches (the same
  subagent used for the 5-map pilot, reusable as-is) is the agreed
  approach for wall-clock speed. **Nothing built beyond the 5-map pilot.**
- **Object-type allowlist, generalized.** Currently the mined object_type
  field only covers the 5 pilot maps; the hook still relies on one-off
  manual skip-list entries for anything outside that scope (or, per §2
  item 1, was relying on incomplete gating even inside it). Full
  person-vs-object gating for the whole game needs the full mining rollout
  first.

### Discussed, feasibility-checked, deliberately deferred
- **Quest bridge revamp.** A diagnostic-first prompt was written (see
  HANDOVER_2 §3) specifically because the user reported it as "very much
  absolutely broken with a lot of issues" but no specific bugs were
  reproduced or verified this session. **Status: prompt exists, never
  confirmed executed.** This is the single largest unaddressed thread —
  worth explicitly deciding in the next session whether to run the
  diagnostic now or keep it parked.
- **PokeNav two-way calls.** Trigger (sMatchCallState trainerId flip),
  buffer (gStringVar4), caller identity (trainer_info.lua), and button
  input (emu:getKey) are all individually verified — the blocking unknown
  is on-hardware page-flip injection timing, the same class of problem as
  the original Phase 3 dialogue-injection timing issue. **Deferred by
  design, not forgotten.**
- **Multi-box dialogue via 0xFB/CHAR_PROMPT_CLEAR encoding.** Named as a
  "next" item as far back as the original CLAUDE.md, never picked up.
- **"Chatter" path for already-rewarded NPCs.** Quest-engine-adjacent
  feature, blocked on the quest-bridge revamp decision above.
- **Real in-game choice menus** (vs. the current A/B-button substitute).
  Would require driving the actual window/menu system — assessed as
  low-feasibility, current substitute pattern is considered good enough.
- **Battle Frontier opponents.** **[VERIFIED x2]** — NOT procedurally
  generated. include/battle_tower.h defines a fixed struct
  BattleFrontierTrainer with authored easy-chat speech; battle_tower.c's
  GetRandomScaledFrontierTrainerId does streak-scaled *random selection*
  from exactly 300 authored trainers and an 882-mon pool — a real
  distinction from true procedural generation. Deliberately deferred:
  their identity is per-battle frontier-save-state, not
  map_group:map_num:npc_id, so the persona-key scheme doesn't fit them as
  designed, and they already have Nintendo-authored personalities via
  their easy-chat speech, so grounding them the normal way would be
  redundant, not additive.

### Phase E — mobile/distribution, fully speculative, zero code
- **Mobile play blocker, [VERIFIED x2]:** mGBA has no native Android app
  (only a RetroArch core exists), and the Lua scripting console is a
  desktop-Qt-only feature. "Phone runs game+hook" is not possible without
  forking mGBA.
- **Streaming (Moonlight/Sunshine/Parsec/AnyDesk)** — zero code needed,
  just a recommended setup, never actually configured/tested this project.
- **Remote bridge for friends via Tailscale tunnel** — one-line socket
  change (point at non-localhost), but the protocol currently has zero
  auth and plaintext JSON. Favorable safety property already noted: the
  dialogue-only bridge emits no actions, so a compromised bridge can only
  ever send text, never write game memory.
- **Vanilla-US-ROM address table + CRC/game-code fingerprinting** — the key
  unlock for a non-technical .exe distribution (skips the
  build-pokeemerald-and-grep-the-.map step entirely). Needs the vanilla
  address set verified two independent ways (once), then a ROM-fingerprint
  check at bridge startup. **Not started.**
- **PyInstaller-frozen bridge + portable mGBA + small launcher** — not
  started. Two open questions never resolved: (a) does mGBA support
  autoloading a Lua script via CLI flag/config (avoiding a manual
  Tools->Scripting step for end users)? **Never checked.** (b) distributing
  the mined dialogue table means distributing verbatim Nintendo text, same
  gray-zone status as the pret decomp itself — worth being aware of before
  shipping, not necessarily a blocker.

---

## 4. Loose ends — unconfirmed either way, small but real

- **species_names.lua loading for Party Reader.** Cosmetic-only (species
  IDs are confirmed correct internal Hoenn indices, decode logic is NOT
  broken), but names still weren't confirmed showing after the suggested
  same-folder/dofile-inline fix. **Never confirmed fixed.**
- **iGPU/dGPU separation via NVIDIA Control Panel + Windows Graphics
  settings.** Steps were given (global default -> integrated, per-app
  override -> discrete for ollama.exe) but never confirmed applied — though
  it turned out not to matter much, since the real VRAM bottleneck was
  model-weight size, not other-app contention (nvidia-smi showed a clean
  0MiB baseline before Ollama even started).
- **Gemini and Groq API key rotation.** Both keys were pasted into chat
  once this project (confirmed never entered git history via git log
  --all -S"<key>", both searches returned empty), rotation was advised
  twice across two different sessions, **never explicitly confirmed done**
  at either dashboard.
- **Item ball fanfare re-verification.** Never actually tested this
  session — Route 110's three item balls were already looted before the
  test was attempted. Low priority (cosmetic, extra-A-press caveat only),
  but technically still an open checklist item from the original Phase B
  live-verification plan.
- **Flash Attention + KV cache quantization on this hardware.** Attempted,
  crashed with a CUDA error inside ggml_cuda_kernel_can_use_pdl (a stack
  buffer overrun during a PDL feature-support probe — looks like a real
  bug in this specific Ollama CUDA v13 build on an Ampere-class card, not
  a genuine VRAM shortage). Reverted (OLLAMA_FLASH_ATTENTION=0,
  OLLAMA_KV_CACHE_TYPE unset). **Not worth chasing further** unless
  Ollama ships an update and someone wants to retest — current 2048-context
  setup without it is stable and fast enough.
- **SUPERSEDED.md** exists in the repo root — origin/purpose unclear as
  of this handover (may predate recent sessions or come from a Cowork
  docs-sync pass). Worth a glance next session to confirm it's meant to be
  there / is correctly named.

---

## 5. The qwen3/Ollama tuning saga — condensed, for context if it comes up

Old models (qwen2.5:7b, qwen2.5:7b-instruct-q4_0, llama3.2:latest)
removed; qwen3:8b installed as the verified same-weight-class successor
(Ollama's own library page confirms it; Qwen's benchmarks claim Qwen3-8B ~
Qwen2.5-14B quality). Initial problems and their real causes:
- **Slow replies** -> qwen3 defaults to "thinking mode." Fixed via
  think=False on both ollama.chat() calls — **[APPLIED, CONFIRMED
  LIVE]**, see §1.
- **Only 70-75% GPU utilization** -> NOT other apps stealing VRAM (baseline
  nvidia-smi was a clean 0MiB before Ollama loaded anything) — it's
  simply that qwen3:8b's weights + default 4096-token KV cache slightly
  exceed a 6GB card's capacity. Fixed via num_ctx: 2048 in the same
  ollama.chat() calls — **[APPLIED, CONFIRMED LIVE]**.
- **Flash attention attempt** -> crashed (see §4 loose ends), reverted.
- **A confusing mid-session regression** (GPU % got worse, not better,
  right after enabling flash attention) turned out to be **zombie
  llama-server.exe processes** stacking up from repeated crashed load
  attempts, not a real settings problem — resolved by fully killing all
  Ollama-related processes (tray app included) and restarting clean.
  **Lesson for next time: always check Get-Process | Where-Object
  {$_.ProcessName -like "*ollama*"} and a clean nvidia-smi baseline
  before trusting any single ollama ps reading as diagnostic.**

---

## 6. Mistakes made this session, worth not repeating

- **A substring search ('nurse' in ... or 'joy' in ...) misidentified an
  NPC.** Key 0:5:19 matched the search but was actually a Lilycove
  honeymoon-tourist couple, not Nurse Joy — her card was nearly deleted
  based on a bad match. Lesson: a text-match search finding a key is not
  the same as confirming *which* NPC that key actually represents; always
  print and read the full cached card content before deleting anything,
  not just the key name or a substring hit.
- **A stale .git\\index.lock** from a sandboxed Claude Code session (which
  correctly refused to commit a truncated file-mirror, but left a lock
  behind) blocked all git commands until manually deleted
  (del .git\\index.lock) — if git commands mysteriously fail with "not a
  git repository" or similar after a Cowork/sandbox session touches the
  repo, check for and clear this first.
- **Windows PowerShell intermittently failed to accept credential-prompt
  input** (typing appeared to do nothing at a git push username/password
  prompt) — Git Bash handled the identical push cleanly every time this
  came up. If PowerShell's credential prompt seems stuck/unresponsive,
  switch to Git Bash rather than debugging PowerShell further.
- **Multi-line commit messages pasted as multiple separate lines into
  PowerShell** occasionally caused git commit -m "..." to be interpreted
  oddly across prompt boundaries — pasting the entire multi-line -m
  block as one contiguous paste (rather than line-by-line) avoided this.

---

## 7. Quick reference — where things are

- Bridge: bridge/dialogue_bridge_server.py (3 backends: ollama/gemini/
  groq; hardened JSON parsing; exception-safe; mined-table-aware for the
  5 pilot maps; qwen3 think=False + num_ctx 2048 applied)
- Mined data: extraction/npc_dialogue_table.json,
  extraction/COVERAGE_REPORT.md, extraction/raw/*.json
- Personas + runtime state: npc_profiles.json (gitignored, NOT tracked —
  editing/deleting entries needs no git commit ever)
- Hook: lua/mgba_hook.lua v4 (§2's true-skip fix is the first hook edit
  since v4 landed — treat any hook change as higher-stakes than bridge
  Python changes)
- Quest engine (parked, diagnostic prompt written, never run):
  bridge/quest_bridge_server.py, bridge/quest_engine.py
- Subagent config: .claude/agents/map-extractor.md (Sonnet-pinned,
  read-only, reusable for the eventual full-map rollout)
- Docs: docs/LIVING_HOENN_HANDOVER.md, docs/LIVING_HOENN_HANDOVER_2.md,
  this file (docs/LIVING_HOENN_HANDOVER_3.md once committed)
- Repo: https://github.com/abhishek-rathod01/Living-Hoenn.git, branch
  main. Confirm git log origin/main --oneline -3 before assuming
  anything below §1-2 is still current if picking this up much later.
