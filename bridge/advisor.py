"""
advisor.py -- 'ask the Professor what to do next'.

Hold SELECT while talking to any NPC and the reply becomes a progression tip
instead of dialogue (hook v3.1 sets advice=1 in the context).

The milestone table is deterministic and curated from the vanilla Emerald
progression (badge count -> next objective); the LLM is NOT in this path, so
tips can never hallucinate the walkthrough.
"""

from world_tables import MAPS

MILESTONES = {
    0: "Head to Rustboro City and challenge Roxanne at the Gym for the Stone Badge.",
    1: "Sail from Route 104 with Mr. Briney to Dewford Town -- Brawly awaits.",
    2: "Deliver the goods to Slateport, then push north to Mauville and battle Wattson.",
    3: "Climb Mt. Chimney, then descend the Jagged Pass to Lavaridge for Flannery.",
    4: "Return to Petalburg City -- it is time to face your father, Norman.",
    5: "Cross Route 119 to Fortree City and earn the Feather Badge from Winona.",
    6: "Make for Mossdeep City; Tate & Liza fight as a pair, so plan for doubles.",
    7: "Dive to Sootopolis. After the Kyogre/Groudon crisis, Juan grants the Rain Badge.",
    8: "Victory Road and the Elite Four are all that remain. Stock up and go.",
}
POST_CLEAR = ("You are the Champion! Explore the Battle Frontier -- and if a sailor "
              "mentions distant islands, hear them out.")


def get_tip(gs):
    loc = MAPS.get((gs.get("map_group"), gs.get("map_num")))
    where = f" You are near {loc}." if loc else ""
    if gs.get("game_clear"):
        return "PROF. BIRCH: " + POST_CLEAR + where
    badges = gs.get("badges", 0)
    tip = MILESTONES.get(min(int(badges), 8), MILESTONES[0])
    return f"PROF. BIRCH: {tip}{where} ({badges} badges so far.)"
