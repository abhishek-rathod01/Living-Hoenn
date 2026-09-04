"""eval/metrics -- the programmatic metrics from docs/EVAL_HARNESS_SPEC.md.

M1 grounding.py   M2 constraints.py   M3 repetition.py   M4 skip.py

M5 (latency) and M6 (LLM-as-judge) are specified but NOT implemented here:
M5 needs a live backend to time and M6 needs a hosted judge model, neither of
which is reachable from the cloud session that built this package. They are
local-machine work. See docs/EVAL_HARNESS_SPEC.md sections 3 and 5.

Hard rule from spec section 7: no metric may call the model under test.
Everything in this package is pure text analysis over an already-generated
line plus its ground truth.
"""
