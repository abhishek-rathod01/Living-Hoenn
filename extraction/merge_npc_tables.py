"""
merge_npc_tables.py -- merge per-map NPC extractions into one generated table.

    python extraction/merge_npc_tables.py [--pokeemerald PATH]

Inputs:  extraction/raw/raw_*.json  (one per map, produced by the map-extractor
         subagent pass; dialogue rows carry a text LABEL and optionally text)
Output:  extraction/npc_dialogue_table.json  keyed "map_group:map_num:local_id"
         (same key convention persona_engine.py / npc_profiles.json use)

What this script does beyond concatenation -- each step is a source-side
verification, not a trust-the-agent step:

1. KEY CHECK: re-derives (map_group, map_num) for every map from the
   pokeemerald map_groups.json (group = index in group_order, num = index in
   that group's list -- the same convention world_tables.py was generated
   with) and refuses to merge a raw file whose keys disagree.
2. TEXT RESOLUTION: every dialogue label (FooCity_Text_Bar, gText_Baz, ...)
   is resolved to its actual .string body by scanning the pokeemerald data/
   tree. Labels are the agents' claim; the resolved text comes straight from
   source. Where an agent also supplied text, the two are compared
   (whitespace-normalized) and disagreements are reported.
3. SHARED-SCRIPT FLAGGING: any script referenced by more than one object
   event is listed in _shared_scripts -- those NPCs need distinct persona
   keys even though their extracted lines are identical.

Do not hand-edit the generated table; fix the raw files or this script and
regenerate.
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_POKEEMERALD = os.path.join(
    os.path.dirname(os.path.dirname(HERE)), "..", "pokeemerald"
)
# The layout above ("..", "..") depends on where the repo sits; resolve the
# user's actual clone location first, fall back to a --pokeemerald argument.
KNOWN_POKEEMERALD = r"C:\Users\abhis\Desktop\Living hoenn\pokeemerald"

STRING_RE = re.compile(r'^\s*\.string\s+"(.*)"\s*$')
LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):{1,2}\s*(?:@.*)?$")
KEY_RE = re.compile(r"^(\d+):(\d+):(\d+)$")


def derive_group_num(pokeemerald, map_name):
    """(map_group, map_num) from map_groups.json -- group_order index, then
    index within the group's map list. Same convention as world_tables.py."""
    path = os.path.join(pokeemerald, "data", "maps", "map_groups.json")
    with open(path, encoding="utf-8") as f:
        groups = json.load(f)
    for g_i, g_name in enumerate(groups["group_order"]):
        maps = groups[g_name]
        if map_name in maps:
            return g_i, maps.index(map_name)
    raise KeyError("map %r not present in map_groups.json" % map_name)


def build_label_index(pokeemerald):
    """Scan every file under data/ that contains .string directives and map
    label -> decoded text. A label directly above another label shares the
    following .string block (both names point at the same text)."""
    index = {}
    roots = [os.path.join(pokeemerald, "data")]
    files = []
    for root in roots:
        for pat in ("**/*.inc", "**/*.s", "**/*.h"):
            files.extend(glob.glob(os.path.join(root, pat), recursive=True))
    for path in sorted(set(files)):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        pending = []  # labels awaiting their .string block
        chunks = []
        for line in lines:
            m = STRING_RE.match(line)
            if m:
                chunks.append(m.group(1))
                continue
            # a non-.string line ends any open block
            if chunks and pending:
                text = decode_string_chunks(chunks)
                for lab in pending:
                    index.setdefault(lab, text)
                pending, chunks = [], []
            elif chunks:
                chunks = []
            lm = LABEL_RE.match(line.strip())
            if lm:
                pending.append(lm.group(1))
            elif line.strip() and not line.strip().startswith(("@", ";", ".")):
                pending = []
        if chunks and pending:  # file ended inside a block
            text = decode_string_chunks(chunks)
            for lab in pending:
                index.setdefault(lab, text)
    return index


