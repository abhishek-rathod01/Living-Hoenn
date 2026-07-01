"""
STEP 2  --  The bridge server (Python side of the socket).

mGBA connects to THIS as a client. The server receives game-state JSON from the
emulator, calls the local LLM, and sends the generated dialogue back.

PROTOCOL: newline-delimited JSON.
  - Each message is one JSON object followed by a single '\n'.
  - Request  (mGBA -> here):  {"npc_role": "...", "player_party": [...], ...}\n
  - Response (here -> mGBA):  the dialogue string, followed by '\n'.
"""

import argparse
import json
import socket

from step1_dialogue_ollama import generate_dialogue

HOST = "127.0.0.1"
PORT = 8888


def make_reply(raw_json: str, echo: bool) -> str:
    """Parse one request and produce the dialogue reply."""
    ctx = json.loads(raw_json)
    if echo:
        party = ", ".join(ctx.get("player_party", [])) or "your team"
        role = ctx.get("npc_role", "an NPC")
        return f"[echo] So, {role} here. That {party} looks tough. Let's battle!"
    return generate_dialogue(ctx)


def serve_one_client(conn: socket.socket, addr, echo: bool) -> None:
    """Handle a single connected emulator: read messages, reply to each."""
    print(f"[bridge] mGBA connected from {addr}")
    buffer = b""
    with conn:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                print("[bridge] mGBA disconnected")
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    reply = make_reply(line.decode("utf-8"), echo)
                except json.JSONDecodeError as e:
                    reply = f"[error] bad JSON from emulator: {e}"
                except Exception as e:
                    reply = f"[error] {type(e).__name__}: {e}"
                conn.sendall(reply.encode("utf-8") + b"\n")
                print(f"[bridge] replied: {reply[:60]}{'...' if len(reply) > 60 else ''}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--echo", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, args.port))
    srv.listen(1)
    mode = "ECHO (no model)" if args.echo else "Ollama"
    print(f"[bridge] listening on {HOST}:{args.port}  |  mode: {mode}")

    try:
        while True:
            conn, addr = srv.accept()
            serve_one_client(conn, addr, args.echo)
    except KeyboardInterrupt:
        print("\n[bridge] shutting down")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
