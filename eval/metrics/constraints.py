"""M2 -- constraint violations (spec section 3).

Four independent rules. Each reports on its own and is never merged into a
single "constraint score": the rules have different precision, and spec
section 4 requires each to be calibrated and individually tightened or dropped
below ~0.8 precision. Averaging them first would make that impossible.

  fourth_wall         breaks the fiction (says "AI", "prompt", "the player")
  offers_transaction  promises an item/trade/quest the bridge cannot deliver
  role_break          acts outside the pinned archetype (healer offering
                      to battle) -- minimum viable version only, on purpose
  format              breaks the prompt's own stated output contract
  non_ascii           emits characters the Emerald charmap cannot render

non_ascii is not in the spec's original table. It was added per HANDOVER_5
section 3.1, which records a confirmed live failure: qwen3 emitted Chinese
characters for "shelf" and the line rendered with a gap and a truncated tail.
The spec's own note calls for it as "a free eval metric ... trivial, 100%
precision, no calibration needed, and it measures something confirmed to
occur."

Spec section 7: no metric may call the model under test. Pure text analysis.
"""

import re

# --------------------------------------------------------------- fourth wall
# Spec section 3 lists these terms verbatim. Two of them -- "player" and
# "game" -- are the reason this rule needs calibration before its numbers are
# trusted: an NPC can innocently say "a game of tag", and Emerald's own
# vanilla script text says "TRAINER" constantly. Word-boundary matched, never
# substring, so "gameplay" matches but "gamer"/"endgame" do not leak in via a
# bare `in` test.
_FOURTH_WALL_TERMS = (
    "ai", "model", "language model", "prompt", "token", "llm", "emulator",
    "screen", "player", "game", "clipboard", "notes", "simulation",
)
_FOURTH_WALL = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in
                      sorted(_FOURTH_WALL_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)

# ---------------------------------------------------------------- transaction
# The dialogue-only bridge emits no actions, so any offer is a false promise.
# Patterns are the spec's, plus the two obvious inflections of each.
_TRANSACTION = re.compile(
    r"("
    r"i'?ll\s+give\s+you"
    r"|i\s+will\s+give\s+you"
    r"|i'?ll\s+hand\s+you"
    r"|bring\s+me\b"
    r"|in\s+exchange\b"
    r"|trade\s+with\s+me\b"
    r"|i'?ll\s+trade\s+you"
    r"|here,?\s+take\s+(this|these|it)"
    r"|take\s+this\s+(as|for)\b"
    r"|if\s+you\s+(bring|fetch|find)\s+me\b"
    r")", re.IGNORECASE)

# ----------------------------------------------------------------- role break
# Deliberately minimum viable, per the spec: "Keep the rule set small and
# precise rather than broad and wrong." Exactly one archetype is checked --
# a healer offering to battle -- because that is the one this project has a
# concrete pinned-persona case for (Nurse Joy, archetype "healer").
_BATTLE_OFFER = re.compile(
    r"("
    r"\bbattle\s+me\b"
    r"|\blet'?s\s+battle\b"
    r"|\bi'?ll\s+battle\s+you\b"
    r"|\bi\s+challenge\s+you\b"
    r"|\bfight\s+me\b"
    r"|\bwant\s+to\s+battle\b"
    r"|\bhow\s+about\s+a\s+battle\b"
    r")", re.IGNORECASE)

_NON_BATTLING_ROLES = ("healer", "nurse", "shop clerk", "clerk")

# ---------------------------------------------------------------------- format
#: The prompt's own stated cap, read out of the bridge rather than assumed.
#: bridge/dialogue_bridge_server.py line 180 says, verbatim:
#:   "- Output ONE spoken line, under 35 words, no quotation marks, no
#:    narration, no asterisks."
#: "under 35" makes 35 itself a violation, so the comparison below is >=, not
#: >. Getting that boundary wrong in the lenient direction would silently
#: excuse every line that lands exactly on the cap.
MAX_WORDS = 35

# Charmap-legitimate non-ASCII that must NOT count as leakage. These are the
# characters Emerald genuinely renders and that the mined vanilla text itself
# contains -- the accented e in "POKeMON", the ellipsis, curly quotes, the
# Nidoran gender symbols, and the gendered-address glyphs.
_LEGIT_NON_ASCII = set("éÉ…‘’“”♀♂"
                       "×÷→↑↓←")


