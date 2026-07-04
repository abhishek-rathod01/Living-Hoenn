-- ============================================================================
-- mgba_hook.lua  --  emulator side of the AI-powered Emerald bridge.
-- v1: initial skeleton, before source-level verification of offsets.
-- ============================================================================

local HOST = "127.0.0.1"
local PORT = 8888

local ADDR_PLAYER_PARTY   = nil
local ADDR_SAVEBLOCK1_PTR = nil
local ADDR_STRINGVAR4     = nil
local ADDR_TRIGGER_FLAG   = nil

local function jsonEscape(s)
  s = tostring(s)
  s = s:gsub("\\", "\\\\"):gsub('"', '\\"')
  s = s:gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t")
  return s
end

local function jsonEncode(tbl)
  local parts = {}
  for k, v in pairs(tbl) do
    local key = '"' .. jsonEscape(k) .. '":'
    local val
    if type(v) == "number" then
      val = tostring(v)
    elseif type(v) == "table" then
      local items = {}
      for _, item in ipairs(v) do
        items[#items + 1] = '"' .. jsonEscape(item) .. '"'
      end
      val = "[" .. table.concat(items, ",") .. "]"
    else
      val = '"' .. jsonEscape(v) .. '"'
    end
    parts[#parts + 1] = key .. val
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

local sock = nil
local rxBuffer = ""
local awaitingReply = false
local lastTriggerValue = nil
local injectDialogue

local function onReceived()
  while true do
    local data, err = sock:receive(4096)
    if data == nil or #data == 0 then break end
    rxBuffer = rxBuffer .. data
  end
  while true do
    local nl = rxBuffer:find("\n", 1, true)
    if not nl then break end
    local line = rxBuffer:sub(1, nl - 1)
    rxBuffer = rxBuffer:sub(nl + 1)
    if #line > 0 then
      injectDialogue(line)
      awaitingReply = false
    end
  end
end

local function connect()
  sock = socket.connect(HOST, PORT)
  if not sock then return false end
  sock:add("received", onReceived)
  sock:add("error", function() console:error("[hook] socket error") end)
  return true
end

local function readContext()
  if not ADDR_TRIGGER_FLAG then return nil end
  local now = emu:read8(ADDR_TRIGGER_FLAG)
  if now == lastTriggerValue then return nil end
  lastTriggerValue = now
  if now == 0 then return nil end
  return { npc_role = "an NPC", situation = "talking" }
end

injectDialogue = function(text)
  console:log("[hook] (stub) would show: " .. text)
end

local function onFrame()
  if not sock or awaitingReply then return end
  local ctx = readContext()
  if ctx then
    awaitingReply = true
    sock:send(jsonEncode(ctx) .. "\n")
  end
end

if connect() then
  callbacks:add("frame", onFrame)
end
