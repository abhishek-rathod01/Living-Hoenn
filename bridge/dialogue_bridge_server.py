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

Mined-table grounding (pilot, 5 maps):
  extraction/npc_dialogue_table.json (decomp-mined, source-verified) is
  loaded once at startup. For the 103 NPCs it covers -- Slateport City,
  Fortree City, Lilycove City, Route 110, Slateport PC 1F -- prompts get
  richer grounding: the NPC's full set of vanilla lines, real trainer party
  (species+level, from trainer_parties.h -- the old "no verified way to tell
  trainer from NPC" limitation is solved at the SOURCE level for mined maps),
  gift awareness, and map weather/type. Every NPC on any OTHER map behaves
  exactly as before (single original_line grounding).

Passthrough limitation (stated, not hidden): the Lua hook has no
"don't inject" sentinel -- every non-stale reply is written to gStringVar4
(handleReply -> writeToBuffer, unconditional). So "skip" for non-person
objects and obtain-item boxes is implemented as echoing the vanilla
original_line back unchanged: visually a re-render of the same text (may
cost one extra A-press, same as any injected line). A true no-op needs a
one-line hook change, deliberately out of scope for this session.

RUN
---
  python dialogue_bridge_server.py --model llama3.2:3b
  python dialogue_bridge_server.py --model qwen2.5:7b-instruct-q4_0
  python dialogue_bridge_server.py --echo     # no LLM, canned reply, test plumbing
"""

import argparse
import ast
import json
import os
import re
import socket

import persona_engine
from world_tables import MAPS

HOST, PORT = "127.0.0.1", 8888

# Ported verbatim from broadcast.LEGENDARIES (the world-reactions/awe list,
# ARCHITECTURE.md III.5). Copied, not imported: this bridge deliberately has
# no quest_engine/advisor/broadcast imports (see handover doc). A test in
# run_all_tests.py asserts the two sets stay identical.
LEGENDARIES = {"Kyogre", "Groudon", "Rayquaza", "Latias", "Latios", "Regirock",
               "Regice", "Registeel", "Mew", "Mewtwo", "Lugia", "Ho-oh",
               "Celebi", "Articuno", "Zapdos", "Moltres", "Raikou", "Entei",
               "Suicune", "Jirachi", "Deoxys"}


# ---------------- mined NPC table (pilot: 5 maps) -----------------------------
def load_mined_table():
    """extraction/npc_dialogue_table.json, generated from the pokeemerald
    decomp (see extraction/COVERAGE_REPORT.md). Missing file is not an
    error -- the bridge then runs entirely on the fallback grounding path,
    exactly as it did before this table existed."""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(os.path.dirname(here), "extraction", "npc_dialogue_table.json"),
                 os.path.join(here, "extraction", "npc_dialogue_table.json")):
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                table = json.load(f)
            print("[dialogue-bridge] mined NPC table: {} NPCs across {} maps".format(
                len(table.get("npcs", {})), len(table.get("_maps", {}))))
            return table
    print("[dialogue-bridge] no mined NPC table found -- fallback grounding only")
    return {"npcs": {}, "_maps": {}}


MINED = load_mined_table()

PERSONA_SYSTEM = """You invent a personality for ONE Pokemon Emerald NPC.
Reply with ONLY a JSON object, no prose, no fences, exactly:
{"archetype":"...","temperament":"...","quirk":"...","greeting":"..."}
Rules:
- archetype is this NPC's FUNCTION/JOB, inferred ONLY from their original
  in-game line and where they stand (e.g. "harbor sailor offering island
  voyages", "gym trainer", "berry farmer", "tower guard"). Never invent a
  role their own line and location don't support.
- If the original line or location strongly implies a WELL-KNOWN Pokemon
  service role -- a Nurse Joy healing Pokemon at a Pokemon Center, a Poke
  Mart/shop clerk, Officer Jenny, a Move Tutor/Deleter, a Day Care attendant,
  a PC/storage clerk -- you MUST set archetype to that exact real role, not
  a generic or invented substitute. These roles carry real constraints: a
  healer NEVER challenges the player to battle or asks for a trade; a shop
  clerk talks about goods and prices, not adventuring; a Day Care attendant
  talks about breeding/leaving Pokemon, nothing else.
- archetype<=40 chars, temperament<=60, quirk<=80 (quirk is a SUBTLE flavor
  trait to surface occasionally, not a catchphrase to repeat every line).
- greeting<=120 chars: a full spoken line in character, said once to a new
  arrival."""

CHATTER_SYSTEM = """You write ONE line of in-character dialogue for a Pokemon
Emerald NPC who is just talking -- not offering a quest, item, or trade.
Rules:
- Only the NPC speaks. Pokemon do not talk, comment, or have dialogue of
  their own -- if you mention the player's Pokemon, the NPC is the one
  reacting to them (admiring, startled by, curious about), never voicing
  lines for the Pokemon itself.
- Stay STRICTLY inside the role you are given. Never drift into an unrelated
  topic (a sailor talks about the sea, tickets, islands; a gym trainer talks
  about battling; a berry farmer talks about berries and soil).
- If your role is a real Pokemon SERVICE job (Nurse Joy, a shop clerk,
  Officer Jenny, Day Care attendant, PC clerk, Move Tutor/Deleter), you are
  bound by what that job actually does in the games. A healer NEVER
  challenges the player to battle or proposes a trade. A shop clerk never
  wanders off-topic into adventuring. Do not contradict the real function of
  a real Pokemon job, even for variety.
- Stay fully IN-WORLD. Never reference anything that would break the 4th
  wall -- no "notes", "records", "data", "clipboard", "according to my
  files", "algorithm", or anything sounding like an outside observer,
  narrator, or system rather than a person standing in this world.
- Your quirk is a subtle trait to surface OCCASIONALLY, not a catchphrase.
  Do not repeat the same phrasing, tic, or sentence structure you (or this
  NPC) used recently -- vary the subject and wording each time even while
  staying in character.
- You may react to the player's Pokemon party if something about it is
  genuinely interesting to comment on, but you don't have to force it.
- NEVER offer, request, complete, or reference any quest, item, trade, gift,
  or reward, even vaguely or hypothetically -- there is no item or quest
  system active, so any exchange you describe would be pure fiction the
  player can't actually act on. Talk about your role, your surroundings, or
  the player's Pokemon instead.
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


# ---------------- renown tier (applies to EVERY NPC, mined or not) ------------
def _party_mons(gs):
    """[(name, level)] from the wire's 'Name:level' strings -- same split
    convention build_world_notes/broadcast already use."""
    out = []
    for p in gs.get("party") or []:
        if ":" in p:
            n, l = p.split(":")[0], p.split(":")[1]
            if l.lstrip("-").isdigit():
                out.append((n, int(l)))
    return out


def renown_tier(gs):
    """rookie / experienced / feared, from badges + game_clear + max party
    level + legendary-in-party. 'Legendary >= Lv50' and the champion flag are
    the same two awe triggers build_world_notes uses (ARCHITECTURE.md III.5);
    the badge/level thresholds grade the space below them."""
    mons = _party_mons(gs)
    max_lvl = max([l for _, l in mons], default=0)
    if gs.get("game_clear") or any(n in LEGENDARIES and l >= 50 for n, l in mons):
        return "feared"
    if int(gs.get("badges", 0) or 0) >= 5 or max_lvl >= 40:
        return "experienced"
    return "rookie"


RENOWN_LINES = {
    "rookie": ("Treat this trainer as a ROOKIE just starting out -- friendly, "
               "maybe encouraging, not intimidated in the slightest."),
    "experienced": ("Treat this trainer with WARY RESPECT -- their badges and "
                    "team mark them as genuinely experienced."),
    "feared": ("Treat this trainer with VISIBLE AWE, fear, or reverence -- "
               "their reputation precedes them."),
}


# ---------------- mined-entry grounding helpers --------------------------------
def _mined_entry(gs, mined=None):
    mined = MINED if mined is None else mined
    return (mined.get("npcs") or {}).get(npc_key(gs))


def _trainer_grounding(entry):
    """Factual one-line party summary from the mined trainerbattle block.
    Species + level ONLY (no IVs or other raw stats). Multi-variant battles
    (the gender-x-starter rival) have no single true party, so no specific
    Pokemon may be named -- naming one would be wrong most of the time."""
    tb = entry.get("trainerbattle")
    if not tb:
        return ""
    battles = tb if isinstance(tb, list) else [tb]
    if len(battles) == 1 and battles[0].get("party"):
        mons = ", ".join(
            "{} (Lv{})".format(m["species"].replace("SPECIES_", "").replace("_", " "),
                               m["lvl"])
            for m in battles[0]["party"])
        return ("This NPC is a battle TRAINER. Their actual battle party is: "
                + mons + ". If their own Pokemon come up, describe ONLY these, "
                "accurately -- never invent Pokemon not on this list.")
    return ("This NPC is a battle TRAINER, but their exact party varies with "
            "events -- they may talk about battling, but must NOT name "
            "specific Pokemon on their own team.")


_OBTAIN_RE = re.compile(r"\b(obtained|received|found)\b", re.IGNORECASE)


def _is_obtain_box(gs, entry):
    """True when the current message box is the item-award fanfare of a
    mined gift-giver: the mined giveitem data is the allowlist (no guessing
    about WHO gives items), the box text decides WHICH of that NPC's boxes
    this is -- by the gifted item's display name when the item is fixed, or
    by the obtain-verb formula when the mined item is dynamic (random berry,
    VAR_0x8008 exchange)."""
    gi = entry.get("giveitem")
    if not gi:
        return False
    line = str(gs.get("original_line") or "")
    item = str(gi.get("item", "") if isinstance(gi, dict) else "")
    if item.startswith("ITEM_"):
        display = item[len("ITEM_"):].replace("_", " ")
        if display and display in line.upper():
            return True
    return bool(_OBTAIN_RE.search(line))


def _passthrough(gs):
    """Echo the vanilla text back unchanged -- the closest available
    'leave it alone' (see the header: the hook writes every non-stale reply,
    there is no don't-inject sentinel, and the hook is out of scope here)."""
    line = " ".join(str(gs.get("original_line") or "").split())
    return line or "..."


_AMBIENT_WEATHER = {"WEATHER_SUNNY": "sunny", "WEATHER_RAIN": "raining",
                    "WEATHER_ASH": "falling ash", "WEATHER_SANDSTORM": "sandstorm",
                    "WEATHER_FOG_HORIZONTAL": "foggy", "WEATHER_NONE": None}
_AMBIENT_TYPE = {"MAP_TYPE_CITY": "a city", "MAP_TYPE_TOWN": "a town",
                 "MAP_TYPE_ROUTE": "a route between towns",
                 "MAP_TYPE_INDOOR": "indoors", "MAP_TYPE_UNDERWATER": "underwater",
                 "MAP_TYPE_UNDERGROUND": "underground"}

MAX_VANILLA_LINES = 5   # keep prompts small for 3b/7b local models


def build_grounding(gs, mined=None):
    """The user-message grounding for BOTH the persona designer and the
    chatter call. For NPCs not in the mined table this is exactly the old
    _gs_summary plus the renown instruction; for mined NPCs it adds their
    full vanilla dialogue, trainer party, and ambient setting."""
    parts = [_gs_summary(gs)]
    entry = _mined_entry(gs, mined)
    if entry:
        lines = [r["text"] for r in entry.get("dialogue", []) if r.get("text")]
        # a trainer's battle intro/defeat lines are their most characterful
        # vanilla text; the merge script resolved them where available
        tb = entry.get("trainerbattle")
        for b in (tb if isinstance(tb, list) else [tb] if tb else []):
            for fld in ("intro_text_resolved", "defeat_text_resolved"):
                if b.get(fld):
                    lines.append(b[fld])
        if lines:
            shown = lines[:MAX_VANILLA_LINES]
            more = len(lines) - len(shown)
            block = "\n- ".join(shown) + (f"\n(...and {more} more)" if more > 0 else "")
            parts.append("Everything this NPC canonically says in the vanilla "
                         "game (ground your personality in these):\n- " + block)
        tg = _trainer_grounding(entry)
        if tg:
            parts.append(tg)
        mined_maps = (mined if mined is not None else MINED).get("_maps") or {}
        meta = mined_maps.get("{}:{}".format(gs.get("map_group"), gs.get("map_num")), {})
        ambient = [x for x in (_AMBIENT_TYPE.get(meta.get("map_type")),
                               _AMBIENT_WEATHER.get(meta.get("weather"))) if x]
        if ambient:
            parts.append("Setting: " + ", ".join(ambient) + ".")
    parts.append(RENOWN_LINES[renown_tier(gs)])
    return "\n".join(parts)


def _json_of(text):
    """Extract a dict from LLM output, tolerating the ways small models
    commonly deviate from strict 'reply with ONLY JSON':
      - markdown code fences around the object
      - prose before/after the object
      - single-quoted Python-dict style instead of double-quoted JSON
    Raises with a clear message (not swallowed) if nothing usable is found."""
    raw = text.strip()
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


def _finish_persona(text):
    """Shared by every backend: parse + clip + validate required fields are
    present, printing the raw output when something's wrong instead of
    silently discarding it (persona_engine's own get_or_create swallows the
    reason, so this is the only place that reason is visible)."""
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


def make_llm(model):
    import ollama

    def persona_designer(gs):
        resp = ollama.chat(model=model, think=False,
                           options={"temperature": 0.7, "num_ctx": 2048},
                           messages=[{"role": "system", "content": PERSONA_SYSTEM},
                                     {"role": "user", "content": build_grounding(gs)}])
        return _finish_persona(resp.message.content)

    def chatter(gs, persona_desc):
        user = (build_grounding(gs) + f"\nYour role: {persona_desc}\n"
                "Say your line now.")
        resp = ollama.chat(model=model, think=False,
                           options={"temperature": 0.85, "num_ctx": 2048},
                           messages=[{"role": "system", "content": CHATTER_SYSTEM},
                                     {"role": "user", "content": user}])
        return resp.message.content.strip()

    return persona_designer, chatter


def make_gemini(model):
    """Google Gemini backend (google-genai SDK, current as of the GA release).
    Needs GEMINI_API_KEY set as an environment variable (same pattern as your
    existing OLLAMA_KEEP_ALIVE setup) -- get a free key at
    https://aistudio.google.com/app/apikey. genai.Client() picks the key up
    from the environment automatically; no key is ever typed into code here.

    Free tier has real rate limits (requests/minute and/or per day) that
    change over time -- check current numbers in AI Studio if you start
    seeing errors; this code doesn't hardcode or guess at a specific limit."""
    from google import genai
    from google.genai import types

    client = genai.Client()

    def persona_designer(gs):
        resp = client.models.generate_content(
            model=model,
            contents=build_grounding(gs),
            config=types.GenerateContentConfig(
                system_instruction=PERSONA_SYSTEM, temperature=0.7),
        )
        return _finish_persona(resp.text)

    def chatter(gs, persona_desc):
        user = (build_grounding(gs) + f"\nYour role: {persona_desc}\n"
                "Say your line now.")
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=CHATTER_SYSTEM, temperature=0.85),
        )
        return resp.text.strip()

    return persona_designer, chatter


