"""
dialogue_bridge_server.py -- pinned-persona, DIALOGUE-ONLY bridge.

The quest engine is intentionally NOT used here. No take_item/give_item/
set_flag/await_choice actions are ever emitted -- every reply is bare
dialogue. This removes the REWARDED-state "Thanks again for the help!" trap
entirely, because there is no REWARDED state.

How personas are pinned:
  Reuses persona_engine.PersonaStore UNCHANGED (npc_profiles.json, same file
  format, same key: "map_group:map_num:npc_id"). A persona is designed ONCE
  per NPC from their vanilla original_line + location -- the same real signal
  the game itself gives that NPC -- and cached forever, same as before.

How dialogue stays fresh AND in-character:
  Every talk calls a small "chatter" LLM prompt, given the pinned persona
  description + live party/badges/location, with an explicit instruction to
  never contradict the pinned role and never invent quests/items (since none
  exist in this bridge). This is what stops a sailor from suddenly talking
  about Mew Tower.

Known limitation (stated, not hidden): there is no verified way in this
project yet to tell "regular NPC" apart from "battle trainer" purely from
game memory (gSpecialVar_LastTalked is an object's local id, not a gTrainers
index), so trainer-party-awareness is NOT implemented here. Function is
inferred only from the NPC's own vanilla line + location.

RUN
---
  python dialogue_bridge_server.py --model llama3.2:3b
  python dialogue_bridge_server.py --model qwen2.5:7b-instruct-q4_0
  python dialogue_bridge_server.py --echo     # no LLM, canned reply, test plumbing
"""

import argparse
import json
import socket

import persona_engine
from world_tables import MAPS

HOST, PORT = "127.0.0.1", 8888

PERSONA_SYSTEM = """You invent a personality for ONE Pokemon Emerald NPC.
Reply with ONLY a JSON object, no prose, no fences, exactly:
{"archetype":"...","temperament":"...","quirk":"...","greeting":"..."}
Rules:
- archetype is this NPC's FUNCTION/JOB, inferred ONLY from their original
  in-game line and where they stand (e.g. "harbor sailor offering island
  voyages", "gym trainer", "berry farmer", "tower guard"). Never invent a
  role their own line and location don't support.
- archetype<=40 chars, temperament<=60, quirk<=80.
- greeting<=120 chars: a full spoken line in character, said once to a new
  arrival."""

CHATTER_SYSTEM = """You write ONE line of in-character dialogue for a Pokemon
Emerald NPC who is just talking -- not offering a quest, item, or trade.
Rules:
- Stay STRICTLY inside the role you are given. Never drift into an unrelated
  topic (a sailor talks about the sea, tickets, islands; a gym trainer talks
  about battling; a berry farmer talks about berries and soil).
- You may react to the player's Pokemon party if something about it is
  genuinely interesting to comment on, but you don't have to force it.
- NEVER offer, complete, or reference any quest, item, trade, or reward --
  no such system exists here.
- Output ONE spoken line, under 35 words, no quotation marks, no narration,
  no asterisks."""


def npc_key(gs):
    return "{}:{}:{}".format(gs.get("map_group", -1), gs.get("map_num", -1),
                             gs.get("npc_id", -1))


def _gs_summary(gs):
    loc = MAPS.get((gs.get("map_group"), gs.get("map_num")),
                   f"map {gs.get('map_group')}-{gs.get('map_num')}")
    return (f"NPC's original game line: {gs.get('original_line', '')!r}\n"
            f"Location: {loc}\n"
            f"Player's badges: {gs.get('badges', 0)}\n"
            f"Player's party: {gs.get('party')}")


