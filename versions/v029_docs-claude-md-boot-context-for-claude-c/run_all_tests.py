"""
run_all_tests.py -- one command to verify the whole project, no emulator, no LLM.

    python run_all_tests.py

Run this FIRST on any new machine. If everything passes, the entire Python
layer (quest engine, personas, bridge, wire protocol) is proven working, and
the Lua files are syntax-checked if `lupa` is installed (pip install lupa --
optional). Exit code 0 = all good.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

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
        proc = subprocess.Popen(
            [sys.executable, "-u", "quest_bridge_server.py", "--echo",
             "--port", str(port), "--store", os.path.join(d, "q.json"),
             "--profiles", os.path.join(d, "p.json")],
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
        finally:
            proc.terminate()
            try:
                proc.communicate(timeout=3)
            except Exception:
                proc.kill()


# ----------------------------------------------------------- lua syntax check
def t_lua():
    try:
        import lupa
    except ImportError:
        SKIP.append("lua syntax (pip install lupa to enable)")
        print("  [SKIP] lua syntax check -- `pip install lupa` to enable")
        return
    lua = lupa.LuaRuntime()
    for f in ("mgba_hook.lua", "party_reader.lua", "species_names.lua", "charmap.lua"):
        res = lua.eval("function(s) local fn, e = load(s); return fn, e end")(open(f).read())
        fn = res[0] if isinstance(res, tuple) else res
        assert fn, f"{f} has a syntax error"
    PASS.append("lua syntax")
    print("  [PASS] lua syntax (all 4 files compile)")


if __name__ == "__main__":
    print("== Pokemon LLM Bridge: full test suite ==")
    check("items table (source-verified IDs, Master Ball denylisted)", t_items)
    check("quest engine (gate, lifecycle, persistence, no double reward)", t_quest_engine)
    check("persona layer (validation, cache-once, fallback chain)", t_persona)
    check("dialogue prompt building (v3 fields)", t_prompt)
    check("quest lifecycle over a real socket (echo bridge)", t_socket_lifecycle)
    t_lua()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
    sys.exit(1 if FAIL else 0)
