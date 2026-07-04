# Verification Report — pokeemerald facts for the LLM dialogue bridge

Everything here was checked against the **actual pokeemerald source** (shallow-cloned
from `pret/pokeemerald`, `master`) and, where possible, proven with a compiler or a
test harness — not recalled from memory. Use this as your reference when you fill in
addresses at your PC.

---

## TL;DR status

| Thing | Verified? | How |
|-------|-----------|-----|
| Party slot size = 100 bytes | ✅ | compiled `sizeof(struct Pokemon)` |
| **Level at offset 84, unencrypted** | ✅ | compiled `offsetof` |
| Species decryption (key = PID ^ OTID) | ✅ | source + 12,000-case test harness |
| Growth-substruct slot table (`GROWTH_POS`) | ✅ | source `GetSubstruct()` + test |
| Species-ID → name (Hoenn internal order) | ✅ | generated from game's own tables |
| Charmap (char → byte, terminator 0xFF) | ✅ | parsed `charmap.txt` + encoder test |
| **Trigger signal = `sFieldMessageBoxMode`** | ✅ | read `field_message_box.c` |
| **Injection target = `gStringVar4`** | ✅ | source shows messages render from it |
| Text-printer re-render offsets | ✅ | `struct TextPrinter` in `text.h` |
| Save blocks are DMA-relocated (not static) | ✅ | source `SetSaveBlocksPointers()` |
| Numeric addresses (`ADDR_*`) | ⬜ | **you** grep your `pokeemerald.map` |

---

## 1. Reading the party (Phase 2 — mostly done in the hook)

`gPlayerParty` is a static EWRAM array of 6 × `struct Pokemon` (100 bytes each).
`gPlayerPartyCount` (u8) says how many slots are filled. Both are plain globals at
fixed addresses.

**Level is trivial.** The `level` field lives in the *unencrypted* part of the struct
at **offset 84**. No decryption needed:
```
highest = max over i<count of  read8(gPlayerParty + i*100 + 84)
```
Proven by compiling the real struct: `sizeof=100`, `offsetof(level)=84`,
encrypted region (`secure`) starts at offset 32.

**Species needs decryption** (it's inside the encrypted Growth substruct):
1. `pid  = read32(base + 0)`, `otId = read32(base + 4)`
2. `key  = pid XOR otId`   ← verified: `DecryptBoxMon` XORs each word by otId then personality
3. `gslot = GROWTH_POS[pid % 24]`   ← the Growth substruct's physical slot
4. `word = read32(base + 32 + gslot*12)`
5. `species = (word XOR key) & 0xFFFF`

`GROWTH_POS` (personality%24 → slot), transcribed from `GetSubstruct()` and test-verified:
```
{0,0,0,0,0,0, 1,1,2,3,2,3, 1,1,2,3,2,3, 1,1,2,3,2,3}
```
This decoder was tested against 12,000 synthetic Pokémon spanning all 24 orderings
with random keys — **0 failures**.

⚠️ **Species value is the internal Hoenn index, not National Dex.** e.g.
`SPECIES_TREECKO = 277`, `SPECIES_BLAZIKEN = 282`, `SPECIES_RAYQUAZA = 406`. That's why
`species_names.lua` was generated from the game's own `gSpeciesNames` table (indexed by
that same internal value) — a National Dex name list would mislabel every Gen-3 mon.

---

## 2. The dialogue trigger (Phase 3 — the risky unknown, now solved)

From `src/field_message_box.c`:
- A static `sFieldMessageBoxMode` (u8) is `FIELD_MESSAGE_BOX_HIDDEN` (0) when idle.
- Every "show message" path (`ShowFieldMessage`, etc.) sets it to a non-zero mode.

So **watch that byte; a `0 → non-zero` transition means a dialogue box just opened.**
That's the hook's trigger. (It's a `static`, so in your `.map` it may be listed with
file scope — grep for `sFieldMessageBoxMode`.)

---

## 3. Injecting text (Phase 3 — the hard part, now scoped)

Also from `field_message_box.c`: every message is expanded into **`gStringVar4`** before
printing (`StringExpandPlaceholders(gStringVar4, str)`), and `ShowFieldMessageFromBuffer`
literally "prints what's already in gStringVar4." **So `gStringVar4` is the buffer to
overwrite.**

