"""
quest_bridge_server.py -- Phase 4 bridge: personas + LLM-designed quests.

Protocol: newline JSON in, "actions|dialogue" (or bare dialogue) out.
See quest_engine.py for the quest state machine and validation gate, and
persona_engine.py for pinned NPC personalities.

RUN
---
  python quest_bridge_server.py --echo     # canned designers, no model needed
  python quest_bridge_server.py            # Ollama (qwen2.5:7b by default)
"""

import argparse
import json
import random
import socket

import persona_engine
import quest_engine
from items_table import ITEMS, REWARDABLE
from world_tables import MAPS
import advisor
from quest_engine import ISLAND_UNLOCKS

HOST, PORT = "127.0.0.1", 8888
SMALLTALK = "Nice weather we're having in Hoenn, huh?"   # quest_engine's fallback

PERSONA_SYSTEM = """You invent a personality for ONE Pokemon Emerald NPC.
Reply with ONLY a JSON object, no prose, no fences, exactly:
{"archetype":"...","temperament":"...","quirk":"...","greeting":"..."}
Derive it from the NPC's original game line, their location, and the player's
progress. Gen-3 tone. archetype<=40 chars, temperament<=60, quirk<=80,
greeting<=120. greeting is a full spoken line."""

DESIGNER_SYSTEM = """You design ONE tiny side-quest for a Pokemon Emerald NPC.
Reply with ONLY a JSON object, no prose, no fences, exactly:
{"quest_type":"fetch_item","target":{"item_id":<int>,"quantity":<1-3>},
 "reward":{"item_id":<int>,"quantity":<1-3>},
 "flavor":{"intro":"...","reminder":"...","complete":"..."}}
Rules:
- item_id values MUST come from the CHOICES list you are given.
- Write flavor lines IN CHARACTER for the persona you are given.
- Each flavor line: Gen-3 tone, under 40 words, no quote marks."""


def _choices_menu(k=8):
    ids = random.sample(sorted(REWARDABLE), k)
    return ", ".join(f"{i}={ITEMS[i]}" for i in ids)


def _gs_summary(gs):
    loc = MAPS.get((gs.get("map_group"), gs.get("map_num")),
                   f"map {gs.get('map_group')}-{gs.get('map_num')}")
    return (f"NPC original line: {gs.get('original_line','')!r}\n"
            f"Location: {loc}  "
            f"Badges: {gs.get('badges', 0)}  GameClear: {gs.get('game_clear', 0)}\n"
            f"Player party: {gs.get('party')}")


def make_llm_designers(model="qwen2.5:7b"):
    import ollama

    def _json_of(text):
        text = text.strip()
        return json.loads(text[text.find("{"): text.rfind("}") + 1])

    def persona_designer(gs):
        resp = ollama.chat(model=model, options={"temperature": 0.9},
                           messages=[{"role": "system", "content": PERSONA_SYSTEM},
                                     {"role": "user", "content": _gs_summary(gs)}])
        return _json_of(resp.message.content)

    def quest_designer(gs):
        user = (_gs_summary(gs) + "\n"
                f"Persona: {gs.get('persona_desc', 'a friendly local')}\n"
                f"CHOICES (id=name): {_choices_menu()}\n"
                "Design the quest JSON now.")
        resp = ollama.chat(model=model, options={"temperature": 0.8},
                           messages=[{"role": "system", "content": DESIGNER_SYSTEM},
                                     {"role": "user", "content": user}])
        return _json_of(resp.message.content)

    return persona_designer, quest_designer


def echo_persona(gs):
    return {"archetype": "gruff berry farmer",
            "temperament": "brusque but kind underneath",
            "quirk": "compares everything to soil quality",
            "greeting": "Hmph. Good soil today. You need something, trainer?"}


def echo_quest(gs):
    oran = next(i for i, n in ITEMS.items() if n == "Oran Berry")
    potion = next(i for i, n in ITEMS.items() if n == "Potion")
    return {"quest_type": "fetch_item",
            "target": {"item_id": oran, "quantity": 2},
            "reward": {"item_id": potion, "quantity": 1},
            "flavor": {"intro": "Say, could you fetch me 2 Oran Berries?",
                       "reminder": "Still waiting on those Oran Berries!",
                       "complete": "My Oran Berries! Here, take this Potion."}}


SAILOR_PORTS = ("Lilycove City", "Slateport City")   # only these harbors run the event ferry (verified in their scripts.inc)
SAILOR_DESC = ("weathered old sailor; temperament: salt-cured and generous; "
               "quirk: speaks of the sea like an old friend")


def locked_islands(gs):
    m = int(gs.get("unlocks", 0) or 0)
    return [k for k, u in ISLAND_UNLOCKS.items() if not (m & u["bit"])]


