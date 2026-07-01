-- ============================================================================
-- mgba_hook.lua  (v2 -- source-verified)  --  emulator side of the bridge.
--
-- Every offset, address role, and mechanism below was verified against the real
-- pokeemerald source (see VERIFICATION_REPORT.md). The ONLY things left for you
-- are the numeric ADDR_* values, which are build-specific and must come from
-- YOUR pokeemerald.map (or datacrystal for vanilla US Emerald). Grep help is in
-- the report.
--
-- Load via mGBA: Tools -> Scripting... -> File -> Load script. Needs mGBA 0.10+.
-- ============================================================================

local HOST = "127.0.0.1"
local PORT = 8888

-- ---------------------------------------------------------------------------
-- ADDRESSES YOU MUST FILL IN  (grep your pokeemerald.map for the symbol name)
-- ---------------------------------------------------------------------------
local ADDR_PLAYER_PARTY      = nil  -- symbol: gPlayerParty        (struct, 100 bytes/slot)
local ADDR_PARTY_COUNT       = nil  -- symbol: gPlayerPartyCount   (u8)
local ADDR_STRINGVAR4        = nil  -- symbol: gStringVar4         (dialogue buffer)
local ADDR_FIELD_MSG_MODE    = nil  -- symbol: sFieldMessageBoxMode (static u8; 0 = hidden)
local ADDR_TEXTPRINTER0      = nil  -- symbol: sTextPrinters (STATIC; window 0 = element [0].
                                    --   base address IS element [0]. Stride is 0x24 if you
                                    --   ever need another window: element[i] = base + i*0x24)
-- Optional enrichment (needs the SaveBlock1.location field offset -- see report):
local ADDR_SAVEBLOCK1_PTR    = nil  -- symbol: gSaveBlock1Ptr (pointer; DMA-relocated data)
local SAVEBLOCK1_MAP_OFFSET  = nil  -- offset of the map location field within SaveBlock1

-- ---------------------------------------------------------------------------
-- VERIFIED CONSTANTS (from pokeemerald; do not change)
-- ---------------------------------------------------------------------------
local MON_SIZE          = 100   -- sizeof(struct Pokemon)
local OFF_PERSONALITY   = 0     -- u32
local OFF_OTID          = 4     -- u32
local OFF_SECURE        = 32    -- start of encrypted substructs (48 bytes)
local OFF_LEVEL         = 84    -- u8, UNENCRYPTED  <- level needs no decryption
local SUBSTRUCT_SIZE    = 12
-- personality%24 -> physical slot holding the Growth substruct (species lives there)
local GROWTH_POS = {[0]=0,0,0,0,0,0,1,1,2,3,2,3,1,1,2,3,2,3,1,1,2,3,2,3}

