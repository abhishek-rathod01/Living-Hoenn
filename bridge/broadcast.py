"""
broadcast.py -- dynamic TV: HOENN NEWS bulletins + 'WHO'S THAT POKEMON?' quiz.

Routed when npc_id == 0: signs/TVs never set gSpecialVar_LastTalked (verified:
LOCALID_NONE = 0, reset each input, assigned only for object events), and every
scripted message -- TVs included -- flows through ShowFieldMessage, i.e. our
existing trigger. News is composed ONLY from real state (completed quests,
badges, party, champion flag) -- deterministic core, so it can't invent deeds.
The quiz uses the verified A/B choice loop (await_choice action).
"""

import random
import re

from world_tables import MAPS

_SPECIES = None


def species_names():
    global _SPECIES
    if _SPECIES is None:
        _SPECIES = []
        try:
            for line in open("species_names.lua", encoding="utf-8"):
                m = re.search(r'= "([^"]+)"', line)
                if m:
                    _SPECIES.append(m.group(1))
        except OSError:
            _SPECIES = ["Pikachu", "Zigzagoon", "Poochyena", "Taillow"]
    return _SPECIES


LEGENDARIES = {"Kyogre", "Groudon", "Rayquaza", "Latias", "Latios", "Regirock",
               "Regice", "Registeel", "Mew", "Mewtwo", "Lugia", "Ho-oh",
               "Celebi", "Articuno", "Zapdos", "Moltres", "Raikou", "Entei",
               "Suicune", "Jirachi", "Deoxys"}

_pending = {}   # quiz answers keyed by (map_group, map_num)


def _deeds(qm):
    out = []
    for key, entry in qm.quests.items():
        if entry.get("state") == "rewarded":
            try:
                g, n, _ = (int(x) for x in key.split(":"))
                out.append(MAPS.get((g, n), "somewhere in Hoenn"))
            except ValueError:
                pass
    return out


def news(gs, qm):
    lines = ["HOENN NEWS NETWORK!"]
    if gs.get("game_clear"):
        lines.append("Our reigning CHAMPION continues to inspire the region!")
    deeds = _deeds(qm)
    if deeds:
        lines.append(f"A kind trainer was seen helping folks near {deeds[-1]}.")
    legends = [p.split(":")[0] for p in gs.get("party") or []
               if p.split(":")[0] in LEGENDARIES]
    if legends:
        lines.append(f"Unconfirmed sightings of the legendary {legends[0]} "
                     "traveling WITH a trainer! Experts are stunned.")
    b = int(gs.get("badges", 0) or 0)
    if not gs.get("game_clear"):
        lines.append(f"Gym watch: our rising star holds {b} badge{'s'*(b!=1)}!")
    return " ".join(lines)


def quiz(gs):
    pool = [s for s in species_names() if s[0].isalpha()]
    correct, decoy = random.sample(pool, 2)
    answer = random.choice((1, 2))
    opts = (correct, decoy) if answer == 1 else (decoy, correct)
    _pending[(gs.get("map_group"), gs.get("map_num"))] = \
        {"answer": answer, "species": correct}
    hint = f"{len(correct)} letters, starts with {correct[0]}"
    line = (f"WHO'S THAT POKEMON? Hint: {hint}! "
            f"Press A for {opts[0]} or B for {opts[1]}!")
    return line, [f"await_choice:600"]


def resolve(gs):
    key = (gs.get("map_group"), gs.get("map_num"))
    p = _pending.pop(key, None)
    choice = int(gs.get("choice", 0) or 0)
    if not p:
        return "And now, back to your program.", []
    if choice == 0:
        return f"Time's up! It was {p['species']}! Better luck next time!", []
    if choice == p["answer"]:
        return (f"Correct! It's {p['species']}! Please accept this prize!",
                ["give_item:139:1"])          # an Oran Berry, on the house
    return f"Ooh, so close! It was {p['species']}! Thanks for playing!", []


def handle(gs, qm, mode=None):
    mode = mode or random.choice(("news", "quiz"))
    if mode == "quiz":
        return quiz(gs)
    return news(gs, qm), []