def island_quest(island, port):
    names = {"southern_island": ("EON TICKET", "Southern Island"),
             "birth_island": ("AURORA TICKET", "Birth Island"),
             "faraway_island": ("OLD SEA MAP", "Faraway Island"),
             "navel_rock": ("MYSTIC TICKET", "Navel Rock")}
    ticket, isle = names[island]
    return {"quest_type": "fetch_item",
            "target": {"item_id": 139, "quantity": 2},
            "unlock": island,
            "flavor": {
                "intro": f"Ahoy! Fetch this old sailor 2 Oran Berries and I'll part "
                         f"with my {ticket} -- the ferry will take you to {isle}.",
                "reminder": "The sea waits, but my stomach doesn't. Those berries?",
                "complete": f"A deal's a deal! Take the {ticket} -- tell the harbor "
                            f"clerk you're bound for {isle}!"}}


def handle_request(gs, qm, pstore, quest_designer, persona_designer):
    """Testable core: one request dict in -> one reply line out."""
    # Professor hotline: SELECT held while talking -> deterministic tip, no quest flow.
    if gs.get("advice") == 1:
        return quest_engine.serialize_reply(advisor.get_tip(gs), [])

    # Sailor path: in a port town, an NPC with no quest yet offers the next
    # locked island's ticket. Persona is pinned sailor so it feels natural.
    loc = MAPS.get((gs.get("map_group"), gs.get("map_num")), "")
    key = quest_engine.QuestManager.key(gs)
    if loc in SAILOR_PORTS and key not in qm.quests:
        locked = locked_islands(gs)
        if locked:
            gs["persona_desc"] = SAILOR_DESC
            spec = island_quest(locked[0], loc)
            dialogue, actions = qm.handle_talk(gs, lambda _g: spec)
            return quest_engine.serialize_reply(dialogue, actions)
    card = pstore.get_or_create(key, persona_designer, gs)
    if card:
        gs["persona_desc"] = persona_engine.describe(card)
    dialogue, actions = qm.handle_talk(gs, quest_designer)
    # If the quest layer had nothing (designer declined/failed), let the
    # persona speak instead of the generic weather line.
    if dialogue == SMALLTALK and card:
        dialogue = card["greeting"]
    return quest_engine.serialize_reply(dialogue, actions)


def _log_line(path, gs, reply):
    if not path:
        return
    try:
        import time
        with open(path, "a") as f:
            f.write(json.dumps({"ts": time.time(),
                                "npc_id": gs.get("npc_id"),
                                "map": [gs.get("map_group"), gs.get("map_num")],
                                "badges": gs.get("badges"),
                                "reply": reply}) + "\n")
    except OSError:
        pass    # logging must never take the bridge down


def serve(port, quest_designer, persona_designer, store, profiles, log_path="transcripts.jsonl"):
    qm = quest_engine.QuestManager(store)
    pstore = persona_engine.PersonaStore(profiles)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(1)
    print(f"[quest-bridge] listening on {HOST}:{port} | quests: {store} | personas: {profiles}")
    try:
        while True:
            conn, addr = srv.accept()
            print(f"[quest-bridge] mGBA connected from {addr}")
            buffer = b""
            try:
                with conn:
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            print("[quest-bridge] mGBA disconnected")
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if not line.strip():
                                continue
                            try:
                                gs = json.loads(line.decode("utf-8"))
                                reply = handle_request(gs, qm, pstore,
                                                       quest_designer, persona_designer)
                            except json.JSONDecodeError as e:
                                reply = quest_engine.serialize_reply(f"[error] bad JSON: {e}", [])
                            except Exception as e:
                                reply = quest_engine.serialize_reply(
                                    f"[error] {type(e).__name__}: {e}", [])
                            conn.sendall(reply.encode("utf-8") + b"\n")
                            _log_line(log_path, gs if isinstance(gs, dict) else {}, reply)
                            print(f"[quest-bridge] -> {reply[:70]}")
            except (ConnectionError, OSError) as e:
                print(f"[quest-bridge] connection lost ({type(e).__name__}); waiting")
    except KeyboardInterrupt:
        print("\n[quest-bridge] shutting down")
    finally:
        srv.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--echo", action="store_true", help="canned designers (no LLM)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--store", default="quests.json")
    ap.add_argument("--profiles", default="npc_profiles.json")
    ap.add_argument("--log", default="transcripts.jsonl",
                    help="JSONL transcript path ('' to disable)")
    args = ap.parse_args()
    if args.echo:
        pd, qd = echo_persona, echo_quest
    else:
        pd, qd = make_llm_designers(args.model)
    serve(args.port, qd, pd, args.store, args.profiles, args.log)


if __name__ == "__main__":
    main()
