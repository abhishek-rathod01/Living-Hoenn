"""
dialogue_bridge_server.py -- pinned-persona, DIALOGUE-ONLY bridge.

The quest engine is intentionally NOT used here. No take_item/give_item/
set_flag/await_choice actions are ever emitted -- every reply is bare
dialogue. This removes the REWARDED-state "Thanks again for the help!" trap
entirely, because there is no REWARDED state.

How personas are pinned:
  Reuses persona_engine.PersonaStore (npc_profiles.json, same card format and
  same key "map_group:map_num:npc_id"; the store has since gained a short
  rolling `_recent_lines` history per NPC, which does not touch the card). A persona is designed ONCE
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

Skip sentinel (signs/TVs, npc_id <= 0): the hook now recognizes SKIP_SENTINEL
as "don't touch gStringVar4/sTextPrinters at all" (mgba_hook.lua handleReply
+ the eager placeholder gate in sendContext) -- a real no-op, not a re-render.
Scoped to npc_id <= 0 only, since that's the one case the hook can gate the
eager "..." placeholder on synchronously (before any reply arrives) without
new protocol round-trips; see the hook's own comments for why.

Passthrough limitation for OTHER skip cases (stated, not hidden): non-person
mined objects (item balls, berry trees) and obtain-item fanfare boxes have
npc_id > 0, so the hook still writes its eager "..." placeholder before the
bridge's classification is known -- these still use _passthrough() (echo the
vanilla original_line back, may cost one extra A-press) rather than the true
no-op sentinel. Closing that gap needs the hook to pre-classify those cases
too (a static mined-object table), deliberately out of scope for this pass.

Backends: three real LLM backends (--backend ollama, the default, local via
the `ollama` package; --backend gemini, google-genai; --backend groq, the
groq SDK), plus --echo for canned no-LLM plumbing tests. All four share the
same persona/chatter call shape (make_llm/make_gemini/make_groq/
echo_persona+echo_chatter). Default model: llama3.2:3b for ollama,
gemini-3.5-flash for gemini, llama-3.3-70b-versatile for groq -- override
with --model.

Startup + failure handling: for the ollama backend only, serve() pings
Ollama's /api/tags before opening the listening socket and exits cleanly
with a clear message if Ollama isn't running (ollama_reachable()) -- gemini/
groq skip this, since there's no local process to check. A single failed
chatter() call at request time (backend down mid-session, cloud timeout)
falls back to "..." and logs the error instead of crashing the process or
leaking a raw exception string into the game as dialogue.

Connection model: single connection, handled synchronously -- srv.listen(1)
and one blocking accept()/recv() loop, matching mGBA's one Lua hook talking
to one bridge process. Not designed for concurrent clients.

RUN
---
  python dialogue_bridge_server.py --model llama3.2:3b
  python dialogue_bridge_server.py --backend gemini --model gemini-3.5-flash
  python dialogue_bridge_server.py --backend groq
  python dialogue_bridge_server.py --echo     # no LLM, canned reply, test plumbing
  python bridge/dialogue_bridge_server.py --model qwen3:8b --trace demo/trace.jsonl
                                              # opt-in event log for demo/dashboard.py
"""

import argparse
import ast
import json
import os
import re
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request

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

# True hook-level no-op sentinel (must match SKIP_SENTINEL in mgba_hook.lua
# exactly). Printable and pipe/newline-free so it survives the hook's
# "|"-delimited action-prefix parsing and shows up readably in console logs --
# unlike literal "...", which the persona-designer-failed fallback below still
# legitimately renders as a real (if neutral) line of dialogue.
SKIP_SENTINEL = "<<SKIP>>"


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


