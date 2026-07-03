-- ============================================================================
-- mgba_hook.lua  (v3 -- quest-capable)  --  emulator side of the bridge.
--
-- Works with bridge_server.py (dialogue only) OR quest_bridge_server.py
-- (dialogue + quests). Replies may be action-prefixed:
--     "take_item:139:2;give_item:13:1|My berries! Take this."
-- Actions execute against verified memory layouts; unknown actions are ignored.
--
-- All offsets/mechanisms verified against pokeemerald + mGBA source
-- (docs/VERIFICATION_REPORT.md). Fill in the ADDR_* values from YOUR
-- pokeemerald.map. Portable Lua (5.1/5.2/5.3/5.4/LuaJIT): no native bit-ops.
-- ============================================================================

local HOST = "127.0.0.1"
local PORT = 8888

-- ---------------- ADDRESSES: grep your pokeemerald.map ----------------------
local ADDR_PLAYER_PARTY   = nil  -- gPlayerParty
local ADDR_PARTY_COUNT    = nil  -- gPlayerPartyCount
local ADDR_STRINGVAR4     = nil  -- gStringVar4
local ADDR_FIELD_MSG_MODE = nil  -- sFieldMessageBoxMode (static)
local ADDR_TEXTPRINTER0   = nil  -- sTextPrinters (static; element [0]; stride 0x24)
local ADDR_LAST_TALKED    = nil  -- gSpecialVar_LastTalked (u16; NPC local id)
local ADDR_SAVEBLOCK1_PTR = nil  -- gSaveBlock1Ptr (pointer; data is DMA-relocated)
local ADDR_SAVEBLOCK2_PTR = nil  -- gSaveBlock2Ptr (pointer; holds encryptionKey)

-- ---------------- VERIFIED CONSTANTS (do not change) ------------------------
local MON_SIZE, OFF_PERSONALITY, OFF_OTID = 100, 0, 4
local OFF_SECURE, OFF_LEVEL, SUBSTRUCT_SIZE = 32, 84, 12
local GROWTH_POS = {[0]=0,0,0,0,0,0,1,1,2,3,2,3,1,1,2,3,2,3,1,1,2,3,2,3}
local TP_CURRENTCHAR, TP_ACTIVE, TP_STATE = 0x00, 0x1B, 0x1C
local FIELD_MSG_HIDDEN, STRING_TERMINATOR = 0, 0xFF
-- SaveBlock1 field offsets (include/global.h):
local SB1_MAPGROUP, SB1_MAPNUM = 0x04, 0x05     -- location (WarpData)
local SB1_BAG_ITEMS, N_ITEMS   = 0x560, 30      -- struct ItemSlot{u16 id,u16 qty}
local SB1_BAG_KEYITEMS, N_KEY  = 0x5D8, 30      -- tickets live here
local SB1_BAG_BERRIES, N_BERR  = 0x790, 46
local POCKETS = {                                -- name -> {offset, count}
  items   = {SB1_BAG_ITEMS,   N_ITEMS},
  key     = {SB1_BAG_KEYITEMS, N_KEY},
  berries = {SB1_BAG_BERRIES, N_BERR},
}
-- Island unlock flags (verified: harbor scripts goto_if_unset these)
local UNLOCK_FLAGS = {0x8B3, 0x8D5, 0x8D6, 0x8E0}  -- southern,birth,faraway,navel
local SB1_FLAGS                = 0x1270         -- flags[id/8] |= 1<<(id%8)
-- SaveBlock2 field offset:
local SB2_ENCKEY               = 0xAC           -- u32; bag qty stored as qty^key(lo16)

-- ---------------- portable bit helpers (no native ~ & | << >>) -------------
local function u32(x) return x % 4294967296 end
local function bxor(a, b)
  a, b = u32(a), u32(b)
  local res, p = 0, 1
  for _ = 1, 32 do
    local ab, bb = a % 2, b % 2
    if ab ~= bb then res = res + p end
    a = (a - ab) / 2; b = (b - bb) / 2; p = p * 2
  end
  return res
end
local function getbit(v, n) return math.floor(v / 2^n) % 2 end

-- ---------------- data tables ----------------------------------------------
local SPECIES, CHARMAP = {}, {}
do
  local okS, s = pcall(dofile, "species_names.lua")
  if okS and type(s) == "table" then SPECIES = s
  else console:warn("[hook] dofile species_names.lua failed -- paste inline") end
  local okC, c = pcall(dofile, "charmap.lua")
  if okC and type(c) == "table" then CHARMAP = c
  else console:warn("[hook] dofile charmap.lua failed -- paste inline") end
end
local REVCHARMAP = {}
for ch, b in pairs(CHARMAP) do REVCHARMAP[b] = ch end

-- ---------------- tiny JSON encoder (flat: str/num/array-of-str) -----------
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

