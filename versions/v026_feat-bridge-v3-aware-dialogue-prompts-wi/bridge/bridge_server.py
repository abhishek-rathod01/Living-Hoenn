"""
STEP 2  --  The bridge server (Python side of the socket).

mGBA connects to THIS as a client. The server receives game-state JSON from the
emulator, calls the local LLM, and sends the generated dialogue back.

PROTOCOL: newline-delimited JSON.
  - Each message is one JSON object followed by a single '\n'.
  - Request  (mGBA -> here):  {"npc_role": "...", "player_party": [...], ...}\n
  - Response (here -> mGBA):  the dialogue string, followed by '\n'.
  Newline framing works because compact JSON never contains a raw newline, so
  '\n' unambiguously marks the end of one message on the TCP stream.

WHY THIS DESIGN DOESN'T FREEZE THE EMULATOR:
  The slow part (the LLM call) happens HERE, in Python. mGBA fires its request
  and keeps running frames; its 'received' callback delivers our reply whenever
  it's ready. The emulator never blocks waiting on the model.

RUN
---
  # Test the plumbing with NO model needed:
  python bridge_server.py --echo

  # Real dialogue (needs Ollama running + `ollama pull llama3.2`):
  python bridge_server.py
"""

import argparse
import json
import socket

from step1_dialogue_ollama import generate_dialogue  # reuse the same core

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
    # A disconnect (mGBA closed, or the Lua script reloaded) makes recv/sendall
    # raise. Catch it so this session just ends and the server goes back to
    # accepting -- otherwise the whole bridge would crash on every script reload.
    try:
        with conn:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    print("[bridge] mGBA disconnected")
                    return
                buffer += chunk
                # A single recv may contain 0, 1, or several complete messages,
                # plus a partial one. Process every complete (newline-terminated) line.
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        reply = make_reply(line.decode("utf-8"), echo)
                    except json.JSONDecodeError as e:
                        reply = f"[error] bad JSON from emulator: {e}"
                    except Exception as e:  # keep the bridge alive on any model error
                        reply = f"[error] {type(e).__name__}: {e}"
                    # The protocol is newline-delimited, so each reply MUST be one
                    # line. LLMs happily emit newlines, which would be read as several
                    # messages on the emulator side (it splits on '\n') -- corrupting
                    # framing and clearing its wait-flag early. Collapse all
                    # whitespace to single spaces, and never send an empty frame
                    # (an empty line is skipped by the hook, hanging it forever).
                    reply = " ".join(reply.split()) or "..."
                    conn.sendall(reply.encode("utf-8") + b"\n")
                    print(f"[bridge] replied: {reply[:60]}{'...' if len(reply) > 60 else ''}")
    except (ConnectionError, OSError) as e:
        print(f"[bridge] connection lost ({type(e).__name__}); waiting for reconnect")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--echo", action="store_true",
                    help="skip the LLM and echo a canned line (test plumbing only)")
    ap.add_argument("--port", type=int, default=PORT)
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, args.port))
    srv.listen(1)
    mode = "ECHO (no model)" if args.echo else f"Ollama ({generate_dialogue.__module__})"
    print(f"[bridge] listening on {HOST}:{args.port}  |  mode: {mode}")
    print("[bridge] waiting for mGBA (or the mock client) to connect...")

    try:
        while True:
            conn, addr = srv.accept()
            serve_one_client(conn, addr, args.echo)  # one emulator at a time
    except KeyboardInterrupt:
        print("\n[bridge] shutting down")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
