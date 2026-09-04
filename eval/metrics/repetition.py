"""M3 -- repetition (spec section 3).

Max Jaccard similarity on 4-grams between a generated line and the previous
k=3 lines from the SAME NPC key. Reports the mean and the fraction above a
threshold.

The known-positive case this is calibrated against is real, not invented:
HANDOVER_3 section 2 item 3 records Nurse Joy producing four near-identical
"your Pokemon look in peak condition" variants across consecutive talks. If a
threshold does not flag that case it is set too high.

Per-NPC, not global: two different NPCs saying similar things is a world with
a consistent voice; one NPC saying the same thing four times is the defect.

Spec section 7: no metric may call the model under test. Pure text analysis.
"""

import re

K = 3          # how many previous lines from the same NPC to compare against
N = 4          # n-gram size
THRESHOLD = 0.5   # spec section 3: "start at 0.5; calibrate"


def _tokens(text):
    """Lowercased word tokens, punctuation dropped.

    Punctuation is dropped deliberately: "Your Pokemon look great!" and "Your
    Pokemon look great." are the same line for this metric's purposes, and
    keeping punctuation would let a model evade the metric by re-punctuating.
    """
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def ngrams(text, n=N):
    """set of n-grams. Falls back to the whole token tuple when the line is
    shorter than n -- otherwise every short line has an empty n-gram set and
    scores 0.0 similarity against everything, which would silently exempt
    exactly the short repetitive lines this metric is meant to catch."""
    toks = _tokens(text)
    if not toks:
        return set()
    if len(toks) < n:
        return {tuple(toks)}
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def jaccard(a, b):
    """|A n B| / |A u B|. Two empty sets are 0.0, not 1.0: an empty line is
    not 'identical' to another empty line in any sense worth reporting."""
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def score_line(line, previous_lines, n=N, k=K):
    """Per-line M3: max similarity against the previous `k` lines.

    `previous_lines` is that NPC's history, most recent LAST (the order
    PersonaStore.recent_lines returns). Only the last k are compared.
    """
    recent = list(previous_lines or [])[-k:]
    grams = ngrams(line, n)
    sims = [jaccard(grams, ngrams(p, n)) for p in recent]
    best = max(sims, default=0.0)
    return {
        "max_similarity": best,
        "compared_against": len(recent),
        "similarities": sims,
        "repetitive": best >= THRESHOLD,
    }


def score_sequence(lines, n=N, k=K):
    """Score a whole per-NPC conversation in order. The first line has no
    history and scores 0.0, which is correct rather than missing data."""
    out, history = [], []
    for line in lines:
        out.append(score_line(line, history, n=n, k=k))
        history.append(line)
    return out


def aggregate(results, threshold=THRESHOLD):
    results = list(results)
    n = len(results)
    if not n:
        return {"n": 0, "mean_max_similarity": None, "repetition_rate": None}
    sims = [r["max_similarity"] for r in results]
    over = sum(1 for s in sims if s >= threshold)
    # Lines with no history to compare against cannot be repetitive; report
    # them so a low rate driven by an empty history is visible rather than
    # flattering.
    no_history = sum(1 for r in results if r["compared_against"] == 0)
    return {
        "n": n,
        "threshold": threshold,
        "mean_max_similarity": sum(sims) / n,
        "max_max_similarity": max(sims),
        "repetition_count": over,
        "repetition_rate": over / n,
        "lines_with_no_history": no_history,
    }
