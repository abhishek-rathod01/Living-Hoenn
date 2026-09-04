"""
run_all_tests.py -- one command to verify the whole project, no emulator, no LLM.

    python run_all_tests.py

Run this FIRST on any new machine. If everything passes, the entire Python
layer (quest engine, personas, bridge, wire protocol) is proven working, and
the Lua files are syntax-checked if `lupa` is installed (pip install lupa --
optional). Exit code 0 = all good.
"""

import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
BRIDGE = os.path.join(HERE, "bridge")
LUA = os.path.join(HERE, "lua")
# Work from a bare clone (bridge/, lua/ as real subfolders) OR from a flat
# working copy (files already copied to HERE, per the old HOME_SETUP.md
# instructions) -- both are supported, so nobody has to remember a setup step.
for d in (HERE, BRIDGE, LUA):
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)


def _find(name):
    """Locate a file whether it's flat at HERE or in its real bridge/lua subfolder."""
    for d in (HERE, BRIDGE, LUA):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return name  # let the caller's own error message explain the miss


@contextlib.contextmanager
def _in_lua_dir():
    """Run a block with CWD set to lua/, then restore it unconditionally.

    mgba_hook.lua's loadTable() resolves species_names/charmap/trainer_flags
    by path. Under lupa the hook is executed as an in-memory string, so it has
    no file location of its own to introspect (debug.getinfo would report the
    chunk, not a path) -- the only lever available to the test is the CWD the
    hook's own dofile() calls resolve against. Without this, all three tables
    load as {} and every test that exercises encoding or species names is
    silently asserting against empty data.
    """
    prev = os.getcwd()
    os.chdir(LUA)
    try:
        yield
    finally:
        os.chdir(prev)


