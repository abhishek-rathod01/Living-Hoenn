"""
MOCK mGBA CLIENT  --  test the bridge WITHOUT the emulator.

This impersonates exactly what the Lua script will do: connect to the bridge,
send game-state JSON lines, and read the dialogue replies. Use it to prove the
Python + LLM half works end-to-end before you ever open mGBA. Debug one thing at
a time.

RUN (two terminals)
-------------------
  Terminal 1:  python bridge_server.py --echo      # or without --echo for real LLM
  Terminal 2:  python mock_mgba_client.py
"""

import json
import socket

HOST = "127.0.0.1"
PORT = 8888

FAKE_EVENTS = [
    {
        "npc_role": "a Rock-type trainer guarding a cave",
        "map": "Granite Cave entrance",
        "player_level": 25,
        "player_party": ["Blaziken", "Swampert"],
        "situation": "The trainer notices the player's strong team and wants to battle.",
    },
    {
        "npc_role": "an old fisherman",
        "map": "Route 118",
        "player_level": 30,
        "player_party": ["Gyarados", "Manectric", "Hariyama"],
        "situation": "The player interrupts him mid-cast.",
    },
]


def recv_line(sock: socket.socket, buffer: bytes) -> tuple[str, bytes]:
    """Read until one newline-terminated reply is available."""
    while b"\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("bridge closed the connection")
        buffer += chunk
    line, buffer = buffer.split(b"\n", 1)
    return line.decode("utf-8"), buffer


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        print(f"[mock] connected to bridge at {HOST}:{PORT}\n")
        buffer = b""
        for i, ctx in enumerate(FAKE_EVENTS, 1):
            # send one compact JSON line (this is exactly what Lua will send)
            s.sendall(json.dumps(ctx).encode("utf-8") + b"\n")
            print(f"--- Event {i}: {ctx['npc_role']} ---")
            reply, buffer = recv_line(s, buffer)
            print(f"NPC says: {reply}\n")
    print("[mock] done -- pipeline works end to end.")


if __name__ == "__main__":
    main()
