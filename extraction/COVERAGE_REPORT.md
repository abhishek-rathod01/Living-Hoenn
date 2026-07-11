# NPC extraction pilot — coverage report (5 maps)

Generated 2026-07-11. Pipeline: one map-extractor subagent per map (read-only,
against the local pokeemerald clone) → per-map raw JSON in `extraction/raw/` →
`extraction/merge_npc_tables.py` → `extraction/npc_dialogue_table.json`,
keyed `map_group:map_num:local_id` (same convention as `npc_profiles.json` /
`persona_engine.py`; LOCALID = 1-based `object_events` position, confirmed in
`tools/mapjson/mapjson.cpp` line 416: `#define <local_id> i + 1`).

**Not wired into the bridge.** Extraction pipeline only.

## Coverage

| Map | (group:num) | object events | dialogue lines | resolved from source | trainer NPCs | gifts |
|---|---|---|---|---|---|---|
| Slateport City | 0:1 | 35 | 69 | 69 (100%) | 0 | 1 |
| Fortree City | 0:4 | 7 | 10 | 10 (100%) | 0 | 0 |
| Lilycove City | 0:5 | 22 | 40 | 40 (100%) | 1 (6 gender×starter variants) | 2 |
| Route 110 | 0:25 | 36 | 54 | 54 (100%) | 15 (14 fixed + rival with 6 variants) | 4 |
| Slateport Pokémon Center 1F | 9:11 | 3 | 12 | 12 (100%) | 0 | 0 |
| **Total** | | **103** | **185** | **185** | **16 objects** | **7** |

"Resolved from source" means the text was pulled from the actual `.string`
blocks in the pokeemerald `data/` tree by the merge script's own parser
(7,953 labels indexed) — not taken from the subagent's transcription. Where a
subagent supplied text AND a label (Fortree, Pokémon Center), the two were
compared after whitespace normalization: **0 disagreements** after removing
transcription annotations, so agent extraction and independent parsing agree
on every line they both cover.

Route 110 did **not** break the extractor — all 36 object events parsed;
no fallback to Route 102 was needed.

## Shared scripts (need distinct persona keys)

One script is referenced by more than one object event:

- `BerryTreeScript` ← `0:25:16`, `0:25:17`, `0:25:18` (Route 110's three
  Nanab berry trees). Identical extracted data, three distinct local IDs —
  personas must be keyed per local_id, never per script. Flagged in the
  merged table's `_shared_scripts` section and asserted in `run_all_tests.py`.

No cross-NPC script sharing exists on the other four maps (`0x0` no-script
objects excluded — they have no dialogue script to share).

## Trainers resolved (party cross-checked in trainer_parties.h)

- Route 110: Jasmine, Anthony, Abigail(_1), Benjamin(_1), Edward, Jaclyn,
  Edwin(_1), Dale, Jacob, Timmy, Isabel(_1), Kaleb, Alyssa, Joseph — full
  parties (species/lvl/iv, held items and fixed moves where the struct has
  them). Rival (local 28): 6 constants (May/Brendan × 3 starters), driven by
  coord_event scenes, example party recorded.
- Lilycove City: Rival (local 17): all 6 gender×starter variants with full
  4-mon parties.
- Hand-verified this session (two independent ways: script macro in the map's
  `scripts.inc` + party struct in `trainer_parties.h`):
  `TRAINER_MAY_LILYCOVE_TREECKO` → `sParty_MayLilycoveTreecko` and
  `TRAINER_JASMINE` → `sParty_Jasmine` (via `.party = NO_ITEM_DEFAULT_MOVES`).
  Jacob's `.iv = 200` third slot is verbatim source (the `.iv` field is a
  0–255 fixed-IV scalar in this struct, so 200 is legal), recorded as-is.

## Gifts found

- `0:1:34` Slateport Berry Powder Clerk: `giveitem ITEM_POWDER_JAR` ×1
  (first visit, sets `FLAG_RECEIVED_POWDER_JAR`) — verified against raw
  `scripts.inc` line 711.
- `0:5:11` Lilycove item ball: `ITEM_MAX_REPEL` ×1 (finditem).
- `0:25:19/20/35` Route 110 item balls: `ITEM_DIRE_HIT`, `ITEM_RARE_CANDY`,
  `ITEM_ELIXIR` ×1 each (finditem).
