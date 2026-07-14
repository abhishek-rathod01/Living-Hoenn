-- Auto-generated: npc_key ("map_group:map_num:npc_id") -> numeric trainer ID.
-- Generation method (regenerate, don't hand-edit):
--   1. extraction/npc_dialogue_table.json (read-only) -- for each NPC whose
--      "trainerbattle" field is a SINGLE object (not a list), take its
--      "trainer" constant name. List-shaped entries are multi-variant
--      (e.g. the gender x starter rival) with no one true trainer for this
--      object, so they are deliberately excluded here.
--   2. pokeemerald include/constants/opponents.h -- look up that constant's
--      numeric #define value.
-- The hook combines this with TRAINER_FLAGS_START (verified in mgba_hook.lua)
-- to read the real "has this trainer been fought" flag, same formula as
-- pokeemerald's own HasTrainerBeenFought() (src/battle_setup.c).
-- Scope: pilot maps only (Route 110, map_group:map_num = 0:25) -- same pilot
-- scope as npc_dialogue_table.json itself. Entries verified against the raw
-- opponents.h lines:
--   TRAINER_JASMINE 359, TRAINER_ANTHONY 352, TRAINER_ABIGAIL_1 358,
--   TRAINER_BENJAMIN_1 353, TRAINER_EDWARD 232, TRAINER_JACLYN 243,
--   TRAINER_EDWIN_1 512, TRAINER_DALE 341, TRAINER_JACOB 351,
--   TRAINER_TIMMY 334, TRAINER_ISABEL_1 302, TRAINER_KALEB 699,
--   TRAINER_ALYSSA 701, TRAINER_JOSEPH 700
local TRAINER_ID_BY_KEY = {
  ["0:25:8"]  = 359,  -- TRAINER_JASMINE
  ["0:25:9"]  = 352,  -- TRAINER_ANTHONY
  ["0:25:10"] = 358,  -- TRAINER_ABIGAIL_1
  ["0:25:11"] = 353,  -- TRAINER_BENJAMIN_1
  ["0:25:12"] = 232,  -- TRAINER_EDWARD
  ["0:25:13"] = 243,  -- TRAINER_JACLYN
  ["0:25:14"] = 512,  -- TRAINER_EDWIN_1
  ["0:25:15"] = 341,  -- TRAINER_DALE
  ["0:25:27"] = 351,  -- TRAINER_JACOB
  ["0:25:30"] = 334,  -- TRAINER_TIMMY
  ["0:25:31"] = 302,  -- TRAINER_ISABEL_1
  ["0:25:32"] = 699,  -- TRAINER_KALEB
  ["0:25:33"] = 701,  -- TRAINER_ALYSSA
  ["0:25:34"] = 700,  -- TRAINER_JOSEPH
}

return TRAINER_ID_BY_KEY
