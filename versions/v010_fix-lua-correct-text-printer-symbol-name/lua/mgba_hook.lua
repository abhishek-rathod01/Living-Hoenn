-- ============================================================================
-- mgba_hook.lua  (v2 -- source-verified)  --  emulator side of the bridge.
-- ============================================================================

local HOST = "127.0.0.1"
local PORT = 8888

local ADDR_PLAYER_PARTY      = nil
local ADDR_PARTY_COUNT       = nil
local ADDR_STRINGVAR4        = nil
local ADDR_FIELD_MSG_MODE    = nil
local ADDR_TEXTPRINTER0      = nil  -- symbol: sTextPrinters (STATIC; window 0 = element [0])
local ADDR_SAVEBLOCK1_PTR    = nil
local SAVEBLOCK1_MAP_OFFSET  = nil

local MON_SIZE          = 100
local OFF_PERSONALITY   = 0
local OFF_OTID          = 4
local OFF_SECURE        = 32
local OFF_LEVEL         = 84
local SUBSTRUCT_SIZE    = 12
local GROWTH_POS = {[0]=0,0,0,0,0,0,1,1,2,3,2,3,1,1,2,3,2,3,1,1,2,3,2,3}

local TP_CURRENTCHAR = 0x00
local TP_ACTIVE      = 0x1B
local TP_STATE       = 0x1C
local FIELD_MSG_HIDDEN = 0
local STRING_TERMINATOR = 0xFF

local SPECIES, CHARMAP = {}, {}
do
  local okS, s = pcall(dofile, "species_names.lua")
  if okS and type(s) == "table" then SPECIES = s end
  local okC, c = pcall(dofile, "charmap.lua")
  if okC and type(c) == "table" then CHARMAP = c end
end
local REVCHARMAP = {}
for ch, b in pairs(CHARMAP) do REVCHARMAP[b] = ch end

local function jsonEscape(s)
  s = tostring(s):gsub("\\", "\\\\"):gsub('"', '\\"')
  return (s:gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t"))
end
local function jsonEncode(t)
  local parts = {}
  for k, v in pairs(t) do
    local val
    if type(v) == "number" then val = tostring(v)
    elseif type(v) == "table" then
      local items = {}
      for _, it in ipairs(v) do items[#items+1] = '"'..jsonEscape(it)..'"' end
      val = "["..table.concat(items, ",").."]"
    else val = '"'..jsonEscape(v)..'"' end
    parts[#parts+1] = '"'..jsonEscape(k)..'":'..val
  end
  return "{"..table.concat(parts, ",").."}"
end

local function readSpeciesAt(base)
  local pid   = emu:read32(base + OFF_PERSONALITY)
  local otId  = emu:read32(base + OFF_OTID)
  local key   = pid ~ otId
  local gslot = GROWTH_POS[pid % 24]
  local encWord = emu:read32(base + OFF_SECURE + gslot * SUBSTRUCT_SIZE)
  return (encWord ~ key) & 0xFFFF
end

local function readParty()
  local names, highest = {}, 0
  if not (ADDR_PLAYER_PARTY and ADDR_PARTY_COUNT) then return names, highest end
  local count = emu:read8(ADDR_PARTY_COUNT)
  if count > 6 then count = 6 end
  for i = 0, count - 1 do
    local base = ADDR_PLAYER_PARTY + i * MON_SIZE
    local lvl = emu:read8(base + OFF_LEVEL)
    if lvl > highest then highest = lvl end
    local sp = readSpeciesAt(base)
    names[#names + 1] = SPECIES[sp] or ("#" .. sp)
  end
  return names, highest
end

local function decodeGameString(addr, maxLen)
  local out = {}
  for i = 0, (maxLen or 200) - 1 do
    local b = emu:read8(addr + i)
    if b == STRING_TERMINATOR then break end
    out[#out + 1] = REVCHARMAP[b] or " "
  end
  return table.concat(out)
end

local function encodeEmerald(text)
  local bytes = {}
  for i = 1, #text do
    local ch = text:sub(i, i)
    bytes[#bytes + 1] = CHARMAP[ch] or CHARMAP[" "] or 0x00
  end
  bytes[#bytes + 1] = STRING_TERMINATOR
  return bytes
end

local function restartPrinter()
  if not ADDR_TEXTPRINTER0 then return end
  emu:write32(ADDR_TEXTPRINTER0 + TP_CURRENTCHAR, ADDR_STRINGVAR4)
  emu:write8 (ADDR_TEXTPRINTER0 + TP_ACTIVE, 1)
  emu:write8 (ADDR_TEXTPRINTER0 + TP_STATE, 0)
end

local function writeToBuffer(text)
  for i, b in ipairs(encodeEmerald(text)) do
    emu:write8(ADDR_STRINGVAR4 + (i - 1), b)
  end
  restartPrinter()
end

local sock, rxBuffer, awaitingReply = nil, "", false

local function onReceived()
  while true do
    local data = sock:receive(4096)
    if data == nil or #data == 0 then break end
    rxBuffer = rxBuffer .. data
  end
  while true do
    local nl = rxBuffer:find("\n", 1, true)
    if not nl then break end
    local line = rxBuffer:sub(1, nl - 1)
    rxBuffer = rxBuffer:sub(nl + 1)
    if #line > 0 then
      writeToBuffer(line)
      awaitingReply = false
    end
  end
end

local function connect()
  sock = socket.connect(HOST, PORT)
  if not sock then console:error("[hook] no bridge"); return false end
  sock:add("received", onReceived)
  sock:add("error", function() console:error("[hook] socket error") end)
  return true
end

local lastMode = 0

local function onFrame()
  if not sock or awaitingReply then return end
  if not ADDR_FIELD_MSG_MODE then return end
  local mode = emu:read8(ADDR_FIELD_MSG_MODE)
  local opened = (lastMode == FIELD_MSG_HIDDEN and mode ~= FIELD_MSG_HIDDEN)
  lastMode = mode
  if not opened then return end

  local original = ADDR_STRINGVAR4 and decodeGameString(ADDR_STRINGVAR4) or ""
  local party, highest = readParty()
  local ctx = {
    npc_role      = "an NPC in Hoenn",
    original_line = original,
    player_level  = highest,
    player_party  = party,
    situation     = "The player is talking to this NPC.",
  }
  awaitingReply = true
  if ADDR_STRINGVAR4 then
    emu:write8(ADDR_STRINGVAR4, STRING_TERMINATOR)
    restartPrinter()
  end
  sock:send(jsonEncode(ctx) .. "\n")
end

if connect() then
  callbacks:add("frame", onFrame)
end
