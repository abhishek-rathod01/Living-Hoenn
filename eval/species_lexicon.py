"""eval/species_lexicon.py -- the species vocabulary the grounding metric uses.

GENERATED, NEVER HAND-WRITTEN (project hard rule: "Don't hand-edit generated
files ... regenerate from pokeemerald source").

This module does not carry a baked-in list. It parses `lua/species_names.lua`
at import time -- which is itself generated from pokeemerald's species.h +
species_names.h and carries the game's own internal Hoenn ordering. Parsing
the generated file rather than duplicating its contents means there is exactly
one place a species name can be wrong, and it is the one place already
verified against the decomp.

Regenerating: there is nothing to regenerate here. Regenerate
`lua/species_names.lua` from pokeemerald and this module follows automatically.

Why a lexicon at all: metric M1 (spec section 3) needs to know which words in a
generated line are Pokemon species names. Matching is case-insensitive on word
boundaries, per the spec.
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
SPECIES_LUA = os.path.join(_REPO, "lua", "species_names.lua")

# [123] = "Name"  -- the only line shape species_names.lua emits for an entry.
_ENTRY = re.compile(r'^\s*\[(\d+)\]\s*=\s*"([^"]+)"\s*,?\s*$')


def _parse(path=SPECIES_LUA):
    """{internal_index: "Name"} straight out of the generated Lua table.

    Raises rather than returning {} if the file is missing or yields nothing.
    An empty lexicon would silently turn every M1 measurement into "zero
    violations found", which is the exact silent-empty-table failure mode that
    produced the CHARMAP bug -- a metric that cannot fire is worse than no
    metric, because it reads as a passing score.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"species_lexicon needs the generated {path}. It is tracked in the "
            "repo; if it is missing, regenerate it from pokeemerald rather "
            "than hand-writing a species list.")
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = _ENTRY.match(line)
            if m:
                out[int(m.group(1))] = m.group(2)
    if not out:
        raise ValueError(
            f"{path} exists but no [index] = \"Name\" entries parsed out of it. "
            "Refusing to hand back an empty lexicon -- see this module's "
            "docstring.")
    return out


SPECIES_BY_INDEX = _parse()

#: Every species name, canonical casing, as it appears in the generated table.
SPECIES_NAMES = sorted(set(SPECIES_BY_INDEX.values()))

#: lowercase -> canonical, for case-insensitive lookup.
_CANON = {n.lower(): n for n in SPECIES_NAMES}


def _flatten(s):
    """Reduce a species spelling to a comparison key.

    The gender symbols must become letters BEFORE punctuation is stripped.
    Dropping them instead collapses Nidoran-female and Nidoran-male onto the
    same key -- verified: it did, and normalize() silently returned the male
    form for both. Mapping them to 'f'/'m' also makes the pokeemerald
    constants SPECIES_NIDORAN_F / _M land on the same keys as the display
    names, which is the whole point of the function.
    """
    s = str(s).strip()
    if s.upper().startswith("SPECIES_"):
        s = s[len("SPECIES_"):]
    s = s.replace("\u2640", "f").replace("\u2642", "m")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def normalize(name):
    """'SPECIES_MR_MIME' / 'mr. mime' / 'MRMIME' -> the canonical table name.

    Accepts the three spellings that actually occur in this project's data:
    a pokeemerald SPECIES_* constant (from the mined trainerbattle blocks), a
    wire-format party name (from the Lua hook, already canonical), and free
    text from a generated line. Returns None when nothing matches, so callers
    can distinguish "not a species" from "a species we failed to spell".
    """
    if not name:
        return None
    flat = _flatten(name)
    if not flat:
        return None
    return _FLAT.get(flat)


_FLAT = {}
for _n in SPECIES_NAMES:
    _k = _flatten(_n)
    # Loud on collision rather than last-one-wins. A silent collision here
    # under-counts M1a possession violations, which is a false PASS -- the
    # failure direction this whole harness exists to catch.
    if _k in _FLAT and _FLAT[_k] != _n:
        raise ValueError(
            f"species key collision: {_FLAT[_k]!r} and {_n!r} both flatten to "
            f"{_k!r}. Widen _flatten() rather than letting one silently win.")
    _FLAT[_k] = _n

# One alternation over every species name, longest first so that a longer name
# wins over a shorter one it contains (Nidorina before Nidoran). \b on both
# ends gives the word-boundary match the spec asks for.
_MENTION = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in
                      sorted(SPECIES_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)


def find_mentions(text):
    """[(canonical_name, start, end)] for every species named in `text`.

    Case-insensitive, word-boundary matched. Overlapping names cannot both
    match because the alternation is longest-first and `re` scans left to
    right without backtracking into an already-consumed span.
    """
    out = []
    for m in _MENTION.finditer(text or ""):
        canon = _CANON.get(m.group(1).lower())
        if canon:
            out.append((canon, m.start(), m.end()))
    return out


if __name__ == "__main__":
    print(f"{len(SPECIES_BY_INDEX)} indices, {len(SPECIES_NAMES)} distinct names")
    print("source:", SPECIES_LUA)
    print("sample:", SPECIES_NAMES[:5], "...", SPECIES_NAMES[-3:])
    print("normalize('SPECIES_MAGNEMITE') ->", normalize("SPECIES_MAGNEMITE"))
    print("find_mentions('My Magnemite and a wild ZIGZAGOON') ->",
          [n for n, _, _ in find_mentions("My Magnemite and a wild ZIGZAGOON")])