#: Emerald text placeholders: {PLAYER}, {KUN}, {STR_VAR_1}, {COLOR RED}, ...
#: These are game control codes, not prose. Verified as a real false positive
#: rather than a hypothetical: an eval run scored the vanilla Devon Scope line
#: "{PLAYER} used the DEVON SCOPE..." as a fourth_wall break, because the
#: placeholder contains the literal word "player". Stripping them costs
#: nothing -- no model is supposed to emit one -- and removes a whole class of
#: violations attributed to text Nintendo wrote.
_PLACEHOLDER = re.compile(r"\{[^}]*\}")


def strip_placeholders(text):
    return _PLACEHOLDER.sub(" ", text or "")


def _words(text):
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def check_line(line, archetype=None):
    """Per-line M2 result: one boolean per rule, plus the evidence for each.

    `archetype` is the NPC's pinned role from npc_profiles.json. None means
    unknown, and role_break then reports False rather than guessing -- a rule
    that fires on missing data manufactures violations, which is worse than a
    rule that stays silent.
    """
    raw = line or ""
    # Word count uses the raw line (a placeholder still occupies a word on
    # screen); every pattern rule uses the stripped form.
    text = strip_placeholders(raw)
    words = _words(raw)

    fw = sorted({m.group(1).lower() for m in _FOURTH_WALL.finditer(text)})
    tx = sorted({m.group(1).lower() for m in _TRANSACTION.finditer(text)})

    role = (archetype or "").strip().lower()
    role_hits = []
    if role and any(r in role for r in _NON_BATTLING_ROLES):
        role_hits = sorted({m.group(1).lower() for m in _BATTLE_OFFER.finditer(text)})

    fmt = []
    if len(words) >= MAX_WORDS:
        fmt.append(f"not_under_{MAX_WORDS}_words({len(words)})")
    if '"' in text or "“" in text or "”" in text:
        fmt.append("quotation_marks")
    if "*" in text:
        fmt.append("asterisks")
    if "\n" in raw:
        fmt.append("multiple_lines")
    # Narration: stage direction in brackets, or a trailing third-person beat.
    if re.search(r"[\[\(][^\)\]]*\b(smiles|laughs|nods|sighs|waves|grins)\b",
                 text, re.IGNORECASE):
        fmt.append("narration")

    leaked = sorted({c for c in raw
                     if ord(c) > 127 and c not in _LEGIT_NON_ASCII})

    return {
        "fourth_wall": bool(fw), "fourth_wall_terms": fw,
        "offers_transaction": bool(tx), "transaction_phrases": tx,
        "role_break": bool(role_hits), "role_break_phrases": role_hits,
        "role_checked": bool(role and any(r in role for r in _NON_BATTLING_ROLES)),
        "format": bool(fmt), "format_problems": fmt,
        "non_ascii": bool(leaked), "non_ascii_chars": leaked,
        "word_count": len(words),
        "any_violation": bool(fw or tx or role_hits or fmt or leaked),
    }


RULES = ("fourth_wall", "offers_transaction", "role_break", "format",
         "non_ascii")


def aggregate(results):
    """Corpus-level M2, one rate per rule. Never averaged into one number --
    see this module's docstring."""
    results = list(results)
    n = len(results)
    if not n:
        return {"n": 0}
    out = {"n": n}
    for rule in RULES:
        hits = sum(1 for r in results if r[rule])
        out[f"{rule}_count"] = hits
        out[f"{rule}_rate"] = hits / n
    out["any_violation_count"] = sum(1 for r in results if r["any_violation"])
    out["any_violation_rate"] = out["any_violation_count"] / n
    # role_break's denominator is not n: it can only fire on entries whose
    # archetype was actually checked. Reporting it over n would understate it.
    checked = sum(1 for r in results if r["role_checked"])
    out["role_break_checked_n"] = checked
    out["role_break_rate_of_checked"] = (
        sum(1 for r in results if r["role_break"]) / checked if checked else None)
    return out
