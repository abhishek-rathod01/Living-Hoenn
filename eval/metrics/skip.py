"""M4 -- skip correctness (spec section 3).

For npc_id == 0 entries (signs, TVs, PCs), did the bridge return the skip
sentinel? Binary, and it directly covers the cbcc26c item-1 fix.

SCOPE, stated plainly because the distinction is the whole point of this
project's verification discipline: this measures the BRIDGE half only. The
hook half -- that mgba_hook.lua leaves gStringVar4 and sTextPrinters untouched
on receiving the sentinel -- cannot be measured without a running emulator,
and is NOT covered here. A green M4 means "the bridge said the right thing",
never "the sign rendered correctly in-game". The spec says the same:
"the hook half still needs live verification".

Spec section 7: no metric may call the model under test.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE = os.path.join(_REPO, "bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

# Imported, never re-declared. A local copy of the literal would silently stop
# matching the moment the bridge changed its sentinel, and M4 would then score
# a real regression as a pass.
from dialogue_bridge_server import SKIP_SENTINEL  # noqa: E402


def score_line(reply, ground_truth):
    """Per-line M4.

    Entries that are not skip cases return applicable=False and are excluded
    from the aggregate denominator, rather than counted as passes -- counting
    them would dilute the rate towards 1.0 with entries that never tested
    anything.
    """
    expect_skip = bool((ground_truth or {}).get("expect_skip"))
    got_skip = (reply or "").strip() == SKIP_SENTINEL
    return {
        "applicable": expect_skip,
        "expected_skip": expect_skip,
        "got_skip": got_skip,
        "correct": (got_skip == expect_skip),
        # A non-sign that skipped is its own failure: the NPC silently said
        # nothing when it should have spoken. Tracked separately because it
        # has a completely different cause from a sign that failed to skip.
        "false_skip": got_skip and not expect_skip,
    }


def aggregate(results):
    results = list(results)
    skip_cases = [r for r in results if r["applicable"]]
    n = len(skip_cases)
    out = {
        "n_skip_cases": n,
        "n_total": len(results),
        "false_skips_on_non_signs": sum(1 for r in results if r["false_skip"]),
    }
    if not n:
        out["skip_correct_rate"] = None
        return out
    correct = sum(1 for r in skip_cases if r["correct"])
    out["skip_correct"] = correct
    out["skip_correct_rate"] = correct / n
    out["_scope"] = ("bridge reply only -- the hook's buffer-untouched half "
                     "needs live emulator verification and is NOT measured here")
    return out
