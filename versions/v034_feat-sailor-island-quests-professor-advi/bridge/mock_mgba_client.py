"""
MOCK mGBA CLIENT (v3) -- full quest-lifecycle demo, no emulator, no model.

Impersonates exactly what hook v3 sends, maintains a fake bag, and APPLIES the
action replies (take_item/give_item) just like the Lua hook would. Running this
against `quest_bridge_server.py --echo` shows the entire quest loop end to end.

RUN (two terminals)
-------------------
  T1:  python quest_bridge_server.py --echo
  T2:  python mock_mgba_client.py
Also works against bridge_server.py (dialogue-only; replies have no actions).
"""

import json
import socket

HOST, PORT = "127.0.0.1", 8888

# fake game state, in hook-v3 wire format
BAG = {13: 1}                    # item_id -> qty  (1 Potion)
PLAYER = {"npc_id": 7, "map_group": 1, "map_num": 4,
          "original_line": "I love berries more than anything.",
          "player_level": 45, "party": ["Blaziken:45", "Mudkip:5"],
          "badges": 5, "game_clear": 0}


def ctx():
    return {**PLAYER, "bag": [f"{i}:{q}" for i, q in BAG.items() if q > 0]}


def apply_actions(acts):
    for tok in acts.split(";"):
        parts = tok.split(":")
        if len(parts) == 3 and parts[0] in ("give_item", "take_item"):
            iid, qty = int(parts[1]), int(parts[2])
            delta = qty if parts[0] == "give_item" else -qty
            BAG[iid] = max(0, BAG.get(iid, 0) + delta)
            print(f"    [applied] {parts[0]} {iid} x{qty}")
        else:
            print(f"    [ignored unknown action] {tok}")


def talk(sock, buf):
    sock.sendall((json.dumps(ctx()) + "\n").encode())
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("bridge closed")
        buf += chunk
    line, buf = buf.split(b"\n", 1)
    reply = line.decode()
    if "|" in reply:
        acts, dialogue = reply.split("|", 1)
        print(f"  NPC: {dialogue}")
        apply_actions(acts)
    else:
        print(f"  NPC: {reply}")
    return buf


def main():
    with socket.socket() as s:
        s.connect((HOST, PORT))
        print(f"[mock] connected to {HOST}:{PORT} | bag: {dict(BAG)}\n")
        buf = b""
        print("--- talk 1 (should offer a quest) ---")
        buf = talk(s, buf)
        print("\n--- talk 2, nothing gathered (should remind) ---")
        buf = talk(s, buf)
        print("\n--- player picks 2 Oran Berries (id 139) ---")
        BAG[139] = BAG.get(139, 0) + 2
        print(f"bag now: {dict(BAG)}")
        print("\n--- talk 3 (should complete: take berries, give reward) ---")
        buf = talk(s, buf)
        print(f"bag after actions: { {i: q for i, q in BAG.items() if q > 0} }")
        print("\n--- talk 4 (should be post-quest thanks) ---")
        buf = talk(s, buf)
    print("\n[mock] full quest lifecycle exercised.")


if __name__ == "__main__":
    main()