-- Text printer field offsets (within sTextPrinters[0]) for the re-render trick.
-- VERIFIED via 32-bit-accurate compile: currentChar@0x00, active@0x1B, state@0x1C.
-- state=0 is RENDER_STATE_HANDLE_CHAR (the printer's start state), confirmed in text.c.
local TP_CURRENTCHAR = 0x00   -- const u8* currentChar
local TP_ACTIVE      = 0x1B   -- u8 active
local TP_STATE       = 0x1C   -- u8 state
local FIELD_MSG_HIDDEN = 0
local STRING_TERMINATOR = 0xFF

-- ---------------------------------------------------------------------------
-- Load the generated tables (species + charmap). If your mGBA build doesn't
-- allow dofile, paste the contents of those two files inline instead.
-- ---------------------------------------------------------------------------
local SPECIES, CHARMAP = {}, {}
do
  local okS, s = pcall(dofile, "species_names.lua")
  if okS and type(s) == "table" then SPECIES = s
  else console:warn("[hook] couldn't dofile species_names.lua -- paste it inline") end
  local okC, c = pcall(dofile, "charmap.lua")
  if okC and type(c) == "table" then CHARMAP = c
  else console:warn("[hook] couldn't dofile charmap.lua -- paste it inline") end
end
local REVCHARMAP = {}                       -- for decoding the ORIGINAL line
for ch, b in pairs(CHARMAP) do REVCHARMAP[b] = ch end

-- ===========================================================================
-- Tiny JSON encoder (flat tables: strings, numbers, arrays of strings)
-- ===========================================================================
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

-- ===========================================================================
-- Reading game state (all VERIFIED offsets)
-- ===========================================================================
-- Portable 32-bit bit-ops. mGBA may link Lua 5.1/5.2 or LuaJIT, where the native
-- ~ and & operators DON'T EXIST -- using them would be a load-time syntax error
-- that breaks the whole script. These arithmetic versions work on every Lua
-- version and were verified equal to native XOR/mask across 5000 cases.
local function u32(x) return x % 4294967296 end
local function bxor(a, b)
  a, b = u32(a), u32(b)
  local res, p = 0, 1
  for _ = 1, 32 do
    local abit, bbit = a % 2, b % 2
    if abit ~= bbit then res = res + p end
    a = (a - abit) / 2
    b = (b - bbit) / 2
    p = p * 2
  end
  return res
end

local function readSpeciesAt(base)
  -- Decrypt the first word of the Growth substruct to get species.
  -- u32() forces the UNSIGNED value so `pid % 24` (which selects the substruct
  -- order) is correct even if the binding returns a signed int -- otherwise any
  -- mon with the high personality bit set decodes wrong.
  local pid     = u32(emu:read32(base + OFF_PERSONALITY))
  local otId    = u32(emu:read32(base + OFF_OTID))
  local key     = bxor(pid, otId)
  local gslot   = GROWTH_POS[pid % 24]
  local encWord = u32(emu:read32(base + OFF_SECURE + gslot * SUBSTRUCT_SIZE))
  return bxor(encWord, key) % 65536     -- % 0x10000 == low 16 bits = species
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

-- ===========================================================================
-- Text: decode the original line (context) and encode our reply
-- ===========================================================================
local function decodeGameString(addr, maxLen)
  local out = {}
  for i = 0, (maxLen or 200) - 1 do
    local b = emu:read8(addr + i)
    if b == STRING_TERMINATOR then break end
    out[#out + 1] = REVCHARMAP[b] or " "
  end
  return table.concat(out)
end

-- gStringVar4 is 1000 bytes (0x3E8). Cap well under that (and small enough to
-- fit the dialogue box): a long/runaway reply must NOT overflow into adjacent
-- EWRAM and corrupt other game state.
local MAX_DIALOGUE_BYTES = 250

local function encodeEmerald(text)
  local bytes = {}
  for i = 1, #text do
    if #bytes >= MAX_DIALOGUE_BYTES then break end   -- hard cap: never overflow
    local ch = text:sub(i, i)
    bytes[#bytes + 1] = CHARMAP[ch] or CHARMAP[" "] or 0x00
  end
  bytes[#bytes + 1] = STRING_TERMINATOR
  return bytes
end

-- Force the field text printer to re-render from the top of gStringVar4.
-- Memory-only replacement for calling AddTextPrinterForMessage (Lua can't call
-- ROM functions). Verified against struct TextPrinter offsets.
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

-- ===========================================================================
-- Socket (non-blocking receive via 'received' callback -- verified API)
-- ===========================================================================
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
      console:log("[hook] LLM dialogue: " .. line)
      writeToBuffer(line)
      awaitingReply = false
    end
  end
end

local function connect()
  sock = socket.connect(HOST, PORT)          -- blocks only for localhost handshake
  if not sock then console:error("[hook] no bridge at "..HOST..":"..PORT); return false end
  sock:add("received", onReceived)
  sock:add("error", function() console:error("[hook] socket error") end)
  console:log("[hook] connected to bridge")
  return true
end

-- ===========================================================================
-- Per-frame trigger: fire on the rising edge of sFieldMessageBoxMode.
-- ===========================================================================
local lastMode = 0
local waitFrames = 0
local WAIT_TIMEOUT = 600   -- ~10s at 60fps; if no reply by then, recover instead of hanging

local function onFrame()
  if not sock then return end
  -- While waiting on a reply, count frames so a dead/slow bridge can't wedge us
  -- forever with a blank box.
  if awaitingReply then
    waitFrames = waitFrames + 1
    if waitFrames >= WAIT_TIMEOUT then
      console:warn("[hook] no reply in time -- is bridge_server.py running? Recovering.")
      if ADDR_STRINGVAR4 then writeToBuffer("...") end   -- don't leave the box blank
      awaitingReply = false
    end
    return
  end
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
  waitFrames = 0                              -- start the recovery timer
  if ADDR_STRINGVAR4 then                     -- blank the box while we wait
    emu:write8(ADDR_STRINGVAR4, STRING_TERMINATOR)
    restartPrinter()
  end
  sock:send(jsonEncode(ctx) .. "\n")
  console:log("[hook] sent context (original: '" .. original .. "')")
end

-- ===========================================================================
-- Boot
-- ===========================================================================
if connect() then
  callbacks:add("frame", onFrame)
  console:log("[hook] running. Fill ADDR_* values to enable triggers.")
end
