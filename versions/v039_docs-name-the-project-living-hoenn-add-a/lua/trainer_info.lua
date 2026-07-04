-- ============================================================================
-- trainer_info.lua -- read a trainer's class + name from the ROM gTrainers
-- table. Groundwork for Phase 5 (PokeNav Match Call personalities).
--
-- VERIFIED (compile + source header comments agree):
--   sizeof(struct Trainer) = 0x28
--   trainerClass @ +0x01 (u8) | trainerName @ +0x04 (11 bytes, 0xFF-terminated)
--   partySize @ +0x20 | party ptr @ +0x24
--
-- USAGE (from mgba_hook or a match-call hook):
--   local T = dofile("trainer_info.lua")
--   local cls  = T.readClassId(ADDR_GTRAINERS, trainerId)          -- number
--   local name = T.readName(ADDR_GTRAINERS, trainerId, REVCHARMAP)  -- string
-- ADDR_GTRAINERS: grep gTrainers in your pokeemerald.map (ROM symbol, static
-- for a given build). trainerId source for calls: read16 at
-- sMatchCallState + 4 (verified: struct MatchCallState { u32 minutes;
-- u16 trainerId; ... }). MATCH-CALL TRIGGER PATTERN: poll that u16 each
-- frame; a 0 -> nonzero transition means a call is starting -- fetch class +
-- name, ship to the bridge, and rewrite gStringVar4 before the call's text
-- printer runs. (Python maps class id -> display name via world_tables.py.)
-- ============================================================================
local M = {}
M.TRAINER_SIZE = 0x28
M.OFF_CLASS    = 0x01
M.OFF_NAME     = 0x04
M.NAME_MAX     = 11
local TERMINATOR = 0xFF

function M.readClassId(gTrainers, trainerId)
  return emu:read8(gTrainers + trainerId * M.TRAINER_SIZE + M.OFF_CLASS)
end

function M.readName(gTrainers, trainerId, revCharmap)
  local base = gTrainers + trainerId * M.TRAINER_SIZE + M.OFF_NAME
  local out = {}
  for i = 0, M.NAME_MAX - 1 do
    local b = emu:read8(base + i)
    if b == TERMINATOR then break end
    out[#out + 1] = revCharmap[b] or "?"
  end
  return table.concat(out)
end

return M