PASS, FAIL, SKIP = [], [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL.append((name, e))
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------- items table
def t_items():
    from items_table import ITEMS, REWARDABLE
    assert len(ITEMS) == 377
    assert ITEMS[1] == "Master Ball" and ITEMS[13] == "Potion" and ITEMS[139] == "Oran Berry"
    assert 1 not in REWARDABLE and 13 in REWARDABLE and 139 in REWARDABLE


# --------------------------------------------------------------- world tables
def t_world():
    from world_tables import MAPS, TRAINER_CLASSES
    assert len(MAPS) == 482 and len(TRAINER_CLASSES) == 66
    assert MAPS[(0, 9)] == "Littleroot Town" and MAPS[(24, 7)] == "Granite Cave"
    assert TRAINER_CLASSES[0x33] == "Bug Catcher" and TRAINER_CLASSES[0x20] == "Leader"
    from quest_bridge_server import _gs_summary
    assert "Littleroot Town" in _gs_summary({"map_group": 0, "map_num": 9, "party": []})


# -------------------------------------------------- NPC dialogue table (pilot)
def t_npc_table():
    import re
    path = os.path.join(HERE, "extraction", "npc_dialogue_table.json")
    with open(path, encoding="utf-8") as f:
        table = json.load(f)
    from world_tables import MAPS
    key_re = re.compile(r"^(\d+):(\d+):(\d+)$")
    assert len(table["_maps"]) == 5 and len(table["npcs"]) == 103
    for map_id, meta in table["_maps"].items():
        g, n = map(int, map_id.split(":"))
        assert (g, n) in MAPS, f"map {map_id} not in world_tables.MAPS"
        assert meta["weather"].startswith("WEATHER_")
        assert meta["map_type"].startswith("MAP_TYPE_")
    for key, entry in table["npcs"].items():
        m = key_re.match(key)
        assert m, f"bad key {key}"
        assert f"{m.group(1)}:{m.group(2)}" in table["_maps"], f"orphan key {key}"
        assert entry.get("graphics_id", "").startswith("OBJ_EVENT_GFX_"), key
        assert "script" in entry and "object_type" in entry, key
        for row in entry.get("dialogue", []):
            assert row.get("label"), f"{key}: dialogue row without label"
            assert row.get("text"), f"{key}: unresolved text for {row.get('label')}"
        tb = entry.get("trainerbattle")
        for t in (tb if isinstance(tb, list) else [tb] if tb else []):
            names = [t["trainer"]] if "trainer" in t else t["trainers"]
            assert names and all(x.startswith("TRAINER_") for x in names), key
            for mon in t.get("party", []):
                assert mon["species"].startswith("SPECIES_") and mon["lvl"] > 0, key
    # spot values hand-verified against pokeemerald source this session
    assert len(table["npcs"]["0:4:3"]["dialogue"]) == 2          # Fortree Woman
    assert table["npcs"]["0:25:8"]["trainerbattle"]["trainer"] == "TRAINER_JASMINE"
    assert len(table["npcs"]["0:25:8"]["trainerbattle"]["party"]) == 3
    assert "POWDER_JAR" in table["npcs"]["0:1:34"]["giveitem"]["item"]
    # shared scripts must be flagged (distinct persona keys needed)
    assert table["_shared_scripts"]["BerryTreeScript"] == ["0:25:16", "0:25:17", "0:25:18"]


# ------------------------------------- mined-table grounding (dialogue bridge)
def t_mined_grounding():
    import dialogue_bridge_server as d
    import broadcast
    import persona_engine
    # the ported legendary set must never drift from the awe list it came from
    assert d.LEGENDARIES == broadcast.LEGENDARIES

    # 1. FALLBACK PATH: an NPC on an unmined map gets exactly the old
    # _gs_summary plus only the renown instruction -- no mined fields leak in.
    gs = {"map_group": 0, "map_num": 9, "npc_id": 1, "original_line": "Hi!",
          "badges": 2, "party": ["Poochyena:8"]}
    assert d._mined_entry(gs) is None
    g = d.build_grounding(gs)
    assert g == d._gs_summary(gs) + "\n" + d.RENOWN_LINES["rookie"]
    assert "canonically" not in g and "battle TRAINER" not in g and "Setting:" not in g
    # and the reply flow is unchanged (echo backend, fresh store)
    with tempfile.TemporaryDirectory() as td:
        ps = persona_engine.PersonaStore(os.path.join(td, "p.json"))
        r = d.handle_request(gs, ps, d.echo_persona, d.echo_chatter)
        assert r.startswith("[echo]")
        # empty mined table forced: byte-identical result
        r2 = d.handle_request(gs, ps, d.echo_persona, d.echo_chatter,
                              mined={"npcs": {}, "_maps": {}})
        assert r2 == r

    # 2. TRAINER AWARENESS: Jasmine (0:25:8), party hand-verified in
    # trainer_parties.h this session. Species+level only, no IVs.
    gs_j = {"map_group": 0, "map_num": 25, "npc_id": 8,
            "original_line": "x", "badges": 3, "party": ["Marshtomp:22"]}
    g = d.build_grounding(gs_j)
    assert "MAGNEMITE (Lv14), MAGNEMITE (Lv14), VOLTORB (Lv6)" in g
    assert "never invent" in g and "80" not in g          # iv=80 must not leak
    assert "thighs are like rocks" in g                   # resolved intro line
    assert "ALREADY been defeated" not in g and "NOT been defeated" not in g

    # 2b. BATTLE-STATUS-AWARE GROUNDING: trainer_defeated filters which
    # resolved vanilla line is shown, so the model can't reference both a
    # pre-battle and post-battle state at once (this was the live Jasmine
    # inconsistency bug). Unknown (omitted key, above) keeps showing both.
    gs_j_beaten = dict(gs_j, trainer_defeated=1)
    g_beaten = d.build_grounding(gs_j_beaten)
    assert "ALREADY been defeated" in g_beaten
    assert "NOT been defeated" not in g_beaten
    assert "thighs are like rocks" not in g_beaten   # intro line must be gone
    gs_j_unbeaten = dict(gs_j, trainer_defeated=0)
    g_unbeaten = d.build_grounding(gs_j_unbeaten)
    assert "NOT been defeated" in g_unbeaten
    assert "ALREADY been defeated" not in g_unbeaten
    assert "thighs are like rocks" in g_unbeaten     # intro line still shown

    # multi-variant rival (0:5:17): must NOT name a specific party
    gs_r = {"map_group": 0, "map_num": 5, "npc_id": 17,
            "original_line": "x", "badges": 3, "party": []}
    g = d.build_grounding(gs_r)
    assert "must NOT name specific Pokemon" in g and "SPECIES_" not in g
    assert "TROPIUS" not in g   # a variant party member must not be asserted

    # 3. RENOWN TIER across badge/level/legendary combinations
    for gs_t, want in [
        ({"badges": 0, "party": ["Poochyena:5"]}, "rookie"),
        ({"badges": 6, "party": ["Poochyena:5"]}, "experienced"),
        ({"badges": 0, "party": ["Swampert:45"]}, "experienced"),
        ({"badges": 8, "party": ["Rayquaza:70"]}, "feared"),
        ({"badges": 0, "party": ["Rayquaza:30"]}, "rookie"),   # legend < 50: no awe
        ({"badges": 0, "party": [], "game_clear": True}, "feared"),
    ]:
        assert d.renown_tier(gs_t) == want, (gs_t, want)
    # every NPC's grounding (mined or not) carries its tier line
    assert d.RENOWN_LINES["experienced"] in d.build_grounding(
        {"map_group": 0, "map_num": 9, "npc_id": 1, "badges": 7, "party": []})

    # 4. OBJECT-TYPE + GIFT GATES (mined maps only): passthrough echoes the
    # vanilla line; no persona store is touched (None would crash if it were).
    ball = {"map_group": 0, "map_num": 25, "npc_id": 19,
            "original_line": "ABHI found one DIRE HIT!"}
    assert d.handle_request(ball, None, d.echo_persona, d.echo_chatter) == \
        "ABHI found one DIRE HIT!"
    gift = {"map_group": 0, "map_num": 1, "npc_id": 34,
            "original_line": "ABHI obtained the POWDER JAR!"}
    assert d.handle_request(gift, None, d.echo_persona, d.echo_chatter) == \
        "ABHI obtained the POWDER JAR!"
    # same gift NPC, ordinary chat line -> normal persona flow
    with tempfile.TemporaryDirectory() as td:
        ps = persona_engine.PersonaStore(os.path.join(td, "p.json"))
        chat = {"map_group": 0, "map_num": 1, "npc_id": 34,
                "original_line": "BERRIES grow on trees.", "badges": 0, "party": []}
        assert d.handle_request(chat, ps, d.echo_persona, d.echo_chatter).startswith("[echo]")

    # 4b. DIALOGUE CONTINUITY: handle_request threads the NPC's own rolling
    # history into chatter() (avoiding the observed live "4 near-identical
    # Nurse Joy lines in a row" bug) and records each new line afterward.
    with tempfile.TemporaryDirectory() as td:
        ps = persona_engine.PersonaStore(os.path.join(td, "p.json"))
        seen_recent = []
        lines = iter(["Line one.", "Line two.", "Line three."])

        def fake_chatter(gs, persona_desc, recent_lines=None):
            seen_recent.append(list(recent_lines or []))
            return next(lines)

        chat2 = {"map_group": 0, "map_num": 1, "npc_id": 40,
                  "original_line": "Hello!", "badges": 0, "party": []}
        assert d.handle_request(chat2, ps, d.echo_persona, fake_chatter) == "Line one."
        assert d.handle_request(chat2, ps, d.echo_persona, fake_chatter) == "Line two."
        assert d.handle_request(chat2, ps, d.echo_persona, fake_chatter) == "Line three."
        assert seen_recent == [[], ["Line one."], ["Line one.", "Line two."]]
        assert ps.recent_lines(d.npc_key(chat2)) == ["Line two.", "Line three."]

    # 5. TRUE HOOK-LEVEL SKIP: signs/TVs (npc_id <= 0) get the real no-op
    # sentinel, not literal "..." -- the hook now leaves gStringVar4/
    # sTextPrinters completely untouched for this exact string (see
    # mgba_hook.lua's handleReply + the sendContext eager-placeholder gate).
    sign = {"map_group": 0, "map_num": 9, "npc_id": 0, "original_line": "PokeMart"}
    assert d.handle_request(sign, None, d.echo_persona, d.echo_chatter) == d.SKIP_SENTINEL
    tv = {"map_group": 0, "map_num": 9, "npc_id": -1, "original_line": "..."}
    assert d.handle_request(tv, None, d.echo_persona, d.echo_chatter) == d.SKIP_SENTINEL
    assert d.SKIP_SENTINEL != "..."   # distinct from the designer-failure fallback
    assert "|" not in d.SKIP_SENTINEL and "\n" not in d.SKIP_SENTINEL


# ------------------------------------------- bridge resilience (Step 5 fixes)
def t_bridge_resilience():
    """(a) A single failed chatter() call (backend down mid-session) must
    fall back to a neutral line and must NOT propagate -- the socket loop
    would otherwise stay alive too (it has its own catch-all), but that
    caught a raw exception string as if it were dialogue; handle_request
    itself must now catch it first and log, not leak, the error.
    (b) ollama_reachable() must return False (not raise/hang) against a
    port nothing is listening on, so the startup preflight can act on it."""
    import dialogue_bridge_server as d
    import persona_engine

    def raising_chatter(gs, persona_desc, recent_lines=None):
        raise RuntimeError("simulated Ollama connection failure")

    with tempfile.TemporaryDirectory() as td:
        ps = persona_engine.PersonaStore(os.path.join(td, "p.json"))
        gs = {"map_group": 0, "map_num": 1, "npc_id": 50,
              "original_line": "Hello!", "badges": 0, "party": []}
        reply = d.handle_request(gs, ps, d.echo_persona, raising_chatter)
        assert reply == "...", reply
        # no line recorded -- the failed call never produced real dialogue
        assert ps.recent_lines(d.npc_key(gs)) == []

    # a second call on the same NPC (persona already cached) must ALSO
    # survive a failing chatter -- not just the first, uncached call
    with tempfile.TemporaryDirectory() as td:
        ps = persona_engine.PersonaStore(os.path.join(td, "p.json"))
        gs = {"map_group": 0, "map_num": 1, "npc_id": 51,
              "original_line": "Hello!", "badges": 0, "party": []}
        d.handle_request(gs, ps, d.echo_persona, d.echo_chatter)  # warms cache
        reply2 = d.handle_request(gs, ps, d.echo_persona, raising_chatter)
        assert reply2 == "...", reply2

    assert d.ollama_reachable("http://127.0.0.1:1/api/tags", timeout=1.0) is False


# --------------------------------------------------------------- quest engine
def t_quest_engine():
    import quest_engine as qe
    good = {"quest_type": "fetch_item",
            "target": {"item_id": 139, "quantity": 2},
            "reward": {"item_id": 13, "quantity": 1},
            "flavor": {"intro": "i", "reminder": "r", "complete": "c"}}
    assert qe.validate_quest(good)[0]
    assert not qe.validate_quest({**good, "reward": {"item_id": 1, "quantity": 1}})[0]
    assert not qe.validate_quest("nonsense")[0]
    with tempfile.TemporaryDirectory() as d:
        qm = qe.QuestManager(os.path.join(d, "q.json"))
        gs = {"map_group": 1, "map_num": 4, "npc_id": 7,
              "party": ["Blaziken:45"], "bag": []}
        d1, a1 = qm.handle_talk(gs, lambda g: good)
        assert (d1, a1) == ("i", [])
        gs["bag"] = ["139:2"]
        d2, a2 = qm.handle_talk(gs, lambda g: good)
        assert d2 == "c" and a2 == ["take_item:139:2", "give_item:13:1"]
        d3, a3 = qm.handle_talk(gs, lambda g: good)
        assert a3 == []  # no double reward
        qm2 = qe.QuestManager(os.path.join(d, "q.json"))
        assert qm2.handle_talk(gs, lambda g: good)[1] == []  # persisted
    assert qe.serialize_reply("x\ny", ["a:1:2"]) == "a:1:2|x y"


# -------------------------------------------------------------- persona layer
def t_persona():
    import persona_engine as pe
    from quest_bridge_server import handle_request, echo_persona, echo_quest, SMALLTALK
    import quest_engine as qe
    assert pe.validate_persona(echo_persona({}))[0]
    assert not pe.validate_persona({"archetype": "x"})[0]
    with tempfile.TemporaryDirectory() as d:
        ps = pe.PersonaStore(os.path.join(d, "p.json"))
        calls = []
        card = ps.get_or_create("k", lambda g: (calls.append(1) or echo_persona(g)), {})
        ps.get_or_create("k", lambda g: (calls.append(1) or echo_persona(g)), {})
        assert card and len(calls) == 1
        qm = qe.QuestManager(os.path.join(d, "q.json"))
        gs = {"map_group": 2, "map_num": 2, "npc_id": 2, "party": [], "bag": []}
        r = handle_request(gs, qm, ps, lambda g: None, echo_persona)
        assert r == echo_persona({})["greeting"]
        r2 = handle_request({"map_group": 3, "map_num": 3, "npc_id": 3, "party": [], "bag": []},
                            qm, ps, lambda g: None,
                            lambda g: (_ for _ in ()).throw(RuntimeError()))
        assert r2 == SMALLTALK

        # rolling chatter history (dialogue-bridge continuity fix): last
        # HISTORY_LEN lines only, oldest first, empty until anything is said,
        # a no-op for a key with no persona card yet.
        assert ps.recent_lines("k") == []
        ps.record_line("no-such-key", "should be dropped, no card to attach to")
        assert ps.recent_lines("no-such-key") == []
        ps.record_line("k", "Nice weather today.")
        assert ps.recent_lines("k") == ["Nice weather today."]
        ps.record_line("k", "The berries are ripe.")
        ps.record_line("k", "Trainers pass through often.")
        assert ps.recent_lines("k") == ["The berries are ripe.", "Trainers pass through often."]
        # persists across a fresh PersonaStore load from the same file
        ps2 = pe.PersonaStore(os.path.join(d, "p.json"))
        assert ps2.recent_lines("k") == ["The berries are ripe.", "Trainers pass through often."]
        # a persona card's own validated fields are untouched by history
        assert pe.validate_persona(ps2.cards["k"])[0]


# --------------------------------------------------- dialogue prompt building
def t_prompt():
    import step1_dialogue_ollama as s
    u = s.build_user_message({"original_line": "Berries!", "party": ["Blaziken:45"],
                              "badges": 5, "map_group": 1, "map_num": 4})
    assert "Berries!" in u and "Blaziken:45" in u and "badges: 5" in u


# ------------------------------------------- full lifecycle over a real socket
def t_socket_lifecycle():
    port = 8987
    with tempfile.TemporaryDirectory() as d:
        logp = os.path.join(d, "t.jsonl")
        proc = subprocess.Popen(
            [sys.executable, "-u", _find("quest_bridge_server.py"), "--echo",
             "--port", str(port), "--store", os.path.join(d, "q.json"),
             "--profiles", os.path.join(d, "p.json"), "--log", logp],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            s = None
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    s = socket.socket(); s.settimeout(5)
                    s.connect(("127.0.0.1", port)); break
                except OSError:
                    s = None
                    if proc.poll() is not None:
                        raise RuntimeError("server died: " + proc.stdout.read())
                    time.sleep(0.3)
            assert s, "server never became ready"

            def talk(gs):
                s.sendall((json.dumps(gs) + "\n").encode())
                buf = b""
                while b"\n" not in buf:
                    buf += s.recv(4096)
                return buf.split(b"\n", 1)[0].decode()

            base = {"map_group": 1, "map_num": 4, "npc_id": 7, "party": ["Blaziken:45"]}
            assert "Oran Berries" in talk({**base, "bag": []})
            assert "Still waiting" in talk({**base, "bag": []})
            done = talk({**base, "bag": ["139:2"]})
            assert done.split("|", 1)[0] == "take_item:139:2;give_item:13:1"
            assert "|" not in talk({**base, "bag": ["13:2"]})
            s.close()
            time.sleep(0.3)
            lines = open(logp, encoding="utf-8").read().strip().splitlines()
            assert len(lines) == 4, f"transcript should have 4 lines, has {len(lines)}"
            assert json.loads(lines[2])["reply"].startswith("take_item")
        finally:
            proc.terminate()
            try:
                proc.communicate(timeout=3)
            except Exception:
                proc.kill()


# ---------------------------------------------------- islands + advisor
def t_islands_advisor():
    import quest_engine as qe
    from quest_bridge_server import handle_request, echo_quest, echo_persona, island_quest
    import persona_engine as pe, world_tables, tempfile as tf
    iq = island_quest("southern_island", "Lilycove City")
    assert qe.validate_quest(iq)[0]
    assert not qe.validate_quest(dict(iq, unlock="atlantis"))[0]
    lily = next(k for k, v in world_tables.MAPS.items() if v == "Lilycove City")
    with tf.TemporaryDirectory() as d:
        qm = qe.QuestManager(os.path.join(d, "q.json"))
        ps = pe.PersonaStore(os.path.join(d, "p.json"))
        gs = {"map_group": lily[0], "map_num": lily[1], "npc_id": 4,
              "party": [], "bag": ["139:2"], "unlocks": 0}
        handle_request(dict(gs, bag=[]), qm, ps, echo_quest, echo_persona)
        done = handle_request(gs, qm, ps, echo_quest, echo_persona)
        acts = done.split("|", 1)[0]
        assert acts == "take_item:139:2;give_item:275:1:key;set_flag:2227", acts
        tip = handle_request({"advice": 1, "badges": 7}, qm, ps, echo_quest, echo_persona)
        assert "Sootopolis" in tip


# --------------------------------------- world reactions (TV/awe/dad guide)
def t_reactions():
    import random, tempfile as tf
    import broadcast, advisor, world_tables
    import quest_engine as qe
    from quest_bridge_server import build_world_notes
    random.seed(1)
    with tf.TemporaryDirectory() as d:
        qm = qe.QuestManager(os.path.join(d, "q.json"))
        n = broadcast.news({"game_clear": 1, "party": ["Rayquaza:70"], "badges": 8}, qm)
        assert "CHAMPION" in n and "Rayquaza" in n
        ql, acts = broadcast.quiz({"map_group": 9, "map_num": 9})
        assert acts == ["await_choice:600"] and "WHO'S THAT" in ql
        ans = broadcast._pending[(9, 9)]["answer"]
        d2, a2 = broadcast.resolve({"map_group": 9, "map_num": 9, "choice": ans})
        assert a2 == ["give_item:139:1"]
        w = build_world_notes({"party": ["Kyogre:60"], "game_clear": 1, "bag": []}, qm)
        assert "LEGENDARY Kyogre" in w and "CHAMPION" in w
        assert "LEGENDARY" not in build_world_notes({"party": ["Poochyena:5"], "bag": []}, qm)
        bf = next(k for k, v in world_tables.MAPS.items() if v == "Battle Frontier")
        assert advisor.get_tip({"map_group": bf[0], "map_num": bf[1], "npc_id": 1}).startswith("DAD:")


# ------------------------------------------------- extract_addresses.py sync
def t_extract_addresses():
    import re, subprocess, tempfile as tf
    # every ADDR_* the hook actually declares
    hook_addrs = set(re.findall(r"local (ADDR_\w+)\s*=\s*nil", open(_find("mgba_hook.lua"), encoding="utf-8").read()))
    tool_src = open(_find("extract_addresses.py"), encoding="utf-8").read()
    tool_vars = set(re.findall(r'"(ADDR_\w+)"', tool_src))
    missing = hook_addrs - tool_vars
    assert not missing, f"extract_addresses.py is missing: {missing} (hook grew, tool didn't)"
    # check the SYMBOL KEYS specifically (a "gTextPrinters" inside an explanatory
    # comment, e.g. "NOT gTextPrinters", is fine -- only a dict key would be a bug)
    wanted_keys = set(re.findall(r'"(\w+)":\s*"ADDR_', tool_src))
    assert "gTextPrinters" not in wanted_keys, "stale wrong symbol name as a dict key"
    assert "sTextPrinters" in wanted_keys
    # functional smoke test against a synthetic map
    with tf.TemporaryDirectory() as d:
        mapfile = os.path.join(d, "t.map")
        open(mapfile, "w", encoding="utf-8").write(
            "                0x02024284                gPlayerParty\n"
            "                0x02024029                gPlayerPartyCount\n")
        r = subprocess.run([sys.executable, _find("extract_addresses.py"), mapfile],
                           capture_output=True, text=True, timeout=10)
        assert "0x02024284" in r.stdout and "ADDR_PLAYER_PARTY" in r.stdout
        assert "NOT FOUND" in r.stdout   # the other 6 correctly reported missing


# ------------------------------------------------ Windows encoding safety
def t_windows_encoding():
    """Guards the exact bug a Windows PC hit: bare file-open calls default to
    the OS codepage (cp1252 on Windows) instead of UTF-8, so any file with
    non-ASCII content (the Emerald charmap's accented/kana entries, box-
    drawing chars in docs, or LLM-generated dialogue with curly quotes /
    em-dashes saved to quests.json / npc_profiles.json) crashes on Windows
    even though it works fine on Linux/Mac. Every file-open call for text in
    this codebase must pin encoding="utf-8" explicitly."""
    import re
    paths = ["run_all_tests.py", "extract_addresses.py", "watchdog.py",
             os.path.join("bridge", "broadcast.py"),
             os.path.join("bridge", "persona_engine.py"),
             os.path.join("bridge", "quest_bridge_server.py"),
             os.path.join("bridge", "quest_engine.py")]
    for path in paths:
        src = open(path, encoding="utf-8").read()
        for m in re.finditer(r"\bopen\(", src):
            prefix = src[max(0, m.start() - 10):m.start()]
            if "Popen" in prefix:
                continue
            window = src[m.start():m.start() + 200]
            depth, end = 0, None
            for i, ch in enumerate(window):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            call = window[:end + 1] if end else window
            assert "encoding=" in call or '"b"' in call or "'b'" in call, \
                f"{path}: a file-read call is missing an explicit encoding: {call[:70]!r}"
    # functional proof: non-ASCII text actually round-trips through the
    # persistent stores a real Windows session would write to.
    import persona_engine as pe
    import quest_engine as qe
    import tempfile
    tricky = "Ahh\u2014the sea calls to me\u2026 \u00e9\u00e8\u00e0! \u3042"  # em-dash, ellipsis, accents, kana
    with tempfile.TemporaryDirectory() as d:
        ps = pe.PersonaStore(os.path.join(d, "p.json"))
        card = {"archetype": tricky, "temperament": "t", "quirk": "q", "greeting": "g"}
        ps.get_or_create("k", lambda g: card, {})
        ps2 = pe.PersonaStore(os.path.join(d, "p.json"))
        reloaded = ps2.get_or_create("k", lambda g: card, {})
        assert reloaded["archetype"] == tricky, "non-ASCII persona text corrupted on reload"


# ------------------------------------------------------------------- watchdog
def t_watchdog():
    import tempfile as tf
    with tf.TemporaryDirectory() as d:
        r = subprocess.run([sys.executable, "watchdog.py", "--backoff", "0.05",
                            "--max-restarts", "2", "--log", os.path.join(d, "w.log"),
                            "--", sys.executable, "-c", "pass"],
                           capture_output=True, text=True, timeout=20)
        assert r.stdout.count("restart #") == 2 and r.returncode == 1


# --------------------- encodeEmerald: locale-safe multi-byte glyph fallback
def t_encode_unmapped_glyphs():
    """Regression test for a bug found while auditing encodeEmerald's CHARMAP
    fallback (which was already safe -- unmapped glyphs fall back to
    CHARMAP[" "]=0x00, never to 0xFF/EOS; the ONLY charmap entry equal to
    0xFF is "$", already guarded). The REAL bug was one level up: the
    word-splitter used Lua's "%S+" pattern, whose %S class calls the C
    runtime's locale-dependent isspace() for bytes >= 0x80. On a locale
    where byte 0xA0 counts as whitespace (reproduced here directly), 0xA0
    -- a common UTF-8 CONTINUATION byte, e.g. inside "\xE4\xBD\xA0" (one
    3-byte CJK glyph) -- got misclassified as a word boundary, splitting a
    single glyph's bytes across two "words" and corrupting it into stray
    single-byte fallbacks instead of one clean glyph-level 0x00. Fixed by
    matching literal ASCII separators ("[^ \\t\\r]+") instead of locale-
    dependent %S. This test proves the fix two ways: (1) directly, that
    this runtime's locale DOES misclassify 0xA0 (so the bug is real, not
    hypothetical) and (2) that encodeEmerald nonetheless now emits exactly
    ONE fallback byte per unmapped multi-byte glyph, correctly bounded by
    the byte count utf8Glyphs reports."""
    try:
        import lupa
    except ImportError:
        SKIP.append("encodeEmerald unmapped glyphs (pip install lupa)")
        print("  [SKIP] encodeEmerald unmapped glyphs -- `pip install lupa` to enable")
        return
    lua = lupa.LuaRuntime()
    # (1) informational only, not asserted: whether THIS machine's locale
    # actually misclassifies 0xA0 as whitespace is environment-dependent
    # (confirmed true on the Windows/en-IN locale this bug was found on;
    # may differ on Linux/"C" locale cloud sessions) -- the fix below must
    # hold regardless, since %S/isspace() locale-dependence for bytes >=
    # 0x80 is real on SOME platforms even when not reproducible on this one.
    hazard_live = bool(lua.eval("string.char(0xA0):match('%s') ~= nil"))
    print(f"  [info] this runtime's locale classifies 0xA0 as whitespace: {hazard_live}")
    lua.execute("""
MEM = {}
local function r8(a) return MEM[a] or 0 end
local function w8(a, v) MEM[a] = v end
local function r16(a) return r8(a) + r8(a + 1) * 256 end
local function r32(a) return r16(a) + r16(a + 2) * 65536 end
SENT={}; RXQ={}
local fake={}
function fake:add(ev,fn) self["cb_"..ev]=fn end
function fake:send(d) SENT[#SENT+1]=d; return #d end
function fake:receive(n) return nil end
socket={connect=function() return fake end}
FAKESOCK=fake
emu={read8=function(s,a) return r8(a) end, read16=function(s,a) return r16(a) end,
 read32=function(s,a) return r32(a) end, write8=function(s,a,v) w8(a,v) end,
 write16=function() end, write32=function() end, getKey=function() return 0 end}
console={log=function() end,warn=function() end,error=function() end,
 createBuffer=function() return {print=function() end,clear=function() end} end}
callbacks={add=function(s,n,fn) FRAMEFN=fn end}
""")
    with _in_lua_dir():
        lua.execute(open(_find("mgba_hook.lua"), encoding="utf-8").read() +
                    "\nENCODE_EMERALD_TEST_HOOK = encodeEmerald\n")
    enc = lua.globals().ENCODE_EMERALD_TEST_HOOK
    # (2) "X" + one unmapped 3-byte CJK glyph + "Y", as ONE word (no ASCII
    # space between them) -- exactly the shape that broke before the fix.
    # (a real CJK codepoint, not a "\xNN" escape -- those name Unicode
    # codepoints in a Python str, not raw bytes, and would silently test
    # the wrong thing: three 2-byte Latin-1-range glyphs, not one 3-byte one)
    result = enc("X" + "你" + "Y")
    b = list(result.values())
    # header(2) + X + ONE fallback byte for the glyph + Y + footer(2) == 7
    assert len(b) == 7, ("expected exactly one fallback byte for the "
                          "3-byte glyph, got byte sequence " + str([hex(x) for x in b]))
    assert b[2] == 0xD2 and b[3] == 0x00 and b[4] == 0xD3, [hex(x) for x in b]

    PASS.append("encodeEmerald unmapped glyphs")
    print("  [PASS] encodeEmerald unmapped multi-byte glyph -- one clean "
          "fallback byte, no locale-dependent word-split corruption")


# ----------------------------------------------------------- lua syntax check
def t_lua():
    try:
        import lupa
    except ImportError:
        SKIP.append("lua syntax (pip install lupa to enable)")
        print("  [SKIP] lua syntax check -- `pip install lupa` to enable")
        return
    lua = lupa.LuaRuntime()
    with _in_lua_dir():
        for f in ("mgba_hook.lua", "party_reader.lua", "species_names.lua",
                  "charmap.lua", "trainer_info.lua", "trainer_flags.lua"):
            res = lua.eval("function(s) local fn, e = load(s); return fn, e end")(open(_find(f), encoding="utf-8").read())
            fn = res[0] if isinstance(res, tuple) else res
            assert fn, f"{f} has a syntax error"
    PASS.append("lua syntax")
    print("  [PASS] lua syntax (all 6 files compile)")


# ------------------------------------------- hook choice loop (needs lupa)
def t_hook_choice():
    try:
        import lupa
    except ImportError:
        SKIP.append("hook choice loop (pip install lupa)")
        print("  [SKIP] hook choice loop -- `pip install lupa` to enable")
        return
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
SENT={}; RXQ={}; KEY_A=0
local fake={}
function fake:add(ev,fn) self["cb_"..ev]=fn end
function fake:send(d) SENT[#SENT+1]=d; return #d end
function fake:receive(n) if #RXQ>0 then return table.remove(RXQ,1) end return nil end
socket={connect=function() return fake end}
FAKESOCK=fake
emu={read8=function() return 0 end,read16=function() return 0 end,read32=function() return 0 end,
 write8=function() end,write16=function() end,write32=function() end,
 getKey=function(s,k) if k==0 then return KEY_A end return 0 end}
console={log=function() end,warn=function() end,error=function() end,
 createBuffer=function() return {print=function() end,clear=function() end} end}
callbacks={add=function(s,n,fn) FRAMEFN=fn end}
""")
    with _in_lua_dir():
        lua.execute(open(_find("mgba_hook.lua"), encoding="utf-8").read())
    lua.execute('RXQ[#RXQ+1]="await_choice:600|Quiz!\\n"')
    lua.execute("FAKESOCK.cb_received(FAKESOCK)")
    lua.execute("FRAMEFN()")
    lua.execute("KEY_A=1")
    lua.execute("FRAMEFN()")
    assert lua.eval("#SENT") == 1
    assert '"choice":1' in lua.globals().SENT[1]
    PASS.append("hook choice")
    print("  [PASS] hook choice loop (A press -> choice:1 over the wire)")


# ---------------------------- hook skip sentinel + trainer flag (needs lupa)
def t_hook_skip_and_trainer_flag():
    """Drives the REAL mgba_hook.lua (not just the bridge's Python side)
    through a byte-addressable fake GBA memory, proving two things end to
    end: (1) a sign (npc_id==0) never gets its box touched -- no eager "..."
    placeholder, and no write at all once the bridge answers SKIP_SENTINEL;
    (2) the trainer-flag read for Jasmine (0:25:8, TRAINER_JASMINE=359,
    source-verified in include/constants/opponents.h) correctly reports
    trainer_defeated in the outgoing context JSON."""
    try:
        import lupa
    except ImportError:
        SKIP.append("hook skip sentinel + trainer flag (pip install lupa)")
        print("  [SKIP] hook skip sentinel + trainer flag -- `pip install lupa` to enable")
        return
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
MEM = {}
local function r8(a) return MEM[a] or 0 end
local function w8(a, v) MEM[a] = v end
local function r16(a) return r8(a) + r8(a + 1) * 256 end
local function r32(a) return r16(a) + r16(a + 2) * 65536 end
SENT={}; RXQ={}
local fake={}
function fake:add(ev,fn) self["cb_"..ev]=fn end
function fake:send(d) SENT[#SENT+1]=d; return #d end
function fake:receive(n) if #RXQ>0 then return table.remove(RXQ,1) end return nil end
socket={connect=function() return fake end}
FAKESOCK=fake
emu={read8=function(s,a) return r8(a) end, read16=function(s,a) return r16(a) end,
 read32=function(s,a) return r32(a) end, write8=function(s,a,v) w8(a,v) end,
 write16=function() end, write32=function() end, getKey=function() return 0 end}
console={log=function() end,warn=function() end,error=function() end,
 createBuffer=function() return {print=function() end,clear=function() end} end}
callbacks={add=function(s,n,fn) FRAMEFN=fn end}
""")
    with _in_lua_dir():
        lua.execute(open(_find("mgba_hook.lua"), encoding="utf-8").read())

    # ---- shared fake save block: SB1 base = 0x02020000 ----
    lua.execute("""
local SB1 = 0x02020000
MEM[0x03005d8c] = SB1 % 256; MEM[0x03005d8d] = 0; MEM[0x03005d8e] = 0x02; MEM[0x03005d8f] = 0x02
MEM[SB1 + 0x04] = 0    -- map_group
MEM[SB1 + 0x05] = 25   -- map_num (Route 110)
-- Jasmine: TRAINER_JASMINE = 359 (verified: opponents.h), flag id =
-- TRAINER_FLAGS_START(0x500) + 359 = 1639; byte = SB1+0x1270+floor(1639/8),
-- bit = 1639%8 = 7 -> 0x80. Marks her as ALREADY DEFEATED.
MEM[SB1 + 0x1270 + 204] = 0x80
MEM[0x020375f2] = 8; MEM[0x020375f3] = 0   -- gSpecialVar_LastTalked = 8 (Jasmine)
MEM[0x02021fc4] = 0xFF                     -- gStringVar4: empty vanilla string
FRAMEFN()                                  -- prime lastMode = HIDDEN, no edge yet
MEM[0x020375bc] = 1                        -- sFieldMessageBoxMode: HIDDEN -> NORMAL
FRAMEFN()                                  -- "opened" edge -> sendContext(8)
""")
    sent = lua.globals().SENT
    assert len(sent) == 1, "expected exactly one context sent for Jasmine"
    assert '"npc_id":8' in sent[1] and '"map_group":0' in sent[1] and '"map_num":25' in sent[1]
    assert '"trainer_defeated":1' in sent[1], sent[1]

    # ---- sign (npc_id==0): close Jasmine's box, then open a sign's ----
    lua.execute("""
MEM[0x020375bc] = 0   -- close Jasmine's box (mode -> HIDDEN)
FRAMEFN()
MEM[0x020375f2] = 0; MEM[0x020375f3] = 0   -- gSpecialVar_LastTalked = 0 (sign)
MEM[0x02021fc4] = 0x41                     -- arbitrary "vanilla text" byte
MEM[0x020201cb] = 0x77                     -- sTextPrinters[0].active: arbitrary sentinel
MEM[0x020375bc] = 1                        -- opened edge for the sign
FRAMEFN()
""")
    sent = lua.globals().SENT
    assert len(sent) == 2, "sign should still contact the bridge (npc_id==0 isn't skipped client-side)"
    assert '"npc_id":0' in sent[2]
    # the eager "..." placeholder must NOT have fired: gStringVar4 and the
    # printer's active byte are byte-for-byte untouched from what we set.
    assert lua.eval("MEM[0x02021fc4]") == 0x41
    assert lua.eval("MEM[0x020201cb]") == 0x77

    # ---- bridge answers with the true skip sentinel ----
    lua.execute('RXQ[#RXQ+1]="<<SKIP>>\\n"')
    lua.execute("FAKESOCK.cb_received(FAKESOCK)")
    # still untouched after the reply -- handleReply must no-op on the sentinel
    assert lua.eval("MEM[0x02021fc4]") == 0x41
    assert lua.eval("MEM[0x020201cb]") == 0x77

    PASS.append("hook skip sentinel + trainer flag")
    print("  [PASS] hook skip sentinel (zero writes for signs) + Jasmine trainer-flag read")


# ------------------------------- trainer_defeated: nil/true/false (needs lupa)
def t_trainer_defeated_tristate():
    """Regression test for the `(defeated == nil) and nil or (defeated and 1
    or 0)` bug: that expression LOOKS like a nil-guard but isn't one -- `A and
    nil` is always falsy in Lua, so the `or` branch always ran and silently
    turned "unknown" into 0. Drives the real mgba_hook.lua through three
    talk-to-NPC cycles and checks all three trainer_defeated encodings against
    the outgoing JSON: known-defeated -> 1, known-not-defeated -> 0, and NPC
    outside TRAINER_ID_BY_KEY (npc 250 at 0:25, not in lua/trainer_flags.lua)
    -> field omitted entirely (still nil, not silently coerced to 0)."""
    try:
        import lupa
    except ImportError:
        SKIP.append("trainer_defeated nil/true/false (pip install lupa)")
        print("  [SKIP] trainer_defeated nil/true/false -- `pip install lupa` to enable")
        return
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("""
MEM = {}
local function r8(a) return MEM[a] or 0 end
local function w8(a, v) MEM[a] = v end
local function r16(a) return r8(a) + r8(a + 1) * 256 end
local function r32(a) return r16(a) + r16(a + 2) * 65536 end
SENT={}; RXQ={}
local fake={}
function fake:add(ev,fn) self["cb_"..ev]=fn end
function fake:send(d) SENT[#SENT+1]=d; return #d end
function fake:receive(n) if #RXQ>0 then return table.remove(RXQ,1) end return nil end
socket={connect=function() return fake end}
FAKESOCK=fake
emu={read8=function(s,a) return r8(a) end, read16=function(s,a) return r16(a) end,
 read32=function(s,a) return r32(a) end, write8=function(s,a,v) w8(a,v) end,
 write16=function() end, write32=function() end, getKey=function() return 0 end}
console={log=function() end,warn=function() end,error=function() end,
 createBuffer=function() return {print=function() end,clear=function() end} end}
callbacks={add=function(s,n,fn) FRAMEFN=fn end}
""")
    with _in_lua_dir():
        lua.execute(open(_find("mgba_hook.lua"), encoding="utf-8").read())
    lua.execute("""
local SB1 = 0x02020000
MEM[0x03005d8c] = SB1 % 256; MEM[0x03005d8d] = 0; MEM[0x03005d8e] = 0x02; MEM[0x03005d8f] = 0x02
MEM[SB1 + 0x04] = 0    -- map_group
MEM[SB1 + 0x05] = 25   -- map_num (Route 110)
MEM[0x02021fc4] = 0xFF -- gStringVar4: empty vanilla string

local function talkTo(lastTalked)
  MEM[0x020375bc] = 0   -- close any open box
  FRAMEFN()
  MEM[0x020375f2] = lastTalked % 256; MEM[0x020375f3] = 0
  MEM[0x020375bc] = 1   -- opened edge
  FRAMEFN()
end

-- 1) Jasmine (npc 8, TRAINER_JASMINE=359), flag CLEAR -> known, not defeated
MEM[SB1 + 0x1270 + 204] = 0x00
talkTo(8)

-- 2) Jasmine again, flag SET -> known, defeated
MEM[SB1 + 0x1270 + 204] = 0x80
talkTo(8)

-- 3) npc 250 at this map -- not in TRAINER_ID_BY_KEY -> unknown
talkTo(250)
""")
    sent = lua.globals().SENT
    assert len(sent) == 3, f"expected 3 contexts sent, got {len(sent)}"
    assert '"trainer_defeated":0' in sent[1], sent[1]
    assert '"trainer_defeated":1' in sent[2], sent[2]
    assert '"trainer_defeated"' not in sent[3], sent[3]

    PASS.append("trainer_defeated nil/true/false")
    print("  [PASS] trainer_defeated tri-state (unknown NPC omits the field, not 0)")


# ------------------------------ hardened persona JSON parser (_json_of etc.)
def t_persona_json_parser():
    """Covers _json_of / _clip_persona_fields / _finish_persona.

    COVERAGE GAP this closes: README and CLAUDE.md both advertise "one
    hardened JSON parser" as a headline property of the three-backend design,
    and t_persona did not touch it. Every backend's persona path runs through
    _finish_persona, so an unnoticed regression here would break all three at
    once while the suite stayed green. Each case below is one behaviour the
    parser's own docstring promises.
    """
    import dialogue_bridge_server as B

    good = '{"archetype": "sailor", "temperament": "gruff", ' \
           '"quirk": "hums shanties", "greeting": "Ahoy there."}'

    # -- the three deviations the docstring says it tolerates ---------------
    assert B._json_of(good)["archetype"] == "sailor"
    assert B._json_of("```json\n" + good + "\n```")["archetype"] == "sailor"
    # A plain fence is NOT enough to prove the fence branch works: the
    # first-{/last-} scan below it already strips simple fences on its own
    # (confirmed by mutation -- deleting the fence branch left the plain case
    # passing). This input is where the branch is genuinely load-bearing:
    # prose containing a brace BEFORE the fence, which makes the outer scan
    # span from the prose brace to the real closing brace and yield garbage.
    assert B._json_of(
        "Use the schema {archetype, temperament, quirk, greeting} like so:\n"
        "```json\n" + good + "\n```")["archetype"] == "sailor"
    assert B._json_of("Sure! Here you go:\n" + good + "\nHope that helps!"
                      )["archetype"] == "sailor"
    # single-quoted Python-dict style, which small instruct models emit often
    assert B._json_of("{'archetype': 'sailor', 'temperament': 'gruff'}"
                      )["archetype"] == "sailor"

    # -- and the failures it must RAISE on rather than silently swallow -----
    for bad in ("no object here at all", "", "}{"):
        try:
            B._json_of(bad)
            raise AssertionError(f"expected a raise for {bad!r}")
        except ValueError:
            pass
    # literal_eval must not be reachable as an execution path: a non-dict
    # literal parses fine but is not a persona, and must still raise.
    try:
        B._json_of("{1, 2, 3}")
        raise AssertionError("a set literal must not pass as a persona")
    except ValueError:
        pass

    # -- clipping truncates over-length fields instead of rejecting them ----
    clipped = B._clip_persona_fields({"archetype": "x" * 200, "temperament": "t",
                                      "quirk": "q", "greeting": "g"})
    assert len(clipped["archetype"]) == 40, len(clipped["archetype"])
    # a field present but blank is DROPPED, so it surfaces through the
    # "missing field(s)" diagnostic rather than as a silent invalid card
    assert "quirk" not in B._clip_persona_fields(
        {"archetype": "a", "temperament": "t", "quirk": "   ", "greeting": "g"})

    # -- _finish_persona ties them together and validates ------------------
    card = B._finish_persona("```json\n" + good + "\n```")
    assert card["greeting"] == "Ahoy there."
    for missing in ('{"archetype": "sailor"}', "not json at all"):
        try:
            B._finish_persona(missing)
            raise AssertionError(f"expected a raise for {missing!r}")
        except ValueError:
            pass


# ------------------------------- persona failure diagnostics (silent-"..." )
def t_persona_failure_is_never_silent():
    """Every way a persona can fail must say WHY on the terminal.

    BUG this covers: PersonaStore.get_or_create swallowed the designer's
    exception with a bare `except Exception: return None`, so a backend
    outage during persona design produced a silent "..." in-game with nothing
    logged -- while the identical outage one call later, in chatter(), logged
    "chatter call failed for <key>". Two failures that look the same in-game
    and completely different in the terminal is how a diagnosis goes wrong.

    .claude/rules/cloud-and-local.md tells the reader that a degraded "..."
    is explained by a terminal diagnostic. This test is what makes that
    documented claim true for every path rather than most of them.
    """
    import contextlib
    import io as _io
    import persona_engine
    import dialogue_bridge_server as B

    gs = {"npc_id": 1, "map_group": 0, "map_num": 1, "original_line": "hi",
          "party": ["Torchic:8"], "badges": 0}

    def _raises(_gs):
        raise ConnectionError("simulated backend outage")

    cases = [
        ("designer raises", _raises),
        ("designer returns an incomplete card", lambda g: {"archetype": "sailor"}),
        ("designer returns nothing", lambda g: None),
    ]
    for label, designer in cases:
        store = persona_engine.PersonaStore(os.path.join(tempfile.gettempdir(),
                                                         "t_persona_never_silent.json"))
        store._save = lambda: None
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            reply = B.handle_request(dict(gs), store, designer,
                                     lambda g, p, r=None: "unused",
                                     mined={"npcs": {}, "_maps": {}})
        logged = buf.getvalue().strip()
        assert reply == "...", f"{label}: expected the neutral fallback, got {reply!r}"
        assert logged, f"{label}: degraded to '...' with NOTHING logged"
        assert "[persona]" in logged, f"{label}: logged without the [persona] tag: {logged!r}"

    # ...and the success path must stay quiet, or the log becomes noise.
    store = persona_engine.PersonaStore(os.path.join(tempfile.gettempdir(),
                                                     "t_persona_never_silent.json"))
    store._save = lambda: None
    buf = _io.StringIO()
    with contextlib.redirect_stdout(buf):
        reply = B.handle_request(dict(gs), store,
                                 lambda g: {"archetype": "sailor",
                                            "temperament": "gruff",
                                            "quirk": "hums sea shanties",
                                            "greeting": "Ahoy there."},
                                 lambda g, p, r=None: "The tide is high today.",
                                 mined={"npcs": {}, "_maps": {}})
    assert reply == "The tide is high today.", reply
    assert "[persona]" not in buf.getvalue(), buf.getvalue()


# ------------------------------------------- eval harness metrics (M1-M4)
def t_eval_metrics():
    """Runs eval/test_metrics.py in-process.

    EVAL_HARNESS_SPEC section 7 requires every M2 rule to carry one
    true-positive and one true-negative test, and section 4 makes the point
    that an unvalidated detector is the same failure mode as the bug the
    harness exists to catch. Surfacing them here means `python
    run_all_tests.py` stays the single command that proves the repo healthy.
    """
    sys.path.insert(0, os.path.join(HERE, "eval"))
    sys.path.insert(0, os.path.join(HERE, "eval", "metrics"))
    import test_metrics
    total, failed = test_metrics.run_all()
    assert total >= 30, f"expected the full metric suite, only found {total} tests"
    assert not failed, "; ".join(f"{n}: {e}" for n, e in failed)


if __name__ == "__main__":
    print("== Pokemon LLM Bridge: full test suite ==")
    check("items table (source-verified IDs, Master Ball denylisted)", t_items)
    check("world tables (482 maps, 66 classes, prompt integration)", t_world)
    check("NPC dialogue table (pilot: 5 maps, 103 NPCs, resolved text)", t_npc_table)
    check("mined grounding (fallback identity, trainer party, renown, gates)", t_mined_grounding)
    check("bridge resilience (failed chatter call, Ollama preflight)", t_bridge_resilience)
    check("quest engine (gate, lifecycle, persistence, no double reward)", t_quest_engine)
    check("persona layer (validation, cache-once, fallback chain)", t_persona)
    check("dialogue prompt building (v3 fields)", t_prompt)
    check("quest lifecycle over a real socket (echo bridge + transcripts)", t_socket_lifecycle)
    check("island unlock quest + Professor advisor", t_islands_advisor)
    check("world reactions (TV news/quiz, awe, Dad's Frontier guide)", t_reactions)
    check("extract_addresses.py stays in sync with the hook", t_extract_addresses)
    check("Windows encoding safety (file-open calls, non-ASCII round-trip)", t_windows_encoding)
    check("watchdog restarts and stops at limit", t_watchdog)
    check("hardened persona JSON parser (fences, prose, dict-literal, raises)",
          t_persona_json_parser)
    check("persona failure always logs a reason (never a silent '...')",
          t_persona_failure_is_never_silent)
    check("eval harness metrics M1-M4 (spec section 7 unit tests)", t_eval_metrics)
    # These five append to PASS/SKIP themselves (they print their own richer
    # pass lines and can skip when lupa is absent), so they are wrapped in a
    # catcher that records a failure WITHOUT re-appending a pass.
    #
    # BUG this fixes: they used to be called bare. When
    # t_encode_unmapped_glyphs raised -- which it did, on the CHARMAP
    # load-path bug -- the process died on an uncaught traceback, the three
    # tests after it never ran and were never reported, and the
    # "N passed, M failed" summary line and the exit code were never reached
    # at all. A suite that stops counting at the first Lua failure hides
    # exactly the failures it exists to surface.
    for _fn in (t_lua, t_encode_unmapped_glyphs, t_hook_choice,
                t_hook_skip_and_trainer_flag, t_trainer_defeated_tristate):
        try:
            _fn()
        except Exception as _e:
            FAIL.append((_fn.__name__, _e))
            print(f"  [FAIL] {_fn.__name__}: {type(_e).__name__}: {_e}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
    sys.exit(1 if FAIL else 0)
