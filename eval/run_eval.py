"""eval/run_eval.py -- entry point (spec section 5).

Replays the frozen eval set against one backend/model/condition and writes a
timestamped JSON run plus a markdown summary.

    python eval/run_eval.py --backend echo                        # no model
    python eval/run_eval.py --backend ollama --model qwen3:8b
    python eval/run_eval.py --backend ollama --model qwen3:8b --config C2
    python eval/run_eval.py --backend groq --limit 20             # smoke test

NOT RUN AGAINST A REAL BACKEND YET. This module was written in a cloud
session with no Ollama server and no emulator; only the --backend echo path
has been exercised. A real measurement is a local-machine task. Nothing this
file produces should be described as a live or in-game result.

REPRODUCIBILITY (spec section 5): every run records backend, model, sampling
parameters, git commit hash and the eval-set hash. A run whose _eval_set_hash
differs from another's was measured against a different corpus and the two
numbers must not be compared -- compare_runs() refuses to do it.

METRICS: M1-M4 only. M5 (latency) and M6 (LLM-as-judge) are specified but not
implemented -- M5 needs a live backend to time, M6 needs a hosted judge model
independent of the model under test. Wall-clock per request IS recorded here,
so an M5 implementation has the raw numbers to work from, but no latency
distribution is reported, because timings taken on a machine with no model
server would be meaningless.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _d in (_HERE, os.path.join(_HERE, "metrics"), os.path.join(_REPO, "bridge")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import constraints                      # noqa: E402  M2
import dataset                          # noqa: E402
import grounding                        # noqa: E402  M1
import repetition                       # noqa: E402  M3
import skip                             # noqa: E402  M4

import dialogue_bridge_server as bridge  # noqa: E402
import persona_engine                    # noqa: E402

#: handle_request()'s neutral non-answer. The bridge spells this literal in
#: four places and exports no constant for it; if it ever gains one, import
#: that instead of this copy.
NEUTRAL_FALLBACK = "..."

RUNS_DIR = os.path.join(_HERE, "runs")
REPORT_PATH = os.path.join(_HERE, "REPORT.md")


# ------------------------------------------------------------------ conditions
# Spec section 6. Each condition switches OFF part of the grounding so the
# ablation can attribute quality to a specific component.
CONDITIONS = {
    "C0": dict(persona=False, vanilla_line=False, trainer_grounding=False, history=False),
    "C1": dict(persona=True,  vanilla_line=False, trainer_grounding=False, history=False),
    "C2": dict(persona=True,  vanilla_line=True,  trainer_grounding=False, history=False),
    "C3": dict(persona=True,  vanilla_line=True,  trainer_grounding=True,  history=False),
    "C4": dict(persona=True,  vanilla_line=True,  trainer_grounding=True,  history=True),
}
DEFAULT_CONDITION = "C4"   # what the bridge actually does today


def _mined_for(condition, full_mined):
    """The mined table as this condition should see it.

    C0/C1 hide the mined table entirely, which removes both the vanilla lines
    and the trainer grounding in one step -- they come from the same source.
    C2 keeps the vanilla lines but must hide the trainer party, so it passes a
    copy with every trainerbattle block stripped. Copying rather than mutating
    matters: the module-level MINED is shared, and mutating it would silently
    contaminate every later condition in the same process.
    """
    cfg = CONDITIONS[condition]
    if not cfg["vanilla_line"] and not cfg["trainer_grounding"]:
        return {"npcs": {}, "_maps": {}}
    if cfg["trainer_grounding"]:
        return full_mined
    stripped = {"_maps": full_mined.get("_maps", {}), "npcs": {}}
    for key, entry in (full_mined.get("npcs") or {}).items():
        e = dict(entry)
        e["trainerbattle"] = None
        stripped["npcs"][key] = e
    return stripped


class _EvalStore:
    """A PersonaStore stand-in that keeps everything in memory.

    The real PersonaStore writes npc_profiles.json, which is the user's live
    pinned-persona file and is gitignored precisely because it is precious
    ("lose it and every NPC gets a new soul"). An eval run must never touch
    it. This class has the same four methods handle_request() calls and
    persists nothing.
    """

    def __init__(self, designer_enabled=True, history_enabled=True):
        self.cards, self.lines = {}, {}
        self.designer_enabled = designer_enabled
        self.history_enabled = history_enabled

    def get_or_create(self, key, designer, game_state):
        if not self.designer_enabled:
            # C0: no pinned persona at all. A minimal valid card keeps the
            # chatter path alive so C0 measures "no persona", not "no reply".
            return {"archetype": "villager", "temperament": "neutral",
                    "quirk": "none", "greeting": "Hello."}
        if key not in self.cards:
            self.cards[key] = designer(game_state)
        return self.cards[key]

    def recent_lines(self, key):
        return self.lines.get(key, []) if self.history_enabled else []

    def record_line(self, key, line):
        self.lines.setdefault(key, []).append(line)


def make_backend(backend, model):
    """(persona_designer, chatter) for one backend. Mirrors serve()'s own
    dispatch rather than reimplementing it, so a backend added to the bridge
    needs one line here and no other change."""
    if backend == "echo":
        return bridge.echo_persona, bridge.echo_chatter
    if backend == "ollama":
        return bridge.make_llm(model)
    if backend == "gemini":
        return bridge.make_gemini(model)
    if backend == "groq":
        return bridge.make_groq(model)
    raise ValueError(f"unknown backend {backend!r}")


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_REPO,
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        # A run from an exported tarball has no git metadata. Recording
        # "unknown" is honest; guessing or crashing is not.
        return "unknown"


# ----------------------------------------------------------------------- run
def run(backend="echo", model=None, condition=DEFAULT_CONDITION, limit=None,
        eval_set=None):
    """Replay the frozen set. Returns the full run payload."""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; "
                         f"choose from {sorted(CONDITIONS)}")
    payload = eval_set or dataset.load()
    entries = payload["entries"][:limit] if limit else payload["entries"]
    cfg = CONDITIONS[condition]

    designer, chatter = make_backend(backend, model)
    store = _EvalStore(designer_enabled=cfg["persona"],
                       history_enabled=cfg["history"])
    mined = _mined_for(condition, bridge.MINED)

    rows = []
    for entry in entries:
        gs = dict(entry["context"])
        # trainer_defeated is tri-state: None means the hook could not
        # determine it and OMITS the field on the wire. Passing an explicit
        # None instead of omitting the key would re-create the exact
        # conflation that 8838b36 fixed.
        if gs.get("trainer_defeated") is None:
            gs.pop("trainer_defeated", None)

        history_before = list(store.recent_lines(bridge.npc_key(gs)))
        t0 = time.perf_counter()
        try:
            reply = bridge.handle_request(gs, store, designer, chatter, mined=mined)
            error = None
        except Exception as e:
            # One entry failing must not lose the other 199. Recorded as an
            # error row so the failure is visible in the run file rather than
            # quietly shrinking the denominator.
            reply, error = "", f"{type(e).__name__}: {e}"
        elapsed = time.perf_counter() - t0

        gt = entry["ground_truth"]
        card = store.cards.get(bridge.npc_key(gs)) or {}
        archetype = card.get("archetype") if isinstance(card, dict) else None

        # A passthrough is the bridge echoing the vanilla line back unchanged.
        # Compared after the same whitespace collapse _passthrough() applies,
        # so the comparison matches what the bridge actually emitted.
        collapsed = " ".join(str(gs.get("original_line") or "").split())
        passthrough = bool(collapsed) and reply == collapsed

        rows.append({
            "id": entry["id"],
            "stratum": entry["stratum"],
            "player_state": entry["player_state"],
            "reply": reply,
            "error": error,
            "passthrough": passthrough,
            "elapsed_s": round(elapsed, 4),
            "m1": grounding.score_line(reply, gt),
            "m2": constraints.check_line(reply, archetype=archetype),
            "m3": repetition.score_line(reply, history_before),
            "m4": skip.score_line(reply, gt),
        })

    # Only genuinely GENERATED prose belongs in the M1-M3 denominators.
    # Three reply kinds must be excluded, and the third was found by running
    # the harness rather than by reasoning about it:
    #   - the skip sentinel (signs) -- judged by M4, not M1-M3
    #   - error rows -- no reply to score
    #   - passthrough replies, where the bridge echoes the vanilla line back
    #     unchanged for an object/item-ball/gift box. An eval run scored the
    #     vanilla Devon Scope text as a fourth_wall violation, because the
    #     bridge had returned Nintendo's own words. Attributing that to the
    #     model is simply false, and it is the same class of mistake as
    #     scoring the sentinel.
    #   - the neutral "..." fallback, which handle_request returns when the
    #     persona designer fails, a backend call raises, or a passthrough has
    #     no vanilla line to echo. Also not model output. A full echo run
    #     produced 22 of these, and leaving them in silently pulled every
    #     violation rate toward zero by padding the denominator with lines
    #     that cannot violate anything.
    # A reply-kind census over a full 200-entry echo run accounts for all of
    # them with nothing left over: 144 generated + 30 sentinel + 22 fallback
    # + 4 passthrough. NEUTRAL_FALLBACK is imported-by-value from the
    # bridge's own literal below.
    generated = [r for r in rows
                 if r["reply"] and r["reply"] != bridge.SKIP_SENTINEL
                 and r["reply"] != NEUTRAL_FALLBACK
                 and not r["error"] and not r["passthrough"]]

    return {
        "_schema": 1,
        "backend": backend,
        "model": model,
        "condition": condition,
        "condition_flags": cfg,
        "sampling": _sampling_params(backend),
        "git_commit": git_commit(),
        "eval_set_hash": payload.get("_eval_set_hash"),
        "eval_set_size": len(entries),
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "counts": {
            "total": len(rows),
            "generated_prose": len(generated),
            "skip_sentinel": sum(1 for r in rows if r["reply"] == bridge.SKIP_SENTINEL),
            "passthrough": sum(1 for r in rows if r["passthrough"]),
            "neutral_fallback": sum(1 for r in rows
                                    if r["reply"] == NEUTRAL_FALLBACK),
            "errors": sum(1 for r in rows if r["error"]),
        },
        "aggregates": {
            "M1_grounding": grounding.aggregate(r["m1"] for r in generated),
            "M2_constraints": constraints.aggregate(r["m2"] for r in generated),
            "M3_repetition": repetition.aggregate(r["m3"] for r in generated),
            "M4_skip": skip.aggregate(r["m4"] for r in rows),
            "M5_latency": None,   # not implemented -- see this module's docstring
            "M6_judge": None,     # not implemented -- see this module's docstring
        },
        "rows": rows,
    }


def _sampling_params(backend):
    """The sampling settings the bridge actually uses, recorded so a run is
    reproducible. Read from the bridge's own call sites, not restated from
    memory; if the bridge changes them this must be updated with it."""
    if backend == "echo":
        return {"note": "canned replies, no model, no sampling"}
    return {"temperature_persona": 0.7, "temperature_chatter": 0.85,
            "num_ctx": 2048, "think": False,
            "_source": "bridge/dialogue_bridge_server.py make_llm()"}


def save(result, runs_dir=RUNS_DIR):
    os.makedirs(runs_dir, exist_ok=True)
    day = result["timestamp"][:10]
    model = (result["model"] or "none").replace(":", "-").replace("/", "-")
    name = f"{day}_{result['backend']}_{model}_{result['condition']}.json"
    path = os.path.join(runs_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def summarise(result):
    """Markdown summary for one run."""
    a = result["aggregates"]
    m1, m2, m3, m4 = (a["M1_grounding"], a["M2_constraints"],
                      a["M3_repetition"], a["M4_skip"])

    def pct(x):
        return "n/a" if x is None else f"{x * 100:.1f}%"

    lines = [
        f"### {result['backend']} / {result['model'] or 'no model'} / "
        f"{result['condition']}",
        "",
        f"- commit `{result['git_commit'][:12]}`, eval set "
        f"`{result['eval_set_hash']}`, {result['eval_set_size']} entries",
        f"- {result['counts']['generated_prose']} generated lines scored, "
        f"{result['counts']['skip_sentinel']} skip sentinels, "
        f"{result['counts']['passthrough']} vanilla passthroughs, "
        f"{result['counts']['neutral_fallback']} neutral fallbacks, "
        f"{result['counts']['errors']} errors",
        "  (M1-M3 score generated prose only; sentinels and passthroughs are "
        "text no model wrote)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| M1a grounding violation rate | {pct(m1.get('m1a_violation_rate'))} |",
        f"| M1b out-of-context mentions / line | "
        f"{m1.get('m1b_mean_per_line') if m1.get('m1b_mean_per_line') is None else round(m1['m1b_mean_per_line'], 3)} |",
        f"| M2 fourth wall | {pct(m2.get('fourth_wall_rate'))} |",
        f"| M2 offers transaction | {pct(m2.get('offers_transaction_rate'))} |",
        f"| M2 role break (of checked) | {pct(m2.get('role_break_rate_of_checked'))} |",
        f"| M2 format | {pct(m2.get('format_rate'))} |",
        f"| M2 non-ASCII leakage | {pct(m2.get('non_ascii_rate'))} |",
        f"| M3 repetition rate (>= {m3.get('threshold')}) | {pct(m3.get('repetition_rate'))} |",
        f"| M3 mean max similarity | "
        f"{m3.get('mean_max_similarity') if m3.get('mean_max_similarity') is None else round(m3['mean_max_similarity'], 3)} |",
        f"| M4 skip correctness | {pct(m4.get('skip_correct_rate'))} "
        f"({m4.get('n_skip_cases')} cases) |",
        f"| M5 latency | not implemented (needs a live backend) |",
        f"| M6 LLM-as-judge | not implemented (needs a hosted judge model) |",
        "",
        "M4 measures the bridge reply only. The hook's buffer-untouched half "
        "needs live emulator verification and is not measured here.",
        "",
    ]
    return "\n".join(lines)


def compare_runs(results):
    """Ablation table across conditions. Refuses to compare runs measured
    against different corpora -- that comparison is meaningless and printing
    it anyway is how a harness starts lying."""
    hashes = {r["eval_set_hash"] for r in results}
    if len(hashes) > 1:
        raise ValueError(
            "refusing to compare runs from different eval sets: "
            f"{sorted(hashes)}. Regenerating eval_set.json invalidates "
            "comparability with every run recorded against the old hash.")
    head = ("| Condition | M1a violation | M2 any | M3 repetition | M4 skip |\n"
            "|---|---|---|---|---|")
    rows = []
    for r in sorted(results, key=lambda x: x["condition"]):
        a = r["aggregates"]

        def pct(x):
            return "n/a" if x is None else f"{x * 100:.1f}%"
        rows.append(
            f"| {r['condition']} | {pct(a['M1_grounding'].get('m1a_violation_rate'))} "
            f"| {pct(a['M2_constraints'].get('any_violation_rate'))} "
            f"| {pct(a['M3_repetition'].get('repetition_rate'))} "
            f"| {pct(a['M4_skip'].get('skip_correct_rate'))} |")
    return "\n".join([head] + rows)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="echo",
                    choices=("echo", "ollama", "gemini", "groq"),
                    help="echo needs no model and is the only path exercised "
                         "so far -- see the module docstring")
    ap.add_argument("--model", default=None)
    ap.add_argument("--config", "--condition", dest="condition",
                    default=DEFAULT_CONDITION, choices=sorted(CONDITIONS),
                    help="ablation condition from spec section 6")
    ap.add_argument("--limit", type=int, default=None,
                    help="replay only the first N entries (smoke test); a "
                         "limited run is NOT comparable to a full one")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    if args.backend != "echo" and not args.model:
        args.model = {"ollama": "qwen3:8b", "gemini": "gemini-3.5-flash",
                      "groq": "llama-3.3-70b-versatile"}[args.backend]

    result = run(backend=args.backend, model=args.model,
                 condition=args.condition, limit=args.limit)
    print(summarise(result))
    if args.limit:
        print(f"NOTE: --limit {args.limit} was used. This run covers a subset "
              "and must not be compared against a full run.")
    if not args.no_save:
        print("run written to", save(result))


if __name__ == "__main__":
    main()