The catch: once the text printer has started, rewriting the buffer alone won't redraw the
screen, and mGBA Lua **cannot call ROM functions** to restart it. The memory-only fix uses
`struct TextPrinter` (from `include/text.h`) — its first field is `const u8 *currentChar`
(offset 0x00), with `active` at 0x1B and `state` at 0x1C. So the hook:
1. writes the new bytes into `gStringVar4`,
2. sets `sTextPrinters[0].currentChar` back to `gStringVar4`,
3. sets `active = 1`, `state = 0`.

That forces a clean re-render from the top of our text. Field messages use window 0, so
element `[0]` is the relevant printer.

---

## 4. Optional: current map name

`struct SaveBlock1` begins with `pos` (Coords16, offset 0x00), then the `location`
(`struct WarpData`) — so **mapGroup is at SaveBlock1 + 0x04, mapNum at + 0x05** (confirm
the field order in your `include/global.h`). But SaveBlock1 is **DMA-relocated**, so you
must read the pointer first:
```
sav1 = read32(gSaveBlock1Ptr)          -- the pointer is static; the data moves
mapGroup = read8(sav1 + 0x04)
mapNum   = read8(sav1 + 0x05)
```
Map (group, num) → human name needs the map-name table (a later nicety; not required).

---

## 5. Symbols to grep in YOUR `pokeemerald.map`

After building, run e.g. `grep gPlayerParty pokeemerald.map`. Symbols needed:

| Symbol | Used for |
|--------|----------|
| `gPlayerParty` | party level + species |
| `gPlayerPartyCount` | how many slots to read |
| `gStringVar4` | dialogue buffer (read original / write reply) |
| `sFieldMessageBoxMode` | the trigger signal |
| `sTextPrinters` | re-render trick (element [0]) |
| `gSaveBlock1Ptr` | (optional) map name |

For **vanilla US Emerald** these are also published on datacrystal, but your own build's
`.map` is the ground truth — and mandatory if you've modified the decomp at all, since the
linker re-places symbols.

---

## 6. The save-block caveat (why "everything is static" isn't quite true)

`load_save.c` stores the save data in structs literally named `SaveBlock1ASLR` /
`SaveBlock2ASLR`. `SetSaveBlocksPointers()` sets the pointer to `base + (offset + Random())
& mask`, and `MoveSaveBlocks_ResetHeap()` re-randomizes it during play. So plain globals
(`gPlayerParty`, `gStringVar4`) are at fixed addresses, but anything inside the save blocks
(map, badges, flags, money, name) must be reached through `gSaveBlock1Ptr`. This is the
well-known reason Emerald Action Replay codes were flaky.

---

## 7. mGBA API surface — verified against mGBA's own source

Every mGBA scripting call the hook/reader make was checked against the real
mGBA source (mgba-emu/mgba), not memory:

- **Memory:** `emu:read8/read16/read32/write8/write32` — declared in
  `src/core/scripting.c`. `read32` returns **U32 (unsigned)**, so personality/OTID
  come back unsigned already. (The u32() masks in the decode are therefore
  defensive-only, not load-bearing — kept for safety, but read32 is unsigned.)
- **Callbacks:** `callbacks:add("frame", fn)` — `src/script/stdlib.c` (also `oneshot`, `remove`).
- **Console:** `console:log/warn/error` and `console:createBuffer(name)` — `src/script/console.c`.
  Text buffer methods `print`, `clear` (also `moveCursor`, `advance`, `setSize`) — same file.
- **Sockets:** the friendly `socket` global is a Lua wrapper (`_socketLuaSource` in
  `src/script/engines/lua.c`) over the low-level `_socket` C binding. Confirmed the
  wrapper exposes `socket.connect`, and on the returned socket: `add(event, cb)`,
  `receive(maxBytes)`, `send(data)`, `poll`, `hasdata`, `close`. Crucially, a
  successful `connect`/`listen`/`accept` auto-registers a per-frame `poll` that
  dispatches the `received` event — which is exactly what drives our onReceived
  callback. `receive` returns `nil, err` on disconnect (our loop handles that).

Conclusion: the script uses only real, correctly-named API. Nothing here should
fail at load or call time due to a wrong method name.
