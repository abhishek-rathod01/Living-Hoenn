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


FRONTIER_GUIDE = [
    "Battle Tower tests raw streaks -- bring sturdy, reliable teams.",
    "Battle Dome is a 16-trainer tournament; scout opponents before each round.",
    "Battle Palace picks moves from your Pokemon's NATURE -- choose them wisely.",
    "Battle Arena judges Mind, Skill and Body every three turns; be aggressive.",
    "Battle Factory is all rentals -- your team-building eye is the real test.",
    "Battle Pike is luck and nerve; heal before you pick a corridor.",
    "Battle Pyramid strips your bag and lights; pack finds as you climb.",
]


def get_tip(gs):
    loc = MAPS.get((gs.get("map_group"), gs.get("map_num")))
    if loc == "Battle Frontier":
        i = (int(gs.get("npc_id", 0) or 0) + int(gs.get("badges", 0) or 0)) \
            % len(FRONTIER_GUIDE)
        return ("DAD: So you made it to the Frontier! Listen well -- "
                + FRONTIER_GUIDE[i] + " Make me proud out there.")
    where = f" You are near {loc}." if loc else ""
    if gs.get("game_clear"):
        return "PROF. BIRCH: " + POST_CLEAR + where
    badges = gs.get("badges", 0)
    tip = MILESTONES.get(min(int(badges), 8), MILESTONES[0])
    return f"PROF. BIRCH: {tip}{where} ({badges} badges so far.)"