def decode_string_chunks(chunks):
    """Join .string chunks into one readable line. \\n \\l \\p are printer
    line/paragraph breaks -> single spaces here (the bridge re-wraps text
    itself). Placeholders like {PLAYER} are kept verbatim. Trailing $ = EOS."""
    text = "".join(chunks)
    if text.endswith("$"):
        text = text[:-1]
    # hyphenated line continuation ("life-\l" + "forms") joins with no space
    text = re.sub(r"-\\[nl]", "-", text)
    text = re.sub(r"\\[nlp]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm(s):
    """Whitespace-collapse for agent-vs-source comparison."""
    return re.sub(r"\s+", " ", (s or "")).strip()


def merge(pokeemerald, raw_dir, out_path):
    label_index = build_label_index(pokeemerald)
    print("label index: %d .string labels found under data/" % len(label_index))

    merged = {
        "_generated_by": "extraction/merge_npc_tables.py -- do not hand-edit",
        "_key_convention": "map_group:map_num:local_id (local_id = 1-based "
                           "position in map.json object_events)",
        "_maps": {},
        "_shared_scripts": {},
        "npcs": {},
    }
    unresolved = []
    mismatches = []
    script_owners = {}

    for path in sorted(glob.glob(os.path.join(raw_dir, "raw_*.json"))):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        map_name = raw["_map"]
        g, n = derive_group_num(pokeemerald, map_name)
        if (g, n) != (raw["_map_group"], raw["_map_num"]):
            raise SystemExit(
                "KEY CHECK FAILED for %s: raw file says %d:%d, map_groups.json "
                "derives %d:%d" % (map_name, raw["_map_group"], raw["_map_num"], g, n)
            )
        merged["_maps"]["%d:%d" % (g, n)] = {
            "name": map_name,
            "weather": raw["_weather"],
            "map_type": raw["_map_type"],
            "region_map_section": raw["_region_map_section"],
            "extraction_notes": raw.get("_agent_notes", ""),
        }
        for key, entry in raw["entries"].items():
            if not KEY_RE.match(key):
                raise SystemExit("bad key %r in %s" % (key, path))
            kg, kn, _ = KEY_RE.match(key).groups()
            if (int(kg), int(kn)) != (g, n):
                raise SystemExit(
                    "key %r in %s does not match derived map id %d:%d"
                    % (key, path, g, n)
                )
            for row in entry.get("dialogue", []):
                # raw files use either "label" or "string" for the .string
                # label name; normalize to "label" in the merged output
                label = row.get("label") or row.get("string")
                if "string" in row:
                    row["label"] = label
                    del row["string"]
                if not label:
                    continue
                source_text = label_index.get(label)
                agent_text = row.get("text")
                if source_text is None:
                    unresolved.append((key, label))
                    row["text"] = agent_text  # keep agent text if any, else None
                    row["text_source"] = "agent-only (label not found in data/)"
                else:
                    if agent_text and norm(agent_text) != norm(source_text):
                        mismatches.append((key, label))
                    row["text"] = source_text
                    row["text_source"] = "resolved from pokeemerald data/"
            # resolve trainer intro/defeat text labels too
            tb = entry.get("trainerbattle")
            for tb_one in (tb if isinstance(tb, list) else [tb] if tb else []):
                for fld in ("intro_text", "defeat_text"):
                    lab = tb_one.get(fld)
                    if lab and lab in label_index:
                        tb_one[fld + "_resolved"] = label_index[lab]
            script = entry.get("script")
            if script and script != "0x0":
                script_owners.setdefault(script, []).append(key)
            merged["npcs"][key] = entry

    merged["_shared_scripts"] = {
        s: owners for s, owners in sorted(script_owners.items()) if len(owners) > 1
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("merged %d NPC entries across %d maps -> %s"
          % (len(merged["npcs"]), len(merged["_maps"]), out_path))
    print("shared scripts (need distinct persona keys): %d"
          % len(merged["_shared_scripts"]))
    for s, owners in merged["_shared_scripts"].items():
        print("  %s <- %s" % (s, ", ".join(owners)))
    if unresolved:
        print("UNRESOLVED labels (%d):" % len(unresolved))
        for key, lab in unresolved:
            print("  %s %s" % (key, lab))
    if mismatches:
        print("AGENT-vs-SOURCE text mismatches (%d) -- source text kept:"
              % len(mismatches))
        for key, lab in mismatches:
            print("  %s %s" % (key, lab))
    return 0 if not unresolved else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pokeemerald", default=None)
    ap.add_argument("--raw-dir", default=os.path.join(HERE, "raw"))
    ap.add_argument("--out", default=os.path.join(HERE, "npc_dialogue_table.json"))
    args = ap.parse_args()
    pokeemerald = args.pokeemerald or (
        KNOWN_POKEEMERALD if os.path.isdir(KNOWN_POKEEMERALD) else DEFAULT_POKEEMERALD
    )
    if not os.path.isdir(os.path.join(pokeemerald, "data", "maps")):
        raise SystemExit("pokeemerald clone not found at %r -- pass --pokeemerald"
                         % pokeemerald)
    sys.exit(merge(pokeemerald, args.raw_dir, args.out))


if __name__ == "__main__":
    main()