def make_llm(model):
    import ollama
    import ast
    import re

    def _json_of(text):
        """Extract a dict from LLM output, tolerating the ways small models
        commonly deviate from strict 'reply with ONLY JSON':
          - markdown code fences around the object
          - prose before/after the object
          - single-quoted Python-dict style instead of double-quoted JSON
        Raises with a clear message (not swallowed) if nothing usable is found."""
        raw = text.strip()
        # strip ```json ... ``` or ``` ... ``` fences if present
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
        if fenced:
            raw = fenced.group(1).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError(f"no JSON object found in model output: {raw[:200]!r}")
        span = raw[start:end + 1]
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            pass
        try:
            # small instruct models frequently emit single-quoted Python-dict
            # syntax instead of strict JSON; ast.literal_eval parses that
            # safely (it's a literal parser, not eval -- no code execution)
            val = ast.literal_eval(span)
            if isinstance(val, dict):
                return val
        except (ValueError, SyntaxError):
            pass
        raise ValueError(f"model output wasn't valid JSON or a Python dict literal: {span[:200]!r}")

    def _clip_persona_fields(card):
        """Truncate over-length fields instead of rejecting the whole persona
        for it -- a slightly chatty model shouldn't lose a valid persona over
        a length cap that's cosmetic, not a safety boundary."""
        caps = {"archetype": 40, "temperament": 60, "quirk": 80, "greeting": 120}
        out = {}
        for k, cap in caps.items():
            v = card.get(k)
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()[:cap]
        return out

    def persona_designer(gs):
        resp = ollama.chat(model=model, options={"temperature": 0.7},
                           messages=[{"role": "system", "content": PERSONA_SYSTEM},
                                     {"role": "user", "content": _gs_summary(gs)}])
        text = resp.message.content
        try:
            card = _json_of(text)
        except ValueError as e:
            print(f"[dialogue-bridge] persona designer produced unusable output: {e}")
            raise
        card = _clip_persona_fields(card)
        missing = [k for k in ("archetype", "temperament", "quirk", "greeting") if k not in card]
        if missing:
            print(f"[dialogue-bridge] persona designer output missing field(s) {missing}, "
                 f"raw was: {text[:200]!r}")
            raise ValueError(f"missing required field(s): {missing}")
        return card

    def chatter(gs, persona_desc):
        user = (_gs_summary(gs) + f"\nYour role: {persona_desc}\n"
                "Say your line now.")
        resp = ollama.chat(model=model, options={"temperature": 0.85},
                           messages=[{"role": "system", "content": CHATTER_SYSTEM},
                                     {"role": "user", "content": user}])
        return resp.message.content.strip()

    return persona_designer, chatter


def echo_persona(gs):
    return {"archetype": "gruff berry farmer",
            "temperament": "brusque but kind underneath",
            "quirk": "compares everything to soil quality",
            "greeting": "Hmph. Good soil today. You need something, trainer?"}


def echo_chatter(gs, persona_desc):
    return "[echo] Nice day for growing berries, wouldn't you say?"


def handle_request(gs, pstore, persona_designer, chatter):
    """Testable core: one request dict in -> one bare-dialogue reply out.
    Never emits an action -- there is no action executor to consume one."""
    npc_id = int(gs.get("npc_id", -1) or -1)
    if npc_id <= 0:
        # Signs/TVs (npc_id == 0) have no persistent identity to pin a
        # persona to; just say nothing meaningful rather than inventing one.
        return "..."
    key = npc_key(gs)
    card = pstore.get_or_create(key, persona_designer, gs)
    if not card:
        # Designer failed/invalid: fall back to a neutral, harmless line
        # rather than silence or a crash.
        return "..."
    line = chatter(gs, persona_engine.describe(card))
    line = " ".join(str(line).split())   # collapse newlines -- protocol is
                                          # newline-delimited, see bridge_server.py
    return line or "..."


def serve(port, model, echo, log_path="transcripts.jsonl"):
    pstore = persona_engine.PersonaStore("npc_profiles.json")
    if echo:
        persona_designer, chatter = echo_persona, echo_chatter
    else:
        persona_designer, chatter = make_llm(model)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(1)
    mode = "ECHO (no model)" if echo else f"Ollama ({model})"
    print(f"[dialogue-bridge] listening on {HOST}:{port} | mode: {mode} | "
          f"personas: npc_profiles.json | quest engine: DISABLED")
    try:
        while True:
            conn, addr = srv.accept()
            print(f"[dialogue-bridge] mGBA connected from {addr}")
            buffer = b""
            try:
                with conn:
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            print("[dialogue-bridge] mGBA disconnected")
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if not line.strip():
                                continue
                            try:
                                gs = json.loads(line.decode("utf-8"))
                                reply = handle_request(gs, pstore, persona_designer, chatter)
                            except json.JSONDecodeError as e:
                                reply = f"[error] bad JSON: {e}"
                            except Exception as e:
                                reply = f"[error] {type(e).__name__}: {e}"
                            conn.sendall(reply.encode("utf-8") + b"\n")
                            print(f"[dialogue-bridge] -> {reply[:70]}")
            except (ConnectionError, OSError) as e:
                print(f"[dialogue-bridge] connection lost ({type(e).__name__}); waiting")
    except KeyboardInterrupt:
        print("\n[dialogue-bridge] shutting down")
    finally:
        srv.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--echo", action="store_true", help="canned replies, no LLM")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--model", default="llama3.2:3b")
    args = ap.parse_args()
    serve(args.port, args.model, args.echo)


if __name__ == "__main__":
    main()
