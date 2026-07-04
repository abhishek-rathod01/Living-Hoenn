"""
quest_engine.py -- Tier 1 quest system for the AI-powered Emerald bridge.

DESIGN RULE (the one that makes this safe): the LLM *designs* quests as strict
JSON; this engine validates against a whitelist and runs the state machine.
Free LLM text NEVER drives memory writes -- only validated IDs/quantities do.

Quest lifecycle per NPC (keyed by map + LastTalked local id):
    (no quest) --talk--> ACTIVE (intro line, quest stored)
    ACTIVE     --talk, not complete--> reminder line
    ACTIVE     --talk, complete-----> REWARDED (complete line + actions)
    REWARDED   --talk--> after line (no more rewards, ever)

Actions emitted to the emulator (executed by the Lua hook):
    take_item:ID:QTY   remove fetched items from the bag
    give_item:ID:QTY   grant the reward
Both are validated against items_table before they can ever be emitted.

Protocol note: the bridge serializes a reply as  "ACT;ACT|dialogue"  (or bare
dialogue when there are no actions). Newline-free by construction.
"""

import json
import os
from items_table import ITEMS, REWARDABLE

MAX_QTY = 5
MAX_TEXT = 200
QUEST_TYPES = ("fetch_item", "show_species")


# ---------------------------------------------------------------------------
# Validation: the gate between LLM output and anything that touches the game.
# ---------------------------------------------------------------------------
def validate_quest(spec):
    """Return (True, '') if spec is a safe, well-formed quest; else (False, why)."""
    if not isinstance(spec, dict):
        return False, "spec is not an object"
    qt = spec.get("quest_type")
    if qt not in QUEST_TYPES:
        return False, f"quest_type must be one of {QUEST_TYPES}"

    tgt = spec.get("target")
    if not isinstance(tgt, dict):
        return False, "target missing"
    if qt == "fetch_item":
        iid = tgt.get("item_id")
        if not (isinstance(iid, int) and iid in ITEMS):
            return False, "target.item_id not a known item"
        q = tgt.get("quantity")
        if not (isinstance(q, int) and 1 <= q <= MAX_QTY):
            return False, f"target.quantity must be 1..{MAX_QTY}"
    else:  # show_species
        sp = tgt.get("species")
        if not (isinstance(sp, str) and 1 <= len(sp) <= 12):
            return False, "target.species must be a short name"
        lvl = tgt.get("min_level", 1)
        if not (isinstance(lvl, int) and 1 <= lvl <= 100):
            return False, "target.min_level must be 1..100"

    rw = spec.get("reward")
    if not isinstance(rw, dict):
        return False, "reward missing"
    rid = rw.get("item_id")
    if not (isinstance(rid, int) and rid in REWARDABLE):
        return False, "reward.item_id not in the rewardable whitelist"
    rq = rw.get("quantity")
    if not (isinstance(rq, int) and 1 <= rq <= MAX_QTY):
        return False, f"reward.quantity must be 1..{MAX_QTY}"

    fl = spec.get("flavor")
    if not isinstance(fl, dict):
        return False, "flavor missing"
    for k in ("intro", "reminder", "complete"):
        v = fl.get(k)
        if not (isinstance(v, str) and 1 <= len(v) <= MAX_TEXT):
            return False, f"flavor.{k} must be a 1..{MAX_TEXT} char string"
    return True, ""


# ---------------------------------------------------------------------------
# Game-state helpers. The Lua hook sends:
#   party: ["Blaziken:45", "Mudkip:5"]      (name:level strings)
#   bag:   ["13:2", "139:5"]                (item_id:quantity strings)
# Parse defensively -- never crash on malformed emulator data.
# ---------------------------------------------------------------------------
def _pairs(lst):
    out = []
    for s in lst if isinstance(lst, list) else []:
        if isinstance(s, str) and ":" in s:
            a, b = s.rsplit(":", 1)
            if b.lstrip("-").isdigit():
                out.append((a, int(b)))
    return out


def bag_count(game_state, item_id):
    return sum(q for name, q in _pairs(game_state.get("bag")) 
               if name.isdigit() and int(name) == item_id)


def party_has(game_state, species, min_level):
    return any(n.lower() == species.lower() and lvl >= min_level
               for n, lvl in _pairs(game_state.get("party")))


def is_complete(spec, game_state):
    t = spec["target"]
    if spec["quest_type"] == "fetch_item":
        return bag_count(game_state, t["item_id"]) >= t["quantity"]
    return party_has(game_state, t["species"], t.get("min_level", 1))


# ---------------------------------------------------------------------------
# The manager: state machine + persistence.
# ---------------------------------------------------------------------------
class QuestManager:
    def __init__(self, path="quests.json"):
        self.path = path
        self.quests = {}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self.quests = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.quests = {}   # corrupt store: start clean, don't crash

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.quests, f, indent=1)
        os.replace(tmp, self.path)   # atomic: a crash can't corrupt the store

    @staticmethod
    def key(game_state):
        return "{}:{}:{}".format(game_state.get("map_group", -1),
                                 game_state.get("map_num", -1),
                                 game_state.get("npc_id", -1))

    def handle_talk(self, game_state, designer):
        """Main entry. Returns (dialogue, actions:list[str]).
        `designer(game_state) -> spec dict` is only called for brand-new NPCs."""
        k = self.key(game_state)
        entry = self.quests.get(k)

        if entry is None:
            spec = None
            try:
                spec = designer(game_state)
            except Exception:
                pass                       # designer (LLM) failure: no quest today
            ok, why = validate_quest(spec) if spec else (False, "no spec")
            if not ok:
                return ("Nice weather we're having in Hoenn, huh?", [])
            self.quests[k] = {"spec": spec, "state": "active"}
            self._save()
            return (spec["flavor"]["intro"], [])

        spec, state = entry["spec"], entry["state"]
        if state == "rewarded":
            return (spec["flavor"].get("after", "Thanks again for the help!"), [])

        # state == "active"
        if not is_complete(spec, game_state):
            return (spec["flavor"]["reminder"], [])

        actions = []
        if spec["quest_type"] == "fetch_item":
            t = spec["target"]
            actions.append("take_item:{}:{}".format(t["item_id"], t["quantity"]))
        rw = spec["reward"]
        actions.append("give_item:{}:{}".format(rw["item_id"], rw["quantity"]))
        entry["state"] = "rewarded"
        self._save()
        return (spec["flavor"]["complete"], actions)


def serialize_reply(dialogue, actions):
    """One newline-free line: 'ACT;ACT|dialogue' or bare dialogue."""
    dialogue = " ".join(str(dialogue).split()) or "..."
    if actions:
        return ";".join(actions) + "|" + dialogue
    return dialogue
