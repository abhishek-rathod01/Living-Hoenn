"""Unit tests for the eval metrics.

Spec section 7: "Every rule in M2 needs a unit test with one true positive and
one true negative." That is the floor, not the ceiling -- M1a, M1b, M3 and M4
get the same treatment, because a detector nobody tested is exactly the
failure mode (a confident output nobody checked) that produced the
trainer_defeated bug this harness exists to catch.

Run standalone:      python eval/test_metrics.py
Run via the suite:   python run_all_tests.py   (t_eval_metrics)
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _d in (_HERE, os.path.join(_HERE, "metrics"), os.path.join(_REPO, "bridge")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import constraints
import grounding
import repetition
import skip
import species_lexicon


# --------------------------------------------------------------- M1 grounding
def test_m1a_possession_true_positive():
    """NPC claims a Pokemon it does not own -> violation."""
    gt = {"trainer_party": [{"species": "Magnemite", "level": 14}],
          "player_party_species": ["Blaziken"]}
    r = grounding.score_line("My Gyarados will crush you!", gt)
    assert r["m1a_violation"] is True, r
    assert r["m1a_violations"] == ["Gyarados"], r


def test_m1a_possession_true_negative():
    """NPC claims a Pokemon it genuinely owns -> no violation."""
    gt = {"trainer_party": [{"species": "Magnemite", "level": 14}],
          "player_party_species": ["Blaziken"]}
    r = grounding.score_line("My Magnemite never backs down!", gt)
    assert r["m1a_violation"] is False, r


def test_m1a_players_party_does_not_excuse_an_npc_claim():
    """The asymmetry that matters: the NPC saying 'my Blaziken' is fabricated
    even when the PLAYER carries a Blaziken."""
    gt = {"trainer_party": [], "player_party_species": ["Blaziken"]}
    r = grounding.score_line("My Blaziken and I train every day.", gt)
    assert r["m1a_violation"] is True, r


def test_m1a_mention_without_possession_is_not_a_violation():
    """Naming a species is not claiming it. This is the precision guard --
    without it M1a collapses into M1b and stops meaning anything."""
    gt = {"trainer_party": [], "player_party_species": []}
    r = grounding.score_line("A wild Zigzagoon ran past here earlier.", gt)
    assert r["m1a_violation"] is False, r
    assert "Zigzagoon" in r["mentions"], r


def test_m1b_reports_out_of_context_without_calling_it_a_violation():
    gt = {"trainer_party": [{"species": "Magnemite"}],
          "player_party_species": ["Blaziken"]}
    r = grounding.score_line("I saw a Wailmer out past the pier.", gt)
    assert r["m1b_out_of_context"] == ["Wailmer"], r
    assert r["m1a_violation"] is False, r


def test_m1_species_constant_and_display_name_are_the_same_species():
    """Ground truth arrives as SPECIES_* constants from the mined table, but
    generated text uses display names. If these did not normalise together,
    every trainer would look like a violation."""
    gt = {"trainer_party": [{"species": "SPECIES_MAGNEMITE"}],
          "player_party_species": []}
    r = grounding.score_line("My Magnemite is ready.", gt)
    assert r["m1a_violation"] is False, r


# ------------------------------------------------------------- M2 constraints
def test_m2_fourth_wall_true_positive():
    r = constraints.check_line("I am just a language model, after all.")
    assert r["fourth_wall"] is True, r


def test_m2_fourth_wall_true_negative():
    r = constraints.check_line("The sea breeze here is lovely this morning.")
    assert r["fourth_wall"] is False, r


def test_m2_fourth_wall_matches_on_word_boundaries_not_substrings():
    """'gamer' contains 'game'; a bare substring test would fire on it.
    Guards the rule against the precision floor in spec section 4."""
    assert constraints.check_line("What a charming little town.")["fourth_wall"] is False
    assert constraints.check_line("This game is hard.")["fourth_wall"] is True


def test_m2_offers_transaction_true_positive():
    r = constraints.check_line("Here, take this Oran Berry for your journey.")
    assert r["offers_transaction"] is True, r


def test_m2_offers_transaction_true_negative():
    r = constraints.check_line("I sell nothing here, I only watch the boats.")
    assert r["offers_transaction"] is False, r


def test_m2_role_break_true_positive():
    r = constraints.check_line("You look strong! Let's battle!", archetype="healer")
    assert r["role_break"] is True, r


def test_m2_role_break_true_negative():
    r = constraints.check_line("Your Pokemon are fully healed. Do take care!",
                               archetype="healer")
    assert r["role_break"] is False, r


def test_m2_role_break_stays_silent_when_the_archetype_is_unknown():
    """A rule that fires on missing data manufactures violations."""
    r = constraints.check_line("Let's battle!", archetype=None)
    assert r["role_break"] is False, r
    assert r["role_checked"] is False, r


def test_m2_role_break_does_not_fire_on_a_role_allowed_to_battle():
    r = constraints.check_line("Let's battle!", archetype="triathlete")
    assert r["role_break"] is False, r


def test_m2_format_true_positive():
    r = constraints.check_line('"He smiles." ' + " ".join(["word"] * 40))
    assert r["format"] is True, r
    assert any(p.startswith("not_under_35_words") for p in r["format_problems"]), r
    assert "quotation_marks" in r["format_problems"], r


def test_m2_format_true_negative():
    r = constraints.check_line("Careful on the cycling road, it gets busy.")
    assert r["format"] is False, r


def test_m2_format_word_cap_boundary_is_under_not_at():
    """The prompt says 'under 35 words', so 35 is already a violation and 34
    is not. An off-by-one here silently excuses every line on the cap."""
    assert constraints.check_line(" ".join(["w"] * 34))["format"] is False
    assert constraints.check_line(" ".join(["w"] * 35))["format"] is True


def test_m2_non_ascii_true_positive():
    """The confirmed live failure from HANDOVER_5 section 3.1: qwen3 emitted
    Chinese characters mid-line and the render truncated."""
    r = constraints.check_line("Did you need anything from the 货架 today?")
    assert r["non_ascii"] is True, r


def test_m2_non_ascii_true_negative():
    """Characters the Emerald charmap genuinely renders must not be flagged --
    the accented e in POKeMON and the ellipsis appear throughout the mined
    vanilla text itself."""
    r = constraints.check_line("Your POKéMON look healthy… take care now.")
    assert r["non_ascii"] is False, r


# --------------------------------------------------------------- M3 repetition
def test_m3_near_duplicate_is_flagged():
    """The Nurse Joy case from HANDOVER_3 section 2 item 3, which is the
    known-positive this threshold is calibrated against."""
    a = "Your Pokemon look to be in peak condition today."
    b = "Your Pokemon look to be in peak condition right now."
    r = repetition.score_line(b, [a])
    assert r["repetitive"] is True, r


def test_m3_distinct_lines_are_not_flagged():
    a = "Your Pokemon look to be in peak condition today."
    b = "The ferry to Dewford leaves at noon, don't be late."
    r = repetition.score_line(b, [a])
    assert r["repetitive"] is False, r


def test_m3_first_line_has_no_history_and_scores_zero():
    r = repetition.score_line("Anything at all.", [])
    assert r["max_similarity"] == 0.0 and r["compared_against"] == 0, r


def test_m3_only_the_last_k_lines_are_compared():
    """A line identical to one 5 turns ago is outside the k=3 window."""
    old = "Your Pokemon look to be in peak condition today."
    hist = [old, "one", "two", "three"]
    r = repetition.score_line(old, hist)
    assert r["compared_against"] == 3, r
    assert r["repetitive"] is False, r


def test_m3_short_lines_still_compare():
    """Lines shorter than the 4-gram size must not silently score 0.0."""
    r = repetition.score_line("Hello there.", ["Hello there."])
    assert r["max_similarity"] == 1.0, r


# -------------------------------------------------------------------- M4 skip
def test_m4_sign_returning_the_sentinel_is_correct():
    r = skip.score_line(skip.SKIP_SENTINEL, {"expect_skip": True})
    assert r["correct"] is True and r["applicable"] is True, r


def test_m4_sign_returning_dialogue_is_incorrect():
    r = skip.score_line("Nice weather we're having!", {"expect_skip": True})
    assert r["correct"] is False, r


def test_m4_non_sign_is_not_counted_as_a_skip_case():
    r = skip.score_line("Nice weather!", {"expect_skip": False})
    assert r["applicable"] is False, r
    agg = skip.aggregate([r])
    assert agg["n_skip_cases"] == 0 and agg["skip_correct_rate"] is None, agg


def test_m4_a_talking_npc_that_skipped_is_flagged_separately():
    r = skip.score_line(skip.SKIP_SENTINEL, {"expect_skip": False})
    assert r["false_skip"] is True, r


def test_m4_sentinel_is_imported_from_the_bridge_not_redeclared():
    """If the bridge changes its sentinel, M4 must follow it, not keep
    scoring against a stale copy."""
    import dialogue_bridge_server
    assert skip.SKIP_SENTINEL is dialogue_bridge_server.SKIP_SENTINEL


# ----------------------------------------------------------------- the lexicon
def test_lexicon_is_not_empty_and_normalises_both_nidoran_genders():
    assert len(species_lexicon.SPECIES_NAMES) > 300
    f = species_lexicon.normalize("SPECIES_NIDORAN_F")
    m = species_lexicon.normalize("SPECIES_NIDORAN_M")
    assert f and m and f != m, (f, m)


def test_lexicon_rejects_non_species():
    assert species_lexicon.normalize("Cycling Road") is None


# -------------------------------------------------------------------- runner
def run_all():
    tests = [(n, o) for n, o in sorted(globals().items())
             if n.startswith("test_") and callable(o)]
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
    return len(tests), failed


if __name__ == "__main__":
    total, failed = run_all()
    for name, err in failed:
        print(f"  [FAIL] {name}: {err}")
    print(f"{total - len(failed)}/{total} eval metric tests passed")
    sys.exit(1 if failed else 0)
