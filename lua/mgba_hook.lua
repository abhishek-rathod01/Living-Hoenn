-- ============================================================================
-- mgba_hook.lua  (v4 -- reload-safe, stale-reply-guarded, wrap-aware)
--
-- Works with bridge_server.py (dialogue only) OR quest_bridge_server.py
-- (dialogue + quests). Replies may be action-prefixed:
--     "take_item:139:2;give_item:13:1|My berries! Take this."
-- Actions execute against verified memory layouts; unknown actions are ignored.
--
-- All offsets/mechanisms verified against pokeemerald + mGBA source
-- (docs/VERIFICATION_REPORT.md). Fill in the ADDR_* values from YOUR
-- pokeemerald.map. Portable Lua (5.1/5.2/5.3/5.4/LuaJIT): no native bit-ops.
--
-- CHANGES FROM v3, each tagged with how it was verified:
--   [VERIFIED x2 -- mgba-emu/mgba source: ScriptingView::load() calls
--    ScriptingController::loadFile()/load() directly; load() re-runs the
--    script on the SAME Lua engine without deiniting it (reset() is a
--    separate, not-automatically-called function). So re-loading this file
--    after an edit -- without clicking Tools>Scripting>Reset or restarting
--    mGBA -- used to leave a PREVIOUS instance's frame callback registered
--    alongside the new one: two live hook instances racing on the same
--    trigger byte. Root cause of double-send / garbled text / blank boxes.]
--   -> reload guard: detects and tears down a prior instance (removes its
--      frame callback via the id callbacks:add returns, closes its socket)
--      before registering new ones. Belt-and-suspenders: you should still
--      restart mGBA or hit Reset before reloading -- this is a safety net.
--
--   [VERIFIED x2 -- pokeemerald src/string_util.c: EXT_CTRL_CODE_BEGIN
--    (0xFC) is followed by a sub-code byte, then 0/1/2/3 argument bytes
--    depending on the sub-code (exact table below, read from the real
--    parser's fallthrough switch) -- these survive untouched in gStringVar4
--    (placeholders like {PLAYER} do NOT: StringExpandPlaceholders already
--    replaced them with real name bytes before gStringVar4 is populated,
--    confirmed in the same file). Decoding gStringVar4 one byte at a time
--    without skipping these control sequences turned their argument bytes
--    into garbage single-character lookups.]
--   -> decodeGameString now skips control codes by their exact verified
--      length instead of translating their bytes as if they were text.
--
--   [VERIFIED -- charmap.lua itself, checked directly: 61 of 251 mapped
--    bytes have TWO different characters assigned (mostly Latin-accented
--    vs Japanese kana, since the shared GBA charmap data covers both
--    regional charsets but only one is active per ROM). Building the
--    reverse map with plain pairs() iteration is non-deterministic on
--    these collisions -- a US ROM should always resolve to the Latin
--    character, never kana, since kana can't appear in vanilla US text.]
--   -> REVCHARMAP construction now deterministically prefers non-kana.
--
--   [VERIFIED -- measured 496 real dialogue lines from 5 vanilla map
--    scripts (Oldale/Littleroot/Petalburg/Rustboro/Slateport) against
--    the actual pokeemerald source: max on-screen line = 40 characters.]
--   -> encodeEmerald now greedily word-wraps LLM replies at 40 display
--      characters per line (first break = 0xFE, subsequent = 0xFA, same
--      convention vanilla scripts use), instead of only breaking on
--      literal "\n" the model happened to emit. Long unbroken replies no
--      longer overflow the window.
--   -> encodeEmerald is now UTF-8-aware: it reads whole codepoints (using
--      the UTF-8 leading-byte length, which is unambiguous -- not a
--      trial-and-error longest-match) instead of raw bytes, so multi-byte
--      charmap entries ("...", curly quotes, (male)/(female) symbols, yen)
--      match correctly instead of being shredded into single fallback
--      spaces. Em/en dashes (not in the charmap) are pre-normalized to
--      a plain hyphen, which IS mapped.
--
--   [DESIGN CHANGE, not a "verified fact" -- a queueing decision]
--   -> awaitingReply (single boolean) replaced with a small FIFO of
--      pending requests. TCP delivers bytes in order, so replies arrive
--      in the same order requests were sent; when the dialogue box closes
--      before a reply comes back, every still-pending request for that
--      conversation is marked stale and its eventual reply is discarded
--      instead of being injected into whatever box happens to be open
--      later. This is the fix for "stale reply lands in the wrong box."
--
--   [BEHAVIOR TOGGLE, default chosen deliberately -- see note at
--    INTERCEPT_SIGNS below]
--   -> optional gate to stop intercepting npc_id==0 (signs) entirely.
-- ============================================================================

local HOST = "127.0.0.1"
local PORT = 8888

-- ---------------- ADDRESSES: grep your pokeemerald.map ----------------------
local ADDR_PLAYER_PARTY   = 0x020244ec  -- gPlayerParty
local ADDR_PARTY_COUNT    = 0x020244e9  -- gPlayerPartyCount
local ADDR_STRINGVAR4     = 0x02021fc4  -- gStringVar4
local ADDR_FIELD_MSG_MODE = 0x020375bc  -- sFieldMessageBoxMode (static) -- absent from
                                  -- pokeemerald.map (ld -Map omits local statics); verified
                                  -- via `arm-none-eabi-nm pokeemerald.elf` and cross-checked
                                  -- against field_message_box.o's local offset (0x0) added to
                                  -- its ewram_data section base (0x020375bc) from the map.
local ADDR_TEXTPRINTER0   = 0x020201b0  -- sTextPrinters (static; element [0]; stride 0x24)
                                  -- -- same method: nm on pokeemerald.elf, cross-checked via
                                  -- text.o's local offset (0x24) + its ewram_data section
                                  -- base (0x0202018c) from the map.
local ADDR_LAST_TALKED    = 0x020375f2  -- gSpecialVar_LastTalked (u16; NPC local id)
local ADDR_SAVEBLOCK1_PTR = 0x03005d8c  -- gSaveBlock1Ptr (pointer; data is DMA-relocated)
local ADDR_SAVEBLOCK2_PTR = 0x03005d90  -- gSaveBlock2Ptr (pointer; holds encryptionKey)

-- ---------------- BEHAVIOR TOGGLES -------------------------------------------
-- INTERCEPT_SIGNS: signs and TVs both report npc_id == 0 (gSpecialVar_LastTalked
-- resets to 0 for anything that isn't a person -- verified in ARCHITECTURE.md
-- section I.8 / field_control_avatar.c). Setting this to false stops the hook
-- from touching ANY npc_id==0 box, so plain signs show vanilla text untouched --
-- but it ALSO disables the built-and-tested TV news/quiz/advisor features
-- (broadcast.py), since those ride on the same npc_id==0 signal and there's no
-- current way in Lua to tell "sign" and "TV" apart before the bridge decides.
-- Default is TRUE here (preserves your existing tested behavior). Flip to
-- false only if you've decided the sign annoyance matters more than TV/quiz
-- right now -- that trade-off is yours to make, not mine to make for you.
local INTERCEPT_SIGNS = true

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

-- Verified (src/string_util.c, StringExpandPlaceholders): EXT_CTRL_CODE_BEGIN
-- (0xFC) sub-codes and how many EXTRA argument bytes follow the sub-code byte.
-- Anything not listed falls to the "default" case = 1 extra byte.
local EXT_CTRL_EXTRA_ARGS = {
  [0x07] = 0,  -- RESET_FONT
  [0x09] = 0,  -- PAUSE_UNTIL_PRESS
  [0x0F] = 0,  -- FILL_WINDOW
  [0x15] = 0,  -- JPN
  [0x16] = 0,  -- ENG
  [0x17] = 0,  -- PAUSE_MUSIC
  [0x18] = 0,  -- RESUME_MUSIC
  [0x04] = 3,  -- COLOR_HIGHLIGHT_SHADOW (fallthrough consumes 3 bytes)
  [0x0B] = 2,  -- PLAY_BGM (fallthrough consumes 2 bytes)
}
local EXT_CTRL_DEFAULT_EXTRA_ARGS = 1

-- Verified (include/constants/characters.h / string_util.c dispatch table).
-- These placeholders are normally already expanded by the game before
-- gStringVar4 is populated, so this table is a defensive fallback only --
-- it should rarely if ever actually fire.
local PLACEHOLDER_NAMES = {
  [0x1] = "{PLAYER}", [0x2] = "{VAR1}", [0x3] = "{VAR2}", [0x4] = "{VAR3}",
  [0x6] = "{RIVAL}",
}

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
-- Tries the absolute repo path first (works from any mGBA working directory),
-- falls back to a relative path (works if the .lua files sit next to the
-- hook, e.g. when testing outside the full repo layout).
local function loadTable(absPath, relPath, label)
  local ok, t = pcall(dofile, absPath)
  if ok and type(t) == "table" then return t end
  ok, t = pcall(dofile, relPath)
  if ok and type(t) == "table" then return t end
  console:warn("[hook] couldn't load " .. label .. " from either path -- paste inline")
  return {}
end

local SPECIES = loadTable(
  "C:/Users/abhis/Desktop/Living hoenn/living-hoenn-COMPLETE-backup/living-hoenn-COMPLETE-backup/gitrepo/lua/species_names.lua",
  "species_names.lua", "species_names.lua")
local CHARMAP = loadTable(
  "C:/Users/abhis/Desktop/Living hoenn/living-hoenn-COMPLETE-backup/living-hoenn-COMPLETE-backup/gitrepo/lua/charmap.lua",
  "charmap.lua", "charmap.lua")

-- Deterministic reverse map: on a byte collision, the SHORTER UTF-8 encoding
-- always wins, regardless of pairs() iteration order. Verified against every
-- real collision in charmap.lua (61 total): every Latin/ASCII entry is 1-2
-- UTF-8 bytes, every Japanese-variant entry (kana, fullwidth punctuation,
-- ideographic space) is 3 bytes -- shorter-wins resolves 60/61 correctly.
-- The remaining 1 is a genuine tie (both 3 bytes: "..." U+2026 vs a lookalike
-- U+22EF, harmless synonyms) broken explicitly below.
local REVCHARMAP = {}
for ch, b in pairs(CHARMAP) do
  local existing = REVCHARMAP[b]
  if existing == nil or #ch < #existing then
    REVCHARMAP[b] = ch
  end
end
-- explicit tie-break for the one equal-length collision (both render as an
-- ellipsis; prefer the standard horizontal ellipsis U+2026 for consistency)
for b, ch in pairs(CHARMAP) do
  if ch == "\xE2\x80\xA6" then REVCHARMAP[b] = ch end -- U+2026 "..."
end

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

-- Reads gStringVar4 back into a plain-text string for the LLM prompt.
-- Skips control-code sequences by their exact verified length instead of
-- feeding their raw bytes through the charmap (which used to produce
-- garbage characters wherever a message used color/highlight/pause codes).
local function decodeGameString(addr, maxLen)
  local out = {}
  local i, limit = 0, (maxLen or 200)
  while i < limit do
    local b = emu:read8(addr + i)
    if b == STRING_TERMINATOR then break end
    if b == 0xFE or b == 0xFA or b == 0xFB then
      out[#out + 1] = "\n"
      i = i + 1
    elseif b == 0xFC then
      local sub = emu:read8(addr + i + 1)
      local extra = EXT_CTRL_EXTRA_ARGS[sub]
      if extra == nil then extra = EXT_CTRL_DEFAULT_EXTRA_ARGS end
      i = i + 2 + extra   -- 0xFC + subcode + its extra args, skip all of it
    elseif b == 0xFD then
      -- defensive only -- see PLACEHOLDER_NAMES comment above; shouldn't
      -- normally fire since the game expands these before we ever read them
      local id = emu:read8(addr + i + 1)
      out[#out + 1] = PLACEHOLDER_NAMES[id] or "{?}"
      i = i + 2
    else
      out[#out + 1] = REVCHARMAP[b] or " "
      i = i + 1
    end
  end
  return table.concat(out)
end

-- ---------------- dialogue injection (verified re-render trick) ------------
local MAX_DIALOGUE_BYTES = 250   -- gStringVar4 is 1000 bytes; never overflow it
local WRAP_WIDTH = 40           -- verified: max real on-screen line = 40 chars
                                 -- (measured against 496 lines from 5 vanilla
                                 -- map scripts: Oldale/Littleroot/Petalburg/
                                 -- Rustboro/Slateport)

-- UTF-8 leading-byte -> total sequence length. Unambiguous per the UTF-8
-- spec (unlike trial-and-error longest-match): the high bits of the first
-- byte alone determine how many bytes follow.
local function utf8Len(b)
  if b < 0x80 then return 1
  elseif b >= 0xF0 then return 4
  elseif b >= 0xE0 then return 3
  elseif b >= 0xC0 then return 2
  else return 1 end -- stray continuation byte; treat defensively as len 1
end

-- Splits a string into a list of whole UTF-8 glyphs (each glyph 1-4 raw
-- bytes). Fixes the old per-raw-byte loop, which shredded every multi-byte
-- charmap entry ("...", curly quotes, (male)/(female), yen) into fallback
-- spaces because it only ever looked up single bytes.
local function utf8Glyphs(text)
  local glyphs = {}
  local i, n = 1, #text
  while i <= n do
    local len = utf8Len(text:byte(i))
    if i + len - 1 > n then len = 1 end
    glyphs[#glyphs + 1] = text:sub(i, i + len - 1)
    i = i + len
  end
  return glyphs
end

-- Pre-normalize characters the LLM commonly emits that aren't in the
-- charmap, to characters that are. Em dash (U+2014, E2 80 94) and en dash
-- (U+2013, E2 80 93) -> plain hyphen (charmap: 0xAE). Non-breaking space
-- (U+00A0, C2 A0) -> plain space.
local function normalizeText(text)
  text = text:gsub("\xE2\x80\x94", "-"):gsub("\xE2\x80\x93", "-")
  text = text:gsub("\xC2\xA0", " ")
  text = text:gsub("\r\n", "\n"):gsub("\\n", "\n")
  return text
end

-- Greedy word-wrap over whole glyphs (not bytes), so multi-byte characters
-- count as one column like they render as one glyph on screen. Explicit
-- "\n" in the text forces a break; otherwise breaks are inserted once a
-- word would push the line past WRAP_WIDTH. First break emitted overall is
-- 0xFE (CHAR_NEWLINE, no wait), every subsequent one is 0xFA (CHAR_PROMPT_
-- SCROLL, wait+scroll) -- the same convention vanilla scripts use (verified:
-- data/maps/*/scripts.inc consistently uses \n first, \l after).
local function encodeEmerald(text)
  text = normalizeText(text)
  local bytes = {0xFC, 0x0F}  -- FILL_WINDOW: printer clears box before drawing
  local brokeOnce = false
  local col = 0

  local function emitBreak()
    bytes[#bytes + 1] = brokeOnce and 0xFA or 0xFE
    brokeOnce = true
    col = 0
  end

  -- split into words, keeping explicit newlines as separate break tokens
  for line in (text .. "\n"):gmatch("(.-)\n") do
    if col > 0 then emitBreak() end -- explicit author newline
    local first = true
    for word in line:gmatch("%S+") do
      local glyphs = utf8Glyphs(word)
      local wlen = #glyphs
      if not first and col + 1 + wlen > WRAP_WIDTH then
        emitBreak()
      elseif not first then
        if #bytes >= MAX_DIALOGUE_BYTES then break end
        bytes[#bytes + 1] = CHARMAP[" "] or 0x00
        col = col + 1
      end
      for _, g in ipairs(glyphs) do
        if #bytes >= MAX_DIALOGUE_BYTES then break end
        if g == "$" then
          bytes[#bytes + 1] = 0xB7
        else
          bytes[#bytes + 1] = CHARMAP[g] or CHARMAP[" "] or 0x00
        end
        col = col + 1
      end
      first = false
      if #bytes >= MAX_DIALOGUE_BYTES then break end
    end
    if #bytes >= MAX_DIALOGUE_BYTES then break end
  end

  -- VERIFIED (pokeemerald src/text.c RenderText): "case EOS: return RENDER_FINISH;"
  -- -- a bare EOS finishes the printer IMMEDIATELY, no player input required.
  -- Only CHAR_PROMPT_CLEAR (0xFB) / CHAR_PROMPT_SCROLL (0xFA) route into
  -- TextPrinterWaitWithDownArrow(), which is what actually blocks for an
  -- A-press. Without this, the printer went inactive within a couple frames
  -- of any short reply finishing, sFieldMessageBoxMode flipped back to
  -- HIDDEN (per field_message_box.c's Task_DrawFieldMessage), and the
  -- stale-reply guard marked the request stale almost immediately --
  -- regardless of how long the player actually waited. This is the real fix.
  bytes[#bytes + 1] = 0xFB
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

-- >0: player choice pending (A/B). DECLARED BEFORE runAction on purpose:
-- Lua closures capture locals only if declared first; putting this after
-- runAction made runAction write a GLOBAL while onFrame read this local --
-- a real bug our test suite caught before it ever reached hardware.
local choiceFrames = 0

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
  elseif kind == "await_choice" and a then
    if emu.getKey then
      choiceFrames = a
      console:log("[hook] awaiting A/B choice (" .. a .. " frames)")
    else
      console:warn("[hook] await_choice ignored: getKey unavailable in this mGBA")
    end
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

-- ---------------- stale-reply guard (FIFO) -----------------------------------
-- DESIGN CHOICE (not a "verified fact" -- a queueing decision): TCP delivers
-- bytes in order, so replies come back in the same order requests were sent.
-- Each entry: {stale=bool, warned=bool, age=frames-since-sent}. When the
-- dialogue box closes, every still-pending entry is marked stale immediately
-- (its box is gone). When a reply arrives, we pop the front entry; if it's
-- stale we discard the reply instead of injecting it into whatever box
-- happens to be open now -- this is the fix for "stale reply lands in the
-- wrong box."
local pending = {}
local MAX_PENDING = 8

local function pushPending()
  pending[#pending + 1] = {stale = false, warned = false, age = 0}
  while #pending > MAX_PENDING do
    console:warn("[hook] dropping oldest pending request -- bridge unresponsive")
    table.remove(pending, 1)
  end
end

local function markAllStale()
  for _, p in ipairs(pending) do p.stale = true end
end

-- ---------------- socket (verified wrapper API) ------------------------------
local sock, rxBuffer = nil, ""

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
      local entry = table.remove(pending, 1)
      if entry and entry.stale then
        console:log("[hook] discarded stale reply (its box already closed): " .. line)
      else
        console:log("[hook] reply: " .. line)
        handleReply(line)
      end
    end
  end
end

local function connect()
  sock = socket.connect(HOST, PORT)
  if not sock then console:error("[hook] no bridge at "..HOST..":"..PORT); return false end
  sock:add("received", onReceived)
  sock:add("error", function()
    console:error("[hook] socket error")
    pending = {}
  end)
  console:log("[hook] connected to bridge")
  return true
end

-- ---------------- per-frame trigger -----------------------------------------
local lastMode = 0
local WAIT_TIMEOUT = 600   -- ~10s @60fps: recover instead of hanging forever

local function sendChoice(n)
  local base = sb1()
  local ctx = {
    choice     = n,
    npc_id     = ADDR_LAST_TALKED and emu:read16(ADDR_LAST_TALKED) or -1,
    map_group  = base and emu:read8(base + SB1_MAPGROUP) or -1,
    map_num    = base and emu:read8(base + SB1_MAPNUM) or -1,
  }
  pushPending()
  sock:send(jsonEncode(ctx) .. "\n")
  console:log("[hook] sent choice " .. n)
end

local function sendContext(npcId)
  local party, highest = readParty()
  local base = sb1()
  local ctx = {
    npc_id       = npcId,
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
  pushPending()
  if ADDR_STRINGVAR4 then
    writeToBuffer("...")   -- visible "thinking" placeholder, not a blank box --
                           -- an empty-looking box during the 4-6s LLM wait was
                           -- getting mistaken for a hang, causing early A-
                           -- presses that then correctly (but confusingly)
                           -- got their late reply discarded as stale.
  end
  sock:send(jsonEncode(ctx) .. "\n")
  console:log("[hook] sent context (npc " .. tostring(npcId) .. ")")
end

local function onFrame()
  if not sock then return end
  if choiceFrames > 0 then
    choiceFrames = choiceFrames - 1
    if emu:getKey(0) == 1 then choiceFrames = 0; sendChoice(1)   -- A
    elseif emu:getKey(1) == 1 then choiceFrames = 0; sendChoice(2) -- B
    elseif choiceFrames == 0 then sendChoice(0) end               -- timed out
    return
  end

  -- Mode/edge detection now runs every frame unconditionally (previously it
  -- was skipped entirely while a reply was pending, which froze lastMode and
  -- masked box-close events that happened during the wait).
  if ADDR_FIELD_MSG_MODE then
    local mode = emu:read8(ADDR_FIELD_MSG_MODE)
    local opened = (lastMode == FIELD_MSG_HIDDEN and mode ~= FIELD_MSG_HIDDEN)
    local closed = (lastMode ~= FIELD_MSG_HIDDEN and mode == FIELD_MSG_HIDDEN)
    lastMode = mode

    if closed then
      markAllStale()
    end

    if opened then
      local npcId = ADDR_LAST_TALKED and emu:read16(ADDR_LAST_TALKED) or -1
      if npcId == 0 and not INTERCEPT_SIGNS then
        -- leave vanilla text alone entirely
      else
        sendContext(npcId)
      end
    end
  end

  -- Age pending requests; warn (and show "..." if their box is still open)
  -- exactly once per request, without removing it -- removing would desync
  -- the FIFO against a bridge that answers late.
  for _, p in ipairs(pending) do
    if not p.warned then
      p.age = p.age + 1
      if p.age >= WAIT_TIMEOUT then
        p.warned = true
        console:warn("[hook] no reply in time -- is the bridge running?")
        if not p.stale then writeToBuffer("...") end
      end
    end
  end
end

-- ---------------- reload guard -------------------------------------------------
-- VERIFIED (mgba-emu/mgba source, two independent code paths):
--   ScriptingView::load() -> ScriptingController::loadFile()/load() re-runs the
--   script on the SAME Lua engine; it never calls reset()/mScriptContextDeinit.
--   So re-loading this file after an edit, without clicking Tools > Scripting >
--   Reset (or restarting mGBA), leaves the PREVIOUS instance's callbacks:add
--   frame-hook still registered -- you get two live hook instances racing each
--   other on the same trigger byte. Lua globals (unlike locals) survive a
--   reload in the same engine, so we use one to detect and tear down any
--   prior instance first.
if _G.__livingHoenn then
  console:warn("[hook] previous instance detected -- tearing it down before restarting")
  if _G.__livingHoenn.frameCbId then
    local ok, err = pcall(function() callbacks:remove(_G.__livingHoenn.frameCbId) end)
    if not ok then console:warn("[hook] couldn't remove old frame callback: " .. tostring(err)) end
  end
  if _G.__livingHoenn.sock then
    pcall(function() _G.__livingHoenn.sock:close() end)
  end
end
_G.__livingHoenn = {}

-- ---------------- boot -------------------------------------------------------
if connect() then
  _G.__livingHoenn.sock = sock
  _G.__livingHoenn.frameCbId = callbacks:add("frame", onFrame)
  console:log("[hook] v4 running. Fill ADDR_* values to enable triggers.")
end