-- ---------------- save-block plumbing --------------------------------------
local function sb1() return ADDR_SAVEBLOCK1_PTR and u32(emu:read32(ADDR_SAVEBLOCK1_PTR)) or nil end
local function encKeyLo16()
  if not ADDR_SAVEBLOCK2_PTR then return nil end
  local sb2 = u32(emu:read32(ADDR_SAVEBLOCK2_PTR))
  return u32(emu:read32(sb2 + SB2_ENCKEY)) % 65536
end

-- ---------------- context reads ---------------------------------------------
local function readSpeciesAt(base)
  local pid  = u32(emu:read32(base + OFF_PERSONALITY))
  local key  = bxor(pid, u32(emu:read32(base + OFF_OTID)))
  local word = u32(emu:read32(base + OFF_SECURE + GROWTH_POS[pid % 24] * SUBSTRUCT_SIZE))
  return bxor(word, key) % 65536
end

local function readParty()   -- -> {"Blaziken:45", ...}, highestLevel
  local out, highest = {}, 0
  if not (ADDR_PLAYER_PARTY and ADDR_PARTY_COUNT) then return out, highest end
  local count = emu:read8(ADDR_PARTY_COUNT)
  if count > 6 then count = 6 end
  for i = 0, count - 1 do
    local base = ADDR_PLAYER_PARTY + i * MON_SIZE
    local lvl = emu:read8(base + OFF_LEVEL)
    if lvl > highest then highest = lvl end
    local sp = readSpeciesAt(base)
    out[#out + 1] = (SPECIES[sp] or ("#" .. sp)) .. ":" .. lvl
  end
  return out, highest
end

local function readBag()     -- -> {"139:2", "13:1", ...} (decrypted quantities)
  local base, key = sb1(), encKeyLo16()
  local out = {}
  if not (base and key) then return out end
  for _, p in pairs(POCKETS) do
    for i = 0, p[2] - 1 do
      local slot = base + p[1] + i * 4
      local id = emu:read16(slot)
      if id ~= 0 then
        out[#out + 1] = id .. ":" .. bxor(emu:read16(slot + 2), key) % 65536
      end
    end
  end
  return out
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

-- ---------------- dialogue injection (verified re-render trick) ------------
local MAX_DIALOGUE_BYTES = 250   -- gStringVar4 is 1000 bytes; never overflow it

local function encodeEmerald(text)
  local bytes = {}
  for i = 1, #text do
    if #bytes >= MAX_DIALOGUE_BYTES then break end
    bytes[#bytes + 1] = CHARMAP[text:sub(i, i)] or CHARMAP[" "] or 0x00
  end
  bytes[#bytes + 1] = STRING_TERMINATOR
  return bytes
end

local function restartPrinter()
  if not (ADDR_TEXTPRINTER0 and ADDR_STRINGVAR4) then return end
  emu:write32(ADDR_TEXTPRINTER0 + TP_CURRENTCHAR, ADDR_STRINGVAR4)
  emu:write8 (ADDR_TEXTPRINTER0 + TP_ACTIVE, 1)
  emu:write8 (ADDR_TEXTPRINTER0 + TP_STATE, 0)
end

local function writeToBuffer(text)
  if not ADDR_STRINGVAR4 then
    console:log("[hook] (no gStringVar4 address set) would show: " .. text)
    return
  end
  for i, b in ipairs(encodeEmerald(text)) do
    emu:write8(ADDR_STRINGVAR4 + (i - 1), b)
  end
  restartPrinter()
end

-- ---------------- quest actuators -------------------------------------------
-- give/take items: quantities stored ENCRYPTED (qty ^ encryptionKey lo16).
-- delta > 0 adds (uses first empty slot if the item isn't in the bag);
-- delta < 0 removes (clamps at 0 and clears the slot id).
local function adjustItem(itemId, delta, pocketName)
  local base, key = sb1(), encKeyLo16()
  if not (base and key) then
    console:warn("[hook] item write skipped: save-block addresses not set")
    return false
  end
  local pockets
  if pocketName and POCKETS[pocketName] then
    pockets = {POCKETS[pocketName]}
    if pocketName == "key" and delta > 1 then delta = 1 end  -- key items never stack
  else
    pockets = {POCKETS.items, POCKETS.berries}   -- default scan (regular goods)
  end
  local empty = nil
  for _, p in ipairs(pockets) do
    for i = 0, p[2] - 1 do
      local slot = base + p[1] + i * 4
      local id = emu:read16(slot)
      if id == itemId then
        local qty = bxor(emu:read16(slot + 2), key) % 65536
        local newQty = qty + delta
        if newQty < 0 then newQty = 0 end
        if newQty > 99 then newQty = 99 end
        emu:write16(slot + 2, bxor(newQty, key) % 65536)
        if newQty == 0 then emu:write16(slot, 0) end
        return true
      elseif id == 0 and not empty then
        empty = slot
      end
    end
  end
  if delta > 0 and empty then
    emu:write16(empty, itemId)
    emu:write16(empty + 2, bxor(math.min(delta, 99), key) % 65536)
    return true
  end
  return false
end

local function setFlag(id)     -- mirrors FlagSet: flags[id/8] |= 1<<(id%8)
  local base = sb1()
  if not base then return false end
  local addr = base + SB1_FLAGS + math.floor(id / 8)
  local bit = id % 8
  local v = emu:read8(addr)
  if getbit(v, bit) == 0 then emu:write8(addr, v + 2^bit) end
  return true
end

local function getFlag(id)
  local base = sb1()
  if not base then return false end
  return getbit(emu:read8(base + SB1_FLAGS + math.floor(id / 8)), id % 8) == 1
end

-- Story progression (verified: SYSTEM_FLAGS = 0x860; badges = +0x7..+0xE)
local FLAG_BADGE1, FLAG_GAME_CLEAR = 0x867, 0x864
local function readBadges()
  local n = 0
  for i = 0, 7 do
    if getFlag(FLAG_BADGE1 + i) then n = n + 1 end
  end
  return n
end

-- ---------------- reply parsing: "act;act|dialogue" or bare dialogue -------
local function runAction(tok)
  local parts = {}
  for w in tok:gmatch("[^:]+") do parts[#parts + 1] = w end
  local kind, a, b = parts[1], tonumber(parts[2]), tonumber(parts[3])
  local pocket = parts[4]
  if kind == "give_item" and a and b then
    if adjustItem(a, b, pocket) then console:log("[hook] gave item " .. a .. " x" .. b) end
  elseif kind == "take_item" and a and b then
    if adjustItem(a, -b, pocket) then console:log("[hook] took item " .. a .. " x" .. b) end
  elseif kind == "set_flag" and a then
    if setFlag(a) then console:log("[hook] set flag " .. a) end
  else
    console:warn("[hook] unknown action ignored: " .. tostring(tok))
  end
end

local function handleReply(line)
  local bar = line:find("|", 1, true)
  local dialogue = line
  if bar then
    local acts = line:sub(1, bar - 1)
    dialogue = line:sub(bar + 1)
    for tok in acts:gmatch("[^;]+") do runAction(tok) end
  end
  writeToBuffer(dialogue)
end

-- ---------------- socket (verified wrapper API) ------------------------------
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
      console:log("[hook] reply: " .. line)
      handleReply(line)
      awaitingReply = false
    end
  end
end

local function connect()
  sock = socket.connect(HOST, PORT)
  if not sock then console:error("[hook] no bridge at "..HOST..":"..PORT); return false end
  sock:add("received", onReceived)
  sock:add("error", function() console:error("[hook] socket error") end)
  console:log("[hook] connected to bridge")
  return true
end

-- ---------------- per-frame trigger -----------------------------------------
local lastMode = 0
local waitFrames = 0
local WAIT_TIMEOUT = 600   -- ~10s @60fps: recover instead of hanging forever

local function onFrame()
  if not sock then return end
  if awaitingReply then
    waitFrames = waitFrames + 1
    if waitFrames >= WAIT_TIMEOUT then
      console:warn("[hook] no reply in time -- is the bridge running? Recovering.")
      writeToBuffer("...")
      awaitingReply = false
    end
    return
  end
  if not ADDR_FIELD_MSG_MODE then return end
  local mode = emu:read8(ADDR_FIELD_MSG_MODE)
  local opened = (lastMode == FIELD_MSG_HIDDEN and mode ~= FIELD_MSG_HIDDEN)
  lastMode = mode
  if not opened then return end

  local party, highest = readParty()
  local base = sb1()
  local ctx = {
    npc_id       = ADDR_LAST_TALKED and emu:read16(ADDR_LAST_TALKED) or -1,
    map_group    = base and emu:read8(base + SB1_MAPGROUP) or -1,
    map_num      = base and emu:read8(base + SB1_MAPNUM) or -1,
    original_line = ADDR_STRINGVAR4 and decodeGameString(ADDR_STRINGVAR4) or "",
    player_level = highest,
    party        = party,
    bag          = readBag(),
    badges       = readBadges(),
    game_clear   = getFlag(FLAG_GAME_CLEAR) and 1 or 0,
    unlocks      = (function()                  -- bit i set = island i reachable
                      local m = 0
                      for i, f in ipairs(UNLOCK_FLAGS) do
                        if getFlag(f) then m = m + 2^(i-1) end
                      end
                      return m
                    end)(),
    -- Hold SELECT while talking to any NPC to ask the Professor for a tip
    -- instead of normal dialogue. (getKey verified in mGBA scripting API;
    -- GBA key index 2 = Select.)
    advice       = (emu.getKey and emu:getKey(2) == 1) and 1 or 0,
  }
  awaitingReply = true
  waitFrames = 0
  if ADDR_STRINGVAR4 then
    emu:write8(ADDR_STRINGVAR4, STRING_TERMINATOR)
    restartPrinter()
  end
  sock:send(jsonEncode(ctx) .. "\n")
  console:log("[hook] sent context (npc " .. tostring(ctx.npc_id) .. ")")
end

-- ---------------- boot -------------------------------------------------------
if connect() then
  callbacks:add("frame", onFrame)
  console:log("[hook] v3 running. Fill ADDR_* values to enable triggers.")
end
