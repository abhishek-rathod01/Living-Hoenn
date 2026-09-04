"""eval/dataset.py -- builds the frozen evaluation set (spec section 2).

WHY THIS EXISTS (spec section 1): the trainer_defeated bug shipped a grounding
layer that stated fabricated facts, and a 16-test suite did not catch it
because those tests measure whether functions return, not what the system
says. This package measures what the system says. Those are different things
and only the first one matters for quality.

WHY IT IS FROZEN: without a fixed corpus, two runs are not comparable and the
section 6 ablation grid is impossible. eval_set.json is generated once, with a
fixed seed, and committed. Regenerate it deliberately -- never hand-edit it,
and never regenerate it casually mid-experiment, because doing so silently
invalidates every run recorded against the previous eval-set hash.

    python eval/dataset.py --sample 5     # show 5 entries, write nothing
    python eval/dataset.py --write        # (re)generate eval/eval_set.json

Composition (spec section 2): the 103 mined object events crossed with a small
fixed set of player states, stratified so trainers, non-trainer NPCs, signs
(npc_id == 0) and service NPCs are all represented. Target ~200 entries.
"""

import argparse
import hashlib
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _d in (_REPO, os.path.join(_REPO, "bridge"), _HERE):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from species_lexicon import normalize as _species  # noqa: E402

MINED_PATH = os.path.join(_REPO, "extraction", "npc_dialogue_table.json")
OUT_PATH = os.path.join(_HERE, "eval_set.json")

#: Bumping this invalidates comparability with older runs on purpose.
SEED = 20260904
TARGET_SIZE = 200


# --------------------------------------------------------------- player states
# Spec section 2: "a small fixed set of player states (early/mid/late badges,
# champion flag on/off, ordinary party, legendary party, empty-ish party)".
# Party strings use the wire's "Name:level" convention -- the same one
# dialogue_bridge_server._party_mons splits on.
PLAYER_STATES = [
    {"label": "early_rookie",
     "party": ["Torchic:8"], "badges": 0, "game_clear": 0},
    {"label": "early_ordinary",
     "party": ["Marshtomp:19", "Zigzagoon:12", "Taillow:14"],
     "badges": 2, "game_clear": 0},
    {"label": "mid_ordinary",
     "party": ["Combusken:28", "Gyarados:26", "Ninjask:25", "Numel:24"],
     "badges": 4, "game_clear": 0},
    {"label": "late_experienced",
     "party": ["Blaziken:45", "Swampert:44", "Gardevoir:43", "Manectric:42"],
     "badges": 7, "game_clear": 0},
    {"label": "champion_legendary",
     "party": ["Rayquaza:70", "Blaziken:62", "Latios:60"],
     "badges": 8, "game_clear": 1},
    {"label": "sparse_underlevelled",
     "party": ["Wingull:5"], "badges": 1, "game_clear": 0},
]

#: Spec section 2 wants signs represented, and the mined table has none
#: (every one of its 103 rows is an object event; the pilot maps' signs are
#: bg_events, which the extractor deliberately did not mine -- see the
#: extraction_notes on map 0:4). Signs are therefore synthesised from the
#: pilot maps, with npc_id == 0, which is precisely the input the bridge must
#: answer with the skip sentinel. Text is generic on purpose: M4 asserts on
#: the reply, and the reply must not depend on what the sign says.
SIGN_MAPS = [(0, 4), (0, 5), (0, 1), (0, 25), (9, 11)]
SIGN_LINES = [
    "FORTREE CITY  The Treetop City That Feels Like a Forest",
    "LILYCOVE CITY  Where the Land Ends and the Sea Begins",
    "SLATEPORT CITY  The Port Where People and Pokemon Cross",
    "ROUTE 110  Slateport City - Mauville City",
    "POKEMON CENTER  Heal Your Tired Pokemon Here",
]


# ----------------------------------------------------------------- classifying
def classify(entry):
    """Stratum for one mined entry. Mirrors the branches handle_request()
    actually takes, so the strata correspond to real code paths rather than to
    a taxonomy invented for the eval set.

    Order matters: the object-type gate in handle_request runs BEFORE any
    persona work, so a berry tree that somehow carried a trainerbattle would
    still be gated as an object. Classifying trainers first would misreport
    which branch the entry exercises.
    """
    otype = str(entry.get("object_type", ""))
    if not otype.startswith("person"):
        return "object"
    if entry.get("trainerbattle"):
        return "trainer"
    if entry.get("giveitem") or entry.get("shop_items") or \
            entry.get("shop_decor_items"):
        return "service"
    return "npc"


