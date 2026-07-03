"""
extract_addresses.py  --  pull the symbols the hook needs out of your build.

After you build pokeemerald you'll have `pokeemerald.map` (and/or `pokeemerald.sym`).
Point this at it and it prints a ready-to-paste Lua ADDR_* block, so you don't have
to grep and copy addresses by hand.

USAGE
-----
  python extract_addresses.py /path/to/pokeemerald.map
  python extract_addresses.py /path/to/pokeemerald.sym

Works with GNU ld .map files and nm-style .sym files.
"""

import re
import sys

# symbol -> the Lua variable name in mgba_hook.lua
WANTED = {
    "gPlayerParty":            "ADDR_PLAYER_PARTY",
    "gPlayerPartyCount":       "ADDR_PARTY_COUNT",
    "gStringVar4":             "ADDR_STRINGVAR4",
    "sFieldMessageBoxMode":    "ADDR_FIELD_MSG_MODE",
    "sTextPrinters":           "ADDR_TEXTPRINTER0",   # NOT gTextPrinters -- verified static
    "gSpecialVar_LastTalked":  "ADDR_LAST_TALKED",
    "gSaveBlock1Ptr":          "ADDR_SAVEBLOCK1_PTR",
    "gSaveBlock2Ptr":          "ADDR_SAVEBLOCK2_PTR",
}

HEX = r"0x([0-9a-fA-F]+)"


def find_address(lines, symbol):
    """Return the address (int) for `symbol`, or None."""
    # Priority 1: a line that is just  <hex>   <symbol>   (GNU ld defined-symbol line)
    pat_alone = re.compile(r"^\s*" + HEX + r"\s+" + re.escape(symbol) + r"\s*$")
    # Priority 2: nm style  <hex> <type> <symbol>
    pat_nm = re.compile(r"^\s*([0-9a-fA-F]{6,8})\s+\w\s+" + re.escape(symbol) + r"\s*$")
    # Fallback: any line with the symbol as a whole word AND a hex address
    pat_any = re.compile(r"\b" + re.escape(symbol) + r"\b")

    for line in lines:
        m = pat_alone.match(line)
        if m:
            return int(m.group(1), 16)
    for line in lines:
        m = pat_nm.match(line)
        if m:
            return int(m.group(1), 16)
    for line in lines:
        if pat_any.search(line):
            m = re.search(HEX, line) or re.search(r"\b([0-9a-fA-F]{6,8})\b", line)
            if m:
                return int(m.group(1), 16)
    return None


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "r", errors="ignore") as f:
        lines = f.readlines()

    print(f"-- extracted from {path}")
    found, missing = {}, []
    for sym, var in WANTED.items():
        addr = find_address(lines, sym)
        if addr is None:
            missing.append(sym)
        else:
            found[var] = addr

    # Emit the Lua block in the hook's order
    order = ["ADDR_PLAYER_PARTY", "ADDR_PARTY_COUNT", "ADDR_STRINGVAR4",
             "ADDR_FIELD_MSG_MODE", "ADDR_TEXTPRINTER0", "ADDR_LAST_TALKED",
             "ADDR_SAVEBLOCK1_PTR", "ADDR_SAVEBLOCK2_PTR"]
    for var in order:
        if var in found:
            print(f"local {var:<22} = 0x{found[var]:08X}")
        else:
            print(f"local {var:<22} = nil  -- NOT FOUND in map")

    if missing:
        print("\n-- WARNING: these symbols weren't found: " + ", ".join(missing))
        print("-- (static symbols like sFieldMessageBoxMode may be absent from a stripped map;")
        print("--  build with the standard, non-stripped map or check pokeemerald.sym.)")


if __name__ == "__main__":
    main()