- `0:25:28` Route 110 rival scene: `ITEM_ITEMFINDER` ×1 post-battle.
- `0:5:16` Lilycove Berry Gentleman: **dynamic** — see below.

## Honest list of unparseable / not-statically-resolvable constructs

1. **Dynamic gift item** — `0:5:16` (Lilycove Berry Gentleman): item is
   `random 10` + `FIRST_BERRY_INDEX` at runtime; no fixed `ITEM_` constant
   exists. Recorded as `DYNAMIC`, not guessed.
2. **Dynamic exchange item** — `0:1:34` (Berry Powder Clerk): the exchange
   menu gives 1 of 11 items via `VAR_0x8008`; all 11 candidates listed with
   berry-powder costs, but the actual item is a runtime choice.
3. **Non-item reward** — `0:1:23` (Effort Ribbon Woman): awards a ribbon via
   `special GiveLeadMonEffortRibbon`; there is no item id/qty to record.
4. **Script `0x0` objects** — `0:1:35` (Scott), `0:25:26` (background Aqua
   grunt), `0:25:28`/`0:25:29` (rival / rival-on-bike), `0:25:36` (Birch):
   no per-object interact script exists. Where the NPC still speaks (Scott,
   rival, Birch) the lines come from map-level `OnFrame` / coord_event scene
   scripts and were extracted from those, flagged as scene-driven.
5. **Dynamic sprites** — `OBJ_EVENT_GFX_VAR_0`/`VAR_3` (both rivals): actual
   May/Brendan sprite chosen at runtime by `Common_EventScript_SetupRivalGfxId`.
6. **Rematch parties** — Abigail/Benjamin/Edwin/Isabel use
   `trainerbattle_rematch` on their `_1` constant; the escalated `_2`…`_5`
   parties are chosen by the engine's runtime rematch table, which is not
   visible in the map script. First-battle parties recorded; rematch tiers
   noted but not expanded.
7. **Engine specials as conditions** — e.g. `CountPlayerTrainerStars`,
   `IsPokerusInParty`, `GetPlayerAvatarBike`, `ShouldTryRematchBattle`:
   recorded verbatim as conditions; they are native code, not further
   decomposable from script.
8. **Cycling challenge rank reactions** — `0:25:21`'s coord_event end-of-run
   script branches on a rank via `switch VAR_RESULT` (Best/Good/OK/Bad/Worst);
   noted, individual rank lines not keyed to the object's own interact script.
9. **Out of scope by design**: bg_events (signs, hidden items) and warp
   events are not object events and were recorded only as notes; the Lua
   hook treats signs separately (`npc_id==0`, `INTERCEPT_SIGNS`).

## Hand-verification performed this session (not subagent self-report)

- Fortree City: full `map.json` + full `scripts.inc` read directly; all 7
  object events, the Woman's `goto_if_set FLAG_KECLEON_FLED_FORTREE`
  conditional, the Kecleon Devon-Scope flow, and the absence of any
  `trainerbattle`/`giveitem` confirmed line-by-line.
- Slateport PC 1F: full `map.json` + `scripts.inc` read; nurse branches
  (gold card / pokérus / union room flags) confirmed in
  `data/scripts/pkmn_center_nurse.inc` (lines 5–116).
- Lilycove: `TRAINER_MAY_LILYCOVE_TREECKO` party (trainers.h:7984,
  trainer_parties.h:8978) and ExpertM2's `FLAG_BADGE07_GET` branch
  (scripts.inc:112–118).
- Slateport City: Girl's 3-branch conditional (scripts.inc:190–197) and
  Powder Jar `giveitem` (scripts.inc:709–713).
- Route 110: Jasmine `trainerbattle_single` (scripts.inc:230) +
  `sParty_Jasmine` (trainer_parties.h:4803), ChallengeGuy conditionals
  (scripts.inc:143–151), Jacob `.iv = 200` (trainer_parties.h:4736).
- Key convention: `tools/mapjson/mapjson.cpp:416` proves LOCALID = 1-based
  array position; `map_groups.json` derivation matches `world_tables.py`'s
  MAPS for all five (group, num) pairs.