def trainer_party(entry):
    """[{"species": canonical, "level": int}] for a mined trainerbattle, or [].

    Returns [] for a battle with no single true party. Three real shapes occur
    in the mined table and they are NOT interchangeable -- checked against the
    data rather than assumed:
      1. a dict with "party"           -- the ordinary case (14 of 16)
      2. a LIST of dicts (0:5:17)      -- the gender x starter rival, several
                                          mutually exclusive parties
      3. a dict with "trainers" plural and no "party" (0:25:28) -- the rival
                                          coord-event scene, party_example only
    Cases 2 and 3 have no single correct answer, so naming any Pokemon for
    them would be wrong most of the time. _trainer_grounding() in the bridge
    already refuses to name one; this mirrors that refusal so the metric never
    penalises the bridge for being right.
    """
    tb = entry.get("trainerbattle")
    if not tb:
        return []
    if isinstance(tb, list):
        return []                       # case 2: multi-variant, no one truth
    if not isinstance(tb, dict):
        return []
    if tb.get("trainers"):
        return []                       # case 3: multi-trainer scene
    out = []
    for mon in tb.get("party") or []:
        canon = _species(mon.get("species"))
        if canon:
            out.append({"species": canon, "level": mon.get("lvl")})
    return out


def vanilla_lines(entry):
    """Every resolved vanilla line attached to this object event."""
    out = []
    for d in entry.get("dialogue") or []:
        t = d.get("text")
        if t:
            out.append(t)
    tb = entry.get("trainerbattle")
    for block in (tb if isinstance(tb, list) else [tb] if isinstance(tb, dict) else []):
        for k in ("intro_text_resolved", "defeat_text_resolved"):
            if block.get(k):
                out.append(block[k])
    return out


def archetype_hint(entry):
    """A coarse role guess from the sprite id, used only as a soft hint.

    Deliberately NOT authoritative: graphics_id says what an NPC looks like,
    not what they are, and the mined table carries no role field. M2's
    role_break rule uses the real archetype from npc_profiles.json at run
    time; this is context for a human reading the eval set.
    """
    g = str(entry.get("graphics_id", "")).replace("OBJ_EVENT_GFX_", "").lower()
    for needle, role in (("nurse", "healer"), ("beauty", "beauty"),
                         ("sailor", "sailor"), ("fisherman", "fisherman"),
                         ("scientist", "scientist"), ("hiker", "hiker"),
                         ("cook", "cook"), ("clerk", "shop clerk"),
                         ("teacher", "teacher"), ("old_man", "elder"),
                         ("old_woman", "elder"), ("boy", "child"),
                         ("girl", "child"), ("triathlete", "triathlete"),
                         ("psychic", "psychic"), ("camper", "camper"),
                         ("picnicker", "picnicker")):
        if needle in g:
            return role
    return None


def player_party_species(state):
    """Canonical species names from a player state's wire-format party."""
    out = []
    for p in state["party"]:
        canon = _species(p.split(":")[0])
        if canon:
            out.append(canon)
    return out


# -------------------------------------------------------------------- building
def _entry(idx, key, entry, state, map_names, stratum):
    group, num, npc_id = (int(x) for x in key.split(":"))
    lines = vanilla_lines(entry)
    tparty = trainer_party(entry)
    rng = random.Random(f"{SEED}:{key}:{state['label']}")
    original = rng.choice(lines) if lines else ""

    context = {
        "npc_id": npc_id, "map_group": group, "map_num": num,
        "original_line": original,
        "party": list(state["party"]),
        "badges": state["badges"], "game_clear": state["game_clear"],
    }
    # trainer_defeated is tri-state on the wire: the hook OMITS the field for
    # an NPC it has no flag for, rather than sending 0 (that conflation WAS
    # the trainer_defeated bug, fixed in 8838b36). The eval set must carry all
    # three states inside the trainer stratum or it cannot exercise the fix --
    # an eval set with only 1/0 would score a regression to the buggy
    # behaviour as perfect, which is precisely the blind spot that let the
    # original bug ship.
    if stratum == "trainer":
        context["trainer_defeated"] = (1, 0, None)[idx % 3]
    else:
        context["trainer_defeated"] = None

    return {
        "id": f"eval_{idx:04d}",
        "stratum": stratum,
        "player_state": state["label"],
        "context": context,
        "ground_truth": {
            "is_trainer": stratum == "trainer",
            "trainer_party": tparty,
            "player_party_species": player_party_species(state),
            "archetype_hint": archetype_hint(entry),
            "map_name": map_names.get(f"{group}:{num}", f"map {group}-{num}"),
            "vanilla_lines": lines,
            "object_type": entry.get("object_type"),
            "expect_skip": False,
        },
    }


def _sign_entry(idx, group, num, line, state, map_names):
    return {
        "id": f"eval_{idx:04d}",
        "stratum": "sign",
        "player_state": state["label"],
        "context": {
            "npc_id": 0, "map_group": group, "map_num": num,
            "original_line": line,
            "party": list(state["party"]),
            "badges": state["badges"], "game_clear": state["game_clear"],
            "trainer_defeated": None,
        },
        "ground_truth": {
            "is_trainer": False,
            "trainer_party": [],
            "player_party_species": player_party_species(state),
            "archetype_hint": None,
            "map_name": map_names.get(f"{group}:{num}", f"map {group}-{num}"),
            "vanilla_lines": [line],
            "object_type": "sign (bg_event, synthesised -- see dataset.py)",
            "expect_skip": True,
        },
    }