def _trainer_grounding(entry, gs=None):
    """Factual one-line party summary from the mined trainerbattle block.
    Species + level ONLY (no IVs or other raw stats). Multi-variant battles
    (the gender-x-starter rival) have no single true party, so no specific
    Pokemon may be named -- naming one would be wrong most of the time.

    Also states the trainer's real "already defeated" status when the hook
    reported one (gs["trainer_defeated"], 1/0 -- see mgba_hook.lua's
    trainerDefeated()/TRAINER_ID_BY_KEY, source-verified against
    HasTrainerBeenFought() in pokeemerald's src/battle_setup.c). Omitted
    (not guessed) when the hook couldn't determine it -- multi-variant
    battles and anything outside the pilot maps' single-trainer table."""
    tb = entry.get("trainerbattle")
    if not tb:
        return ""
    battles = tb if isinstance(tb, list) else [tb]
    defeated = gs.get("trainer_defeated") if gs is not None else None
    status = ""
    if defeated is not None:
        status = (" This trainer has ALREADY been defeated by the player -- "
                   "do not challenge them to a fresh battle or act as if the "
                   "fight hasn't happened yet; speak as someone they've "
                   "already lost to."
                   if defeated else
                   " This trainer has NOT been defeated yet -- they may "
                   "anticipate, threaten, or reference an upcoming challenge, "
                   "but never describe a battle that hasn't happened.")
    if len(battles) == 1 and battles[0].get("party"):
        mons = ", ".join(
            "{} (Lv{})".format(m["species"].replace("SPECIES_", "").replace("_", " "),
                               m["lvl"])
            for m in battles[0]["party"])
        return ("This NPC is a battle TRAINER. Their actual battle party is: "
                + mons + ". If their own Pokemon come up, describe ONLY these, "
                "accurately -- never invent Pokemon not on this list." + status)
    return ("This NPC is a battle TRAINER, but their exact party varies with "
            "events -- they may talk about battling, but must NOT name "
            "specific Pokemon on their own team." + status)


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
    'leave it alone' for npc_id > 0. (The hook writes every non-stale reply it
    receives; the true no-op SKIP_SENTINEL exists but is only used for
    npc_id <= 0, because for npc_id > 0 the hook has already written its eager
    placeholder before the bridge's reply arrives -- see the header.)"""
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
        # vanilla text; the merge script resolved them where available.
        # Only show the ONE that matches the player's real state when the
        # hook could determine it (gs["trainer_defeated"], 1/0) -- showing
        # both unconditionally is what let the model reference a battle
        # that already happened (or hasn't yet) inconsistently. Unknown
        # (None -- multi-variant battles, or NPCs outside the hook's
        # per-key table) keeps the old both-shown behavior, since we have
        # no real state to filter by.
        defeated = gs.get("trainer_defeated")
        tb = entry.get("trainerbattle")
        for b in (tb if isinstance(tb, list) else [tb] if tb else []):
            fields = ("intro_text_resolved", "defeat_text_resolved")
            if defeated == 1:
                fields = ("defeat_text_resolved",)
            elif defeated == 0:
                fields = ("intro_text_resolved",)
            for fld in fields:
                if b.get(fld):
                    lines.append(b[fld])
        if lines:
            shown = lines[:MAX_VANILLA_LINES]
            more = len(lines) - len(shown)
            block = "\n- ".join(shown) + (f"\n(...and {more} more)" if more > 0 else "")
            parts.append("Everything this NPC canonically says in the vanilla "
                         "game (ground your personality in these):\n- " + block)
        tg = _trainer_grounding(entry, gs)
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
    silently discarding it (persona_engine.get_or_create now also prints a
    '[persona] designer call failed / output rejected' line, but only this
    function shows the raw model output)."""
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


def _chatter_user_message(gs, persona_desc, recent_lines=None):
    """Shared by every backend's chatter() call. Appending the NPC's own
    last HISTORY_LEN lines (persona_engine.PersonaStore.recent_lines) as
    a concrete "don't repeat these" list is what CHATTER_SYSTEM's generic
    anti-repetition instruction was missing -- it had no actual data to
    avoid repeating, which is why the same quirk/phrasing kept recurring
    (observed live: Nurse Joy, 4 near-identical variants in a row)."""
    user = (build_grounding(gs) + f"\nYour role: {persona_desc}\n")
    if recent_lines:
        block = "\n- ".join(recent_lines)
        user += ("You (this NPC) recently said:\n- " + block +
                 "\nDo not repeat or closely paraphrase any of these -- say "
                 "something different this time, while staying in character.\n")
    return user + "Say your line now."


# Ollama generation settings, named once so the demo trace (--trace) reports
# exactly what make_llm() sends. Values are unchanged from the inline dicts
# they replace. num_ctx must stay identical across every request that shares
# the loaded model: Ollama reloads the model when num_ctx changes.
PERSONA_OPTIONS = {"temperature": 0.7, "num_ctx": 2048}
CHATTER_OPTIONS = {"temperature": 0.85, "num_ctx": 2048}

# Upper bound on one Ollama call. The ollama package's default is NO timeout,
# so a wedged Ollama (driver hiccup, GPU swap storm) used to freeze this
# single-threaded bridge forever: every later NPC got "..." until a manual
# restart. On timeout the call raises, and the existing fallbacks turn that
# into a neutral "..." for this one NPC; the next NPC gets a fresh attempt.
# Generous on purpose: a cold model load from disk can take 10-20 s, and the
# hook already stops waiting after ~10 s (WAIT_TIMEOUT), so this exists only
# to guarantee the bridge never hangs, not to race the hook.
LLM_TIMEOUT_S = 45.0


def make_llm(model, tracer=None, timeout=LLM_TIMEOUT_S):
    """Ollama backend. `tracer` is an optional DemoTrace (bridge started with
    --trace FILE). Every call is client.chat(model, think=False, options,
    messages) with or without a tracer -- tracing only observes. `timeout`
    bounds each call (seconds); see LLM_TIMEOUT_S."""
    import ollama
    client = ollama.Client(timeout=timeout)

    def _chat(stage, messages, options):
        if tracer is None:
            return client.chat(model=model, think=False, options=dict(options),
                               messages=messages)
        tracer.llm_start(stage, model, messages, options)
        t0 = time.perf_counter()
        try:
            resp = client.chat(model=model, think=False, options=dict(options),
                               messages=messages)
        except Exception as e:
            tracer.llm_error(stage, e, time.perf_counter() - t0)
            raise
        tracer.llm_done(stage, resp, time.perf_counter() - t0)
        return resp

    def persona_designer(gs):
        resp = _chat("persona",
                     [{"role": "system", "content": PERSONA_SYSTEM},
                      {"role": "user", "content": build_grounding(gs)}],
                     PERSONA_OPTIONS)
        return _finish_persona(resp.message.content)

    def chatter(gs, persona_desc, recent_lines=None):
        user = _chatter_user_message(gs, persona_desc, recent_lines)
        resp = _chat("chatter",
                     [{"role": "system", "content": CHATTER_SYSTEM},
                      {"role": "user", "content": user}],
                     CHATTER_OPTIONS)
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

    def chatter(gs, persona_desc, recent_lines=None):
        user = _chatter_user_message(gs, persona_desc, recent_lines)
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

    def chatter(gs, persona_desc, recent_lines=None):
        user = _chatter_user_message(gs, persona_desc, recent_lines)
        resp = client.chat.completions.create(
            model=model, temperature=0.85,
            messages=[{"role": "system", "content": CHATTER_SYSTEM},
                      {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content.strip()

    return persona_designer, chatter


def ollama_reachable(url="http://127.0.0.1:11434/api/tags", timeout=2.0):
    """Preflight check: is an Ollama server actually listening? Without this,
    the bridge used to accept the mGBA connection and only discover Ollama
    was never started on the FIRST chat() call, deep inside a request."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError):
        return False


def echo_persona(gs):
    return {"archetype": "gruff berry farmer",
            "temperament": "brusque but kind underneath",
            "quirk": "compares everything to soil quality",
            "greeting": "Hmph. Good soil today. You need something, trainer?"}


def echo_chatter(gs, persona_desc, recent_lines=None):
    return "[echo] Nice day for growing berries, wouldn't you say?"


def handle_request(gs, pstore, persona_designer, chatter, mined=None):
    """Testable core: one request dict in -> one bare-dialogue reply out.
    Never emits an action -- there is no action executor to consume one.
    `mined` overrides the module-level table for tests only."""
    npc_id = int(gs.get("npc_id", -1) or -1)
    if npc_id <= 0:
        # Signs/TVs (npc_id == 0) have no persistent identity to pin a
        # persona to. Return the true no-op sentinel -- the hook leaves
        # gStringVar4/sTextPrinters completely untouched for this, rather
        # than rendering a literal "..." over the vanilla text.
        return SKIP_SENTINEL
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
    recent = pstore.recent_lines(key)
    try:
        line = chatter(gs, persona_engine.describe(card), recent)
    except Exception as e:
        # A single failed backend call (Ollama unreachable mid-session, a
        # cloud backend timeout, etc.) must not surface a raw error string as
        # in-game dialogue, and must not take the connection/process down --
        # fall back to a neutral line, same as a designer failure above.
        print(f"[dialogue-bridge] chatter call failed for {key}: "
              f"{type(e).__name__}: {e}")
        return "..."
    line = " ".join(str(line).split())   # collapse newlines -- protocol is
                                          # newline-delimited, see bridge_server.py
    line = line or "..."
    pstore.record_line(key, line)
    return line


# ---------------- opt-in demo trace (--trace FILE) ---------------------------
class DemoTrace:
    """Event log for the open-day dashboard (demo/dashboard.py). Only exists
    when the bridge is started with --trace FILE; without that flag serve()
    never creates one and no code below runs.

    Appends one JSON object per line. Every method swallows its own errors:
    a locked or full file must never change a reply or take the bridge down.
    The game path does not depend on this class."""

    def __init__(self, path):
        self.path = path
        self.req = 0
        self.llm_visible = False   # True only for the ollama backend
        self.echo = False
        self._t0 = None
        self._chatter_ok = False

    def _emit(self, ev, **fields):
        try:
            rec = {"ev": ev, "ts": round(time.time(), 3), "req": self.req}
            rec.update(fields)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            print(f"[dialogue-bridge] trace write failed (ignored): "
                  f"{type(e).__name__}: {e}")

    def bridge_up(self, mode, port):
        self._emit("bridge_up", mode=mode, host=HOST, port=port)

    def mgba(self, connected, addr=None):
        self._emit("mgba", connected=bool(connected),
                   addr=str(addr) if addr else None)

    def request(self, gs):
        self.req += 1
        self._t0 = time.perf_counter()
        self._chatter_ok = False
        try:
            loc = MAPS.get((gs.get("map_group"), gs.get("map_num")),
                           f"map {gs.get('map_group')}-{gs.get('map_num')}")
            key = npc_key(gs)
        except Exception:
            loc, key = None, None
        self._emit("request", gs=gs, location=loc, npc_key=key)

    def llm_start(self, stage, model, messages, options):
        self._emit("llm_start", stage=stage, model=model, think=False,
                   messages=messages, options=dict(options))

    def llm_done(self, stage, resp, secs):
        def g(obj, name):
            try:
                return getattr(obj, name, None)
            except Exception:
                return None
        msg = g(resp, "message")
        if stage == "chatter":
            self._chatter_ok = True
        self._emit("llm_done", stage=stage, secs=round(secs, 3),
                   content=g(msg, "content"),
                   prompt_tokens=g(resp, "prompt_eval_count"),
                   output_tokens=g(resp, "eval_count"),
                   load_ns=g(resp, "load_duration"),
                   prompt_ns=g(resp, "prompt_eval_duration"),
                   eval_ns=g(resp, "eval_duration"),
                   total_ns=g(resp, "total_duration"))

    def llm_error(self, stage, err, secs):
        self._emit("llm_error", stage=stage, secs=round(secs, 3),
                   error=f"{type(err).__name__}: {err}")

    def reply(self, reply, error=None):
        secs = (time.perf_counter() - self._t0) if self._t0 is not None else None
        reply = str(reply)
        if error is not None:
            kind = "error"
        elif reply == SKIP_SENTINEL:
            kind = "skip"
        elif reply.startswith("[error]"):
            kind = "error"
        elif self.echo:
            kind = "echo"
        elif self._chatter_ok:
            kind = "llm"
        elif not self.llm_visible:
            kind = "reply"
        elif reply == "...":
            kind = "fallback"
        else:
            kind = "passthrough"
        self._emit("reply", reply=reply, kind=kind, error=error,
                   secs=round(secs, 3) if secs is not None else None)
        self._t0 = None


def handle_line(line, pstore, persona_designer, chatter, tracer=None):
    """One raw request line from the hook -> (reply, error_or_None).

    Always returns exactly one reply, because the hook matches replies to
    requests strictly in order (its pending FIFO). An exception never
    reaches the game as text: the old behaviour sent "[error] KeyError: ..."
    straight into the NPC's text box, since the hook renders whatever it gets.
    Now the player sees the same neutral "..." as any other failed call, and
    the real error goes to the console (with a traceback) and the trace."""
    try:
        gs = json.loads(line.decode("utf-8"))
        if not isinstance(gs, dict):
            raise ValueError(f"expected a JSON object, got {type(gs).__name__}")
    except (UnicodeDecodeError, ValueError) as e:
        print(f"[dialogue-bridge] unreadable request from the hook ({e}); "
              f"replying '...'")
        if tracer:
            tracer.request({})
        return "...", f"bad request: {e}"
    if tracer:
        tracer.request(gs)
    try:
        return handle_request(gs, pstore, persona_designer, chatter), None
    except Exception as e:
        print(f"[dialogue-bridge] request for {npc_key(gs)} failed, replying "
              f"'...':\n{traceback.format_exc()}")
        return "...", f"{type(e).__name__}: {e}"


# NOTE (2026-10-15 text sync): `log_path` is accepted but not used anywhere in
# this function -- this bridge has never written transcripts.jsonl (only
# quest_bridge_server.py does). Use `trace_path` (--trace) for an event log.
# Logged in REVIEW_QUEUE.md; left unchanged because this pass is text-only.
def serve(port, model, echo, backend, log_path="transcripts.jsonl",
          trace_path=None, llm_timeout=LLM_TIMEOUT_S):
    pstore = persona_engine.PersonaStore("npc_profiles.json")
    tracer = DemoTrace(trace_path) if trace_path else None
    if echo:
        persona_designer, chatter = echo_persona, echo_chatter
        if tracer:
            tracer.echo = True
    elif backend == "gemini":
        persona_designer, chatter = make_gemini(model)
    elif backend == "groq":
        persona_designer, chatter = make_groq(model)
    else:
        persona_designer, chatter = make_llm(model, tracer=tracer, timeout=llm_timeout)
        if tracer:
            tracer.llm_visible = True
        if not ollama_reachable():
            print("[dialogue-bridge] Ollama is not running -- start it with "
                  "`ollama serve`")
            sys.exit(1)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        # Windows. There, SO_REUSEADDR lets a SECOND process bind a port that
        # is already listening -- seen in live testing: a restart raced the
        # watchdog and two bridges both reported "listening on 8888", so the
        # hook could land on either. Exclusive use makes the second bind fail
        # (and exit 2, below) instead.
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, port))
    except OSError as e:
        print(f"[dialogue-bridge] can't listen on {HOST}:{port} ({e}). Another "
              f"bridge is probably still running -- STOP_DEMO.bat stops it.")
        srv.close()
        sys.exit(2)
    srv.listen(1)
    mode = "ECHO (no model)" if echo else f"{backend} ({model})"
    print(f"[dialogue-bridge] listening on {HOST}:{port} | mode: {mode} | "
          f"personas: npc_profiles.json | quest engine: DISABLED")
    if tracer:
        print(f"[dialogue-bridge] demo trace ON -> {trace_path}")
        tracer.bridge_up(mode, port)
    try:
        while True:
            conn, addr = srv.accept()
            print(f"[dialogue-bridge] mGBA connected from {addr}")
            if tracer:
                tracer.mgba(True, addr)
            buffer = b""
            try:
                with conn:
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            print("[dialogue-bridge] mGBA disconnected")
                            if tracer:
                                tracer.mgba(False)
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if not line.strip():
                                continue
                            reply, err = handle_line(line, pstore, persona_designer,
                                                     chatter, tracer)
                            conn.sendall(reply.encode("utf-8") + b"\n")
                            if tracer:
                                tracer.reply(reply, error=err)
                            print(f"[dialogue-bridge] -> {reply[:70]}")
            except (ConnectionError, OSError) as e:
                print(f"[dialogue-bridge] connection lost ({type(e).__name__}); waiting")
                if tracer:
                    tracer.mgba(False)
            except Exception as e:
                # Last line of defence: anything unexpected in this
                # connection's loop drops THIS connection, never the process.
                # The hook can reconnect (reload the script); a dead process
                # would need a restart as well.
                print(f"[dialogue-bridge] unexpected {type(e).__name__} in the "
                      f"connection loop -- dropping this connection, still "
                      f"listening:\n{traceback.format_exc()}")
                if tracer:
                    tracer.mgba(False)
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
    ap.add_argument("--trace", metavar="FILE", default=None,
                    help="opt-in: append prompt/settings/timing events for the "
                         "demo dashboard (demo/dashboard.py). Off by default.")
    ap.add_argument("--llm-timeout", type=float, default=LLM_TIMEOUT_S,
                    help=f"seconds before one Ollama call is abandoned "
                         f"(default {LLM_TIMEOUT_S:g})")
    args = ap.parse_args()
    # A print() must never be what kills the bridge: when stdout is a pipe or
    # a file on Windows it uses the ANSI codepage, and an emoji or kana in a
    # model reply raises UnicodeEncodeError. Replace unencodable characters.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    defaults = {"gemini": "gemini-3.5-flash", "groq": "llama-3.3-70b-versatile"}
    model = args.model or defaults.get(args.backend, "llama3.2:3b")
    serve(args.port, model, args.echo, args.backend, trace_path=args.trace,
          llm_timeout=args.llm_timeout)


if __name__ == "__main__":
    main()