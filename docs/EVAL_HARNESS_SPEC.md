# Living Hoenn — Evaluation Harness Specification

**Purpose:** turn every quality claim in this project from anecdote into
measurement. This is Track A1 of the master plan and the prerequisite for
everything else in that track.

**Intended reader:** a Claude Code session, and you reviewing its work.
Point it at this file plus `CLAUDE.md` and `LIVING_HOENN_HANDOVER_3.md`.

---

## 1. Why this exists — state it in the code's own docstring

The `trainer_defeated` bug is the argument for this harness. A Lua idiom on
line 732 caused unknown trainer status to be reported as `false`, so the
bridge injected *"This trainer has NOT been defeated yet"* into prompts for
every trainer outside the lookup table. The grounding layer — the component
the credibility of the whole system rests on — was emitting fabricated facts,
and the 16-test suite didn't catch it because the tests cover plumbing, not
outputs.

**Design consequence:** this harness measures what the system *says*, not
whether its functions return. Those are different things and only the first
one matters for quality.

---

## 2. The single most important design decision

**A frozen evaluation set.** Without it, two runs are not comparable and no
ablation is possible.

`eval/dataset.py` builds a fixed corpus of evaluation contexts, written once
to `eval/eval_set.json` and then **never regenerated non-deterministically**
(seed it; commit it).

Each entry is one synthetic-but-realistic bridge request plus its known
ground truth:

{
  "id": "eval_0042",
  "context": {
    "npc_id": 7, "map_group": 24, "map_num": 7,
    "original_line": "I love berries more than anything.",
    "party": ["Blaziken:45", "Mudkip:5"],
    "badges": 5, "game_clear": 0,
    "trainer_defeated": null
  },
  "ground_truth": {
    "is_trainer": false,
    "trainer_party": [],
    "player_party_species": ["BLAZIKEN", "MUDKIP"],
    "archetype_hint": "berry farmer",
    "map_name": "Route 110",
    "vanilla_lines": ["I love berries more than anything."]
  }
}

**How to build it:** enumerate the 103 object events from
`extraction/npc_dialogue_table.json`, cross them with a small fixed set of
player states (early/mid/late badges, champion flag on/off, ordinary party,
legendary party, empty-ish party). Target **~200 entries**. Stratify so
trainers, non-trainer NPCs, signs (`npc_id == 0`), and service NPCs are all
represented. Signs matter: the correct output for `npc_id == 0` is the skip
sentinel, and "did it correctly do nothing" is a measurable property.

`transcripts.jsonl` is useful as a *secondary* corpus for measuring what
already happened, but it is not a controlled eval set — it has no fixed
composition and can't support ablations. Build both; report on the frozen set.

---

## 3. Metrics

Each returns a per-line result and an aggregate. All programmatic except M6.

### M1 — Grounding violation rate (primary metric)

The one metric that justifies the whole project's architecture. Split into two
sub-measures because they have very different precision:

**M1a — Possession claims (high precision, harder to detect).**
Did the NPC claim to *own or use* a Pokémon that isn't in their real party?
Detect possessive/ownership constructions near a species mention: `my <S>`,
`I have (a|an|my) <S>`, `I('ll| will) use my <S>`, `my partner <S>`,
`I raised (a|an|my) <S>`, `<S> and I`. Then check `<S>` against
`ground_truth.trainer_party`.

**M1b — Out-of-context species mentions (low precision, easy to detect).**
Any species named that appears in neither the trainer's party nor the player's
party. Report separately and **do not treat as a violation on its own** — NPCs
can legitimately mention wild Pokémon. It's a useful drift signal, not an error
count.

Requires a species lexicon. `lua/species_names.lua` is already generated from
the game's own `gSpeciesNames`; generate the Python equivalent from the same
source rather than hand-listing. Match case-insensitively on word boundaries.

### M2 — Constraint violations

Rule set, each rule reporting independently:

| Rule | Detects |
|---|---|
| fourth_wall | ai, model, language model, prompt, token, llm, emulator, screen, player, game, clipboard, notes, simulation |
| offers_transaction | quest/item/trade offers — dialogue-only bridge emits no actions, so any offer is a false promise. Patterns: "I'll give you", "bring me", "in exchange", "trade with", "here, take" |
| role_break | archetype from `npc_profiles.json` vs. content. Minimum viable version: a `healer` archetype offering to battle. Keep the rule set small and precise rather than broad and wrong. |
| format | over 35 words (the prompt's own stated cap), quotation marks, asterisks, narration, multiple lines |

### M3 — Repetition

Max Jaccard similarity on 4-grams between a generated line and the previous
`k=3` lines from the same NPC key. Report mean and the fraction above a
threshold (start at 0.5; calibrate against the Nurse Joy four-variant case,
which is your known-positive example).

### M4 — Skip correctness

For `npc_id == 0` entries, did the bridge return the skip sentinel and did the
hook leave the buffer untouched? Binary, and it directly covers the `cbcc26c`
fix. This one can be exercised without the emulator by asserting on the bridge
reply; the hook half still needs live verification.

### M5 — Latency

Full distribution per backend: p50, p95, max. Not a mean. Report token counts
alongside.

### M6 — LLM-as-judge (secondary, clearly labelled as least reliable)

Rubric scoring 1–5 on: in-character consistency, naturalness, and whether the
line plausibly belongs in a 2004 GBA game. **Use a hosted model (Gemini or
Groq) so the judge is independent of the model under test** — never judge
qwen3 with qwen3. Report separately from the programmatic metrics and never
average them together.

---

## 4. Calibrating the harness itself

This is the step that makes it credible, and it's the project's own
two-independent-ways standard applied to the measuring instrument.

A detector you haven't validated is exactly the failure mode that produced the
`trainer_defeated` bug — a confident output nobody checked.

**Procedure:**
1. Sample 50 lines from `transcripts.jsonl`.
2. **You** hand-label each against M1a and M2 — violation or not. Store as
   `eval/calibration_labels.json`. This is an hour of your time and it is not
   optional.
3. Run the harness against the same 50.
4. Report precision, recall, and F1 *for the harness*.
5. Any rule below ~0.8 precision gets tightened or dropped. A noisy rule is
   worse than no rule, because it corrupts every subsequent comparison.

Publish these numbers in the README alongside the results. "My grounding
detector has 0.91 precision and 0.84 recall on a hand-labelled set" is a much
stronger claim than any raw violation rate, and it's the kind of thing an FYP
examiner looks for specifically.

---

## 5. Structure

eval/
  dataset.py              # builds eval_set.json from the mined table (seeded)
  eval_set.json           # frozen, committed
  metrics/
    grounding.py          # M1a, M1b
    constraints.py        # M2
    repetition.py         # M3
    skip.py               # M4
    latency.py            # M5
    judge.py              # M6
  species_lexicon.py      # generated from pokeemerald, do not hand-edit
  calibration_labels.json # your hand labels
  run_eval.py              # entry point
  runs/
    2026-09-08_ollama_qwen3-8b_grounded.json
    2026-09-08_ollama_qwen3-8b_baseline.json
  REPORT.md               # generated summary table

`run_eval.py` takes `--backend`, `--model`, and a `--config` naming the
ablation condition, replays the frozen eval set, and writes one timestamped
JSON plus a markdown summary. Every run must record backend, model, all
sampling parameters, git commit hash, and eval-set hash — otherwise results
aren't reproducible and the comparisons are worthless.

---

## 6. The ablation grid (Track A2, once the harness exists)

| Condition | Persona pinned | Mined original_line | Trainer grounding | Chatter history |
|---|---|---|---|---|
| C0 baseline | no | no | no | no |
| C1 persona only | yes | no | no | no |
| C2 + vanilla line | yes | yes | no | no |
| C3 + grounding | yes | yes | yes | no |
| C4 full (current) | yes | yes | yes | yes |

Five runs over 200 entries. This answers, with numbers, every design question
the project has ever asserted without evidence — and it's roughly a day's work
once A1 exists.

**Be prepared for an unwelcome result.** It's entirely possible C2 ≈ C4, i.e.
that the vanilla line does most of the work and the elaborate grounding adds
little. If that's what the data says, report it. That finding is more valuable
than a flattering one, and reporting it is the thing that makes every other
number you publish believable.

---

## 7. Rules for the implementing session

- Do **not** touch `lua/`, the bridge's generation path, or `extraction/`.
  This is additive: a new `eval/` package and nothing else.
- No metric may call the model under test.
- Species lexicon is **generated**, never hand-written (project rule 6).
- Every rule in M2 needs a unit test with one true positive and one true
  negative.
- `run_all_tests.py` green before and after.
- Atomic commits, BUG/FIX/verification style.
- Show the eval-set builder's output on 5 sample entries before generating all
  200 — the same show-me-real-output-first discipline that worked for the
  decomp-mining pilot.

---

## 8. Done when

- `eval_set.json` exists, is frozen and committed, ~200 stratified entries.
- `python eval/run_eval.py --backend ollama --model qwen3:8b` produces a report.
- Calibration numbers exist for M1a and M2, measured against your own labels.
- The five-condition ablation grid has been run and the results are in
  `REPORT.md`.
- The README carries three numbers it didn't have before: grounding violation
  rate, repetition rate, and latency p50/p95.

At that point the sentence *"I don't know how good the dialogue is"* stops
being true, and that is the single biggest change available to this project.
