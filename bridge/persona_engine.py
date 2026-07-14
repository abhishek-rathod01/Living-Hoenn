"""
persona_engine.py -- deterministic, persistent NPC personalities.

Personality is PINNED, not prompted: a persona card is generated ONCE per NPC
(keyed by map_group:map_num:npc_id, same key as quests), validated, cached to
disk, and injected into every later prompt. Same NPC = same personality forever,
across bridge restarts -- consistency comes from storage, not model memory.

Inputs available to the persona designer: the NPC's ORIGINAL vanilla line
(hook v3 captures it), map, player's badges/party -- so personalities are
derived from the game, not randomized.
"""

import json
import os

MAXLEN = {"archetype": 40, "temperament": 60, "quirk": 80, "greeting": 120}
HISTORY_LEN = 2   # short rolling window -- just enough to stop back-to-back
                  # near-repeats (the observed live bug) without biasing the
                  # model toward an ever-growing transcript


def validate_persona(card):
    if not isinstance(card, dict):
        return False, "not an object"
    for field, cap in MAXLEN.items():
        v = card.get(field)
        if not (isinstance(v, str) and 1 <= len(v.strip()) <= cap):
            return False, f"{field} must be a 1..{cap} char string"
    return True, ""


def describe(card):
    """One line for prompt injection."""
    return ("{archetype}; temperament: {temperament}; quirk: {quirk}"
            .format(**card))


class PersonaStore:
    def __init__(self, path="npc_profiles.json"):
        self.path = path
        self.cards = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.cards = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.cards = {}

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cards, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)

    def get_or_create(self, key, designer, game_state):
        """Returns a valid card or None. Designer runs at most once per NPC."""
        if key in self.cards:
            return self.cards[key]
        card = None
        try:
            card = designer(game_state)
        except Exception:
            return None
        ok, _ = validate_persona(card) if card else (False, "")
        if not ok:
            return None
        card = {k: card[k].strip() for k in MAXLEN}
        self.cards[key] = card
        self._save()
        return card

    def recent_lines(self, key):
        """Last HISTORY_LEN chatter lines actually said by this NPC, oldest
        first -- stored under a '_recent_lines' key alongside the persona
        card in the same npc_profiles.json entry (a plain list, not a
        validated persona field, so validate_persona/the MAXLEN strip in
        get_or_create above never touch it)."""
        card = self.cards.get(key)
        return list(card.get("_recent_lines", [])) if card else []

    def record_line(self, key, line):
        """Append a freshly-said chatter line to that NPC's rolling history,
        trimmed to the last HISTORY_LEN. No-op if the NPC has no persona card
        yet (nothing to attach history to)."""
        card = self.cards.get(key)
        if card is None:
            return
        hist = card.get("_recent_lines", [])
        hist.append(line)
        card["_recent_lines"] = hist[-HISTORY_LEN:]
        self._save()
