-- ============================================================================
-- party_reader.lua  --  STANDALONE address-validation tool (no bridge, no LLM).
-- Load in mGBA to confirm your party addresses are correct before wiring the
-- full bridge. Shows live levels + species names in a console buffer.
-- ============================================================================

local ADDR_PLAYER_PARTY = nil   -- symbol: gPlayerParty
local ADDR_PARTY_COUNT  = nil   -- symbol: gPlayerPartyCount

local MON_SIZE       = 100
local OFF_PERSONALITY= 0
local OFF_OTID       = 4
local OFF_SECURE     = 32
local OFF_LEVEL      = 84
local SUBSTRUCT_SIZE = 12
local GROWTH_POS = {[0]=0,0,0,0,0,0,1,1,2,3,2,3,1,1,2,3,2,3,1,1,2,3,2,3}

local SPECIES = {}
do
  local ok, s = pcall(dofile, "species_names.lua")
  if ok and type(s) == "table" then SPECIES = s end
end

local function decodeSpecies(base)
  local pid   = emu:read32(base + OFF_PERSONALITY)
  local otId  = emu:read32(base + OFF_OTID)
  local key   = pid ~ otId
  local gslot = GROWTH_POS[pid % 24]
  local word  = emu:read32(base + OFF_SECURE + gslot * SUBSTRUCT_SIZE)
  return (word ~ key) & 0xFFFF
end

local function readPartyList()
  local out = {}
  if not (ADDR_PLAYER_PARTY and ADDR_PARTY_COUNT) then return out end
  local count = emu:read8(ADDR_PARTY_COUNT)
  if count > 6 then count = 6 end
  for i = 0, count - 1 do
    local base = ADDR_PLAYER_PARTY + i * MON_SIZE
    local sp = decodeSpecies(base)
    out[#out + 1] = {
      slot = i + 1,
      level = emu:read8(base + OFF_LEVEL),
      species = sp,
      name = SPECIES[sp] or ("#" .. sp),
    }
  end
  return out
end

local function formatParty()
  if not (ADDR_PLAYER_PARTY and ADDR_PARTY_COUNT) then
    return "Fill in ADDR_PLAYER_PARTY and ADDR_PARTY_COUNT (grep your .map)."
  end
  local list = readPartyList()
  if #list == 0 then return "Party count = 0." end
  local lines = { "Party (" .. #list .. "):" }
  for _, m in ipairs(list) do
    lines[#lines + 1] = string.format("  %d. %-11s Lv%-3d  (species #%d)",
                                       m.slot, m.name, m.level, m.species)
  end
  return table.concat(lines, "\n")
end

local buf = console:createBuffer("Party Reader")
local frames = 0
callbacks:add("frame", function()
  frames = frames + 1
  if frames % 30 == 0 then
    buf:clear()
    buf:print(formatParty())
  end
end)
buf:print(formatParty())
console:log("[party_reader] loaded.")