def make_groq(model):
    """Groq backend (groq python SDK, OpenAI-compatible chat completions --
    same messages=[{role, content}] shape as the Ollama backend above).
    Needs GROQ_API_KEY set as an environment variable -- get a free key at
    https://console.groq.com/keys. Groq() picks the key up from the
    environment automatically, same pattern as the other backends.

    Groq's selling point here is inference speed (custom hardware) and, as a
    second cloud option, redundancy: if Gemini's free tier is temporarily
    overloaded (503 UNAVAILABLE), Groq is a completely independent service
    that won't share that outage."""
    from groq import Groq

    client = Groq()

    def persona_designer(gs):
        resp = client.chat.completions.create(
            model=model, temperature=0.7,
            messages=[{"role": "system", "content": PERSONA_SYSTEM},
                      {"role": "user", "content": build_grounding(gs)}],
        )
        return _finish_persona(resp.choices[0].message.content)

    def chatter(gs, persona_desc):
        user = (build_grounding(gs) + f"\nYour role: {persona_desc}\n"
                "Say your line now.")
        resp = client.chat.completions.create(
            model=model, temperature=0.85,
            messages=[{"role": "system", "content": CHATTER_SYSTEM},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content.strip()

    return persona_designer, chatter


def echo_persona(gs):
    return {"archetype": "gruff berry farmer",
            "temperament": "brusque but kind underneath",
            "quirk": "compares everything to soil quality",
            "greeting": "Hmph. Good soil today. You need something, trainer?"}


def echo_chatter(gs, persona_desc):
    return "[echo] Nice day for growing berries, wouldn't you say?"


def handle_request(gs, pstore, persona_designer, chatter, mined=None):
    """Testable core: one request dict in -> one bare-dialogue reply out.
    Never emits an action -- there is no action executor to consume one.
    `mined` overrides the module-level table for tests only."""
    npc_id = int(gs.get("npc_id", -1) or -1)
    if npc_id <= 0:
        # Signs/TVs (npc_id == 0) have no persistent identity to pin a
        # persona to; just say nothing meaningful rather than inventing one.
        return "..."
    entry = _mined_entry(gs, mined)
    if entry is not None:
        # Object-type gate (mined maps only): item balls, berry trees, the
        # invisible Kecleon etc. are not people -- generating a persona for
        # them is nonsense. Strictly scoped to keys present in the mined
        # table; NPCs on unmined maps never reach this branch.
        if not str(entry.get("object_type", "")).startswith("person"):
            return _passthrough(gs)
        # Gift fanfare gate: never overwrite an obtain-item box with fiction.
        if _is_obtain_box(gs, entry):
            return _passthrough(gs)
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


def serve(port, model, echo, backend, log_path="transcripts.jsonl"):
    pstore = persona_engine.PersonaStore("npc_profiles.json")
    if echo:
        persona_designer, chatter = echo_persona, echo_chatter
    elif backend == "gemini":
        persona_designer, chatter = make_gemini(model)
    elif backend == "groq":
        persona_designer, chatter = make_groq(model)
    else:
        persona_designer, chatter = make_llm(model)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(1)
    mode = "ECHO (no model)" if echo else f"{backend} ({model})"
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
    ap.add_argument("--backend", choices=("ollama", "gemini", "groq"), default="ollama")
    ap.add_argument("--model", default=None,
                    help="defaults to llama3.2:3b for ollama, gemini-3.5-flash for gemini, "
                        "llama-3.3-70b-versatile for groq")
    args = ap.parse_args()
    defaults = {"gemini": "gemini-3.5-flash", "groq": "llama-3.3-70b-versatile"}
    model = args.model or defaults.get(args.backend, "llama3.2:3b")
    serve(args.port, model, args.echo, args.backend)


if __name__ == "__main__":
    main()