def build(target=TARGET_SIZE, mined_path=MINED_PATH):
    """The frozen eval set as a dict. Deterministic for a fixed SEED.

    Stratification: every mined object event appears at least once, so no NPC
    is missing from the corpus, and the remaining budget is spent round-robin
    across strata rather than uniformly at random -- uniform sampling would
    swamp the 16 trainers under the 87 ordinary NPCs and leave the trainer
    stratum too small to say anything about, which is the stratum M1a exists
    to measure.
    """
    mined = json.load(open(mined_path, encoding="utf-8"))
    npcs = mined["npcs"]
    map_names = {k: v.get("name", k) for k, v in (mined.get("_maps") or {}).items()}

    by_stratum = {}
    for key, entry in npcs.items():
        by_stratum.setdefault(classify(entry), []).append((key, entry))
    for v in by_stratum.values():
        v.sort()                              # deterministic order

    rng = random.Random(SEED)
    entries, idx = [], 0

    # Pass 1: every mined object event once, cycling player states so the
    # states are evenly spread rather than correlated with map order.
    for stratum in sorted(by_stratum):
        for i, (key, entry) in enumerate(by_stratum[stratum]):
            entries.append(_entry(idx, key, entry, PLAYER_STATES[i % len(PLAYER_STATES)],
                                  map_names, stratum))
            idx += 1

    # Pass 2: signs, one per pilot map, one per player state.
    for i, ((group, num), line) in enumerate(zip(SIGN_MAPS, SIGN_LINES)):
        for j, state in enumerate(PLAYER_STATES):
            if len(entries) >= target:
                break
            entries.append(_sign_entry(idx, group, num, line, state, map_names))
            idx += 1

    # Pass 3: fill the remaining budget round-robin across strata, pairing
    # each NPC with a player state it has not already been seen with.
    seen = {(e["context"]["map_group"], e["context"]["map_num"],
             e["context"]["npc_id"], e["player_state"]) for e in entries}
    order = sorted(by_stratum)
    cursor = {s: 0 for s in order}
    guard = 0
    while len(entries) < target and guard < target * 50:
        guard += 1
        for stratum in order:
            if len(entries) >= target:
                break
            pool = by_stratum[stratum]
            key, entry = pool[cursor[stratum] % len(pool)]
            cursor[stratum] += 1
            group, num, npc_id = (int(x) for x in key.split(":"))
            for state in rng.sample(PLAYER_STATES, len(PLAYER_STATES)):
                if (group, num, npc_id, state["label"]) not in seen:
                    entries.append(_entry(idx, key, entry, state, map_names, stratum))
                    seen.add((group, num, npc_id, state["label"]))
                    idx += 1
                    break

    payload = {
        "_generated_by": "eval/dataset.py -- do not hand-edit; regenerate",
        "_seed": SEED,
        "_source": "extraction/npc_dialogue_table.json",
        "_spec": "docs/EVAL_HARNESS_SPEC.md section 2",
        "_note": ("Frozen corpus. Regenerating invalidates comparability with "
                  "every run recorded against a different _eval_set_hash."),
        "_counts": _counts(entries),
        "entries": entries,
    }
    payload["_eval_set_hash"] = eval_set_hash(entries)
    return payload


def _counts(entries):
    c = {}
    for e in entries:
        c[e["stratum"]] = c.get(e["stratum"], 0) + 1
    return dict(sorted(c.items()))


def eval_set_hash(entries):
    """Stable content hash. Every run records this; a run whose hash differs
    from another's was measured against a different corpus and the two numbers
    must not be compared."""
    blob = json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def load(path=OUT_PATH):
    """The frozen set as committed. Raises if it has not been generated."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found. Generate it with: python eval/dataset.py --write")
    return json.load(open(path, encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", type=int, metavar="N",
                    help="print N entries and exit without writing anything")
    ap.add_argument("--write", action="store_true",
                    help="(re)generate eval/eval_set.json -- invalidates old runs")
    ap.add_argument("--target", type=int, default=TARGET_SIZE)
    args = ap.parse_args()

    payload = build(target=args.target)
    print(f"built {len(payload['entries'])} entries  seed={SEED}  "
          f"hash={payload['_eval_set_hash']}")
    print("strata:", payload["_counts"])

    if args.sample:
        for e in payload["entries"][:args.sample]:
            print("\n" + "-" * 72)
            print(json.dumps(e, indent=2, ensure_ascii=False))
    if args.write:
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"\nwrote {OUT_PATH}")
    elif not args.sample:
        print("\n(nothing written -- pass --write to freeze, --sample N to inspect)")


if __name__ == "__main__":
    main()
