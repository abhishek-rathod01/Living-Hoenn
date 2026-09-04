"""M1 -- grounding violation rate (spec section 3, the primary metric).

This is the metric that justifies the project's architecture. It is split in
two because the two halves have very different precision, and reporting them
as one number would launder a noisy signal into a headline figure:

  M1a  possession claims        -- high precision, harder to detect. A real
                                   violation: the NPC claims to own or use a
                                   Pokemon that is not in their actual party.
  M1b  out-of-context mentions  -- low precision, easy to detect. A species
                                   named that is in neither the trainer's
                                   party nor the player's. NOT a violation on
                                   its own: an NPC may legitimately mention a
                                   wild Pokemon. Drift signal, not error count.

Spec section 7: no metric may call the model under test. This module is pure
text analysis.
"""

import re

from species_lexicon import find_mentions, normalize

#: Possession constructions from spec section 3, M1a. `{S}` is filled with the
#: species alternation at match time. Kept deliberately small and precise --
#: spec section 4 requires any rule below ~0.8 precision to be tightened or
#: dropped, because a noisy rule corrupts every subsequent comparison.
_POSSESSION_TEMPLATES = (
    r"\bmy\s+(?:own\s+|dear\s+|trusty\s+|beloved\s+)?{S}\b",
    r"\bi\s+have\s+(?:a|an|my|two|three)\s+{S}\b",
    r"\bi(?:'ll|\s+will)\s+use\s+my\s+{S}\b",
    r"\bmy\s+partner\s*,?\s*{S}\b",
    r"\bi\s+raised\s+(?:a|an|my)\s+{S}\b",
    r"\b{S}\s+and\s+i\b",
)

# A possessive can sit a few words before the species ("my faithful old
# Magnemite"). This bounded gap is why the templates use \s+ plus an optional
# adjective group rather than a greedy .*: an unbounded gap would match "my
# badges are nothing next to your Blaziken", which is not a possession claim
# by the NPC at all.


def _possession_hits(text, species):
    """Which of `species` this line claims possession of."""
    hits = []
    for name in species:
        s_pat = re.escape(name)
        for tpl in _POSSESSION_TEMPLATES:
            if re.search(tpl.replace("{S}", s_pat), text, re.IGNORECASE):
                hits.append(name)
                break
    return hits


def _owned(ground_truth):
    """Canonical species the speaking NPC genuinely owns."""
    out = set()
    for mon in ground_truth.get("trainer_party") or []:
        canon = normalize(mon.get("species") if isinstance(mon, dict) else mon)
        if canon:
            out.add(canon)
    return out


def _player(ground_truth):
    out = set()
    for name in ground_truth.get("player_party_species") or []:
        canon = normalize(name)
        if canon:
            out.add(canon)
    return out


def score_line(line, ground_truth):
    """Per-line M1 result.

    Returns a dict with, for one generated line:
      m1a_violations   species falsely claimed as the NPC's own
      m1a_violation    bool -- the headline per-line result
      m1b_out_of_ctx   species in neither party (reported, never a violation)
      mentions         every species named, for auditing a disputed score

    A line with no species mention scores clean on both. That is correct and
    it is also why M1 alone cannot say a system is good -- a model that never
    names a Pokemon scores a perfect grounding rate. Read M1 alongside M2's
    format rule and M3, never on its own.
    """
    text = line or ""
    mentioned = sorted({n for n, _, _ in find_mentions(text)})
    owned, player = _owned(ground_truth), _player(ground_truth)

    claimed = _possession_hits(text, mentioned)
    # A possession claim is only a violation when the NPC does not own it.
    # Note the deliberate asymmetry: the PLAYER's party does not excuse an
    # NPC's possession claim. "My Blaziken" said by an NPC whose party is
    # empty is fabricated even when the player happens to carry a Blaziken.
    violations = sorted(n for n in claimed if n not in owned)

    out_of_ctx = sorted(n for n in mentioned if n not in owned and n not in player)

    return {
        "mentions": mentioned,
        "m1a_claimed": sorted(set(claimed)),
        "m1a_violations": violations,
        "m1a_violation": bool(violations),
        "m1b_out_of_context": out_of_ctx,
        "m1b_count": len(out_of_ctx),
    }


def aggregate(results):
    """Corpus-level M1. `results` is an iterable of score_line() dicts."""
    results = list(results)
    n = len(results)
    if not n:
        return {"n": 0, "m1a_violation_rate": None, "m1b_mean_per_line": None}
    viol = sum(1 for r in results if r["m1a_violation"])
    return {
        "n": n,
        "m1a_violations": viol,
        "m1a_violation_rate": viol / n,
        "m1b_total_out_of_context": sum(r["m1b_count"] for r in results),
        "m1b_mean_per_line": sum(r["m1b_count"] for r in results) / n,
        "lines_naming_no_species": sum(1 for r in results if not r["mentions"]),
    }
