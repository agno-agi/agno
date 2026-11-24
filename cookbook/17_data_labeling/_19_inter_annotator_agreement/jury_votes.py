"""
Inter-Annotator Agreement - Jury Votes
======================================

The same agreement metrics applied to dpo_jury-shaped preference votes.
Three instruction framings of one judge model vote a/b/tie on eight
pairwise preference pairs that are deliberately skewed: in six of the
eight, answer "a" is constructed to be clearly better. Label skew is the
point - it is exactly the regime where raw agreement flatters a jury,
because chance agreement on the majority label is already high.

One juror recuses on one pair (a deterministic stand-in for dpo_jury's
self-preference recusal), leaving a missing cell in the vote matrix.
Krippendorff's alpha handles the missing cell natively by counting only
pairable values; Fleiss' kappa cannot, so it is computed on the
complete-rows subset only.
"""

from collections import Counter
from itertools import combinations
from typing import Literal, Optional

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Vote(BaseModel):
    winner: Literal["a", "b", "tie"] = Field(
        ..., description="Which answer better addresses the prompt, or tie"
    )


# ---------------------------------------------------------------------------
# Create Agents - three juror framings of one judge model
# ---------------------------------------------------------------------------
# Jurors run at temperature=0 so disagreement measures the framings, not
# sampling noise. Votes can still drift with model updates and serving-side
# nondeterminism.
terse_juror = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions="Pick the better answer to the prompt: a, b, or tie.",
    output_schema=Vote,
)

rubric_juror = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=(
        "Pick the more correct answer; ties are allowed. Never reward "
        "length, hedging, or a confident tone. When both answers are "
        "correct, always prefer the shorter one - extra background, "
        "caveats, or teaching content in the longer answer must not win."
    ),
    output_schema=Vote,
)

persona_juror = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=(
        "You are a teaching assistant grading two candidate answers. "
        "Correctness comes first, but between two correct answers always "
        "prefer the more instructive one - correct extra background and "
        "caveats are a plus, never a penalty. Ties are allowed."
    ),
    output_schema=Vote,
)

JURORS: dict[str, Agent] = {
    "terse": terse_juror,
    "rubric": rubric_juror,
    "persona": persona_juror,
}


# ---------------------------------------------------------------------------
# Pairs - deliberately skewed: "a" is clearly better in six of eight
# ---------------------------------------------------------------------------
PAIRS: list[dict] = [
    dict(
        id="fib",
        prompt="Write an iterative Python fib(n), with fib(0) = 0.",
        a="def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
        b="def fib(n):\n    a, b = 0, 1\n    for _ in range(n - 1):\n        a, b = b, a + b\n    return b",
    ),
    dict(
        id="sum35",
        prompt="How many integers from 1 to 1000 are divisible by 3 or 5?",
        a="467: floor(1000/3)=333, floor(1000/5)=200, subtract floor(1000/15)=66 counted twice: 333+200-66=467.",
        b="533: there are 333 multiples of 3 and 200 multiples of 5, giving 533 integers divisible by 3 or 5.",
    ),
    dict(
        id="round",
        prompt="In Python 3, what is round(2.5) and why?",
        a="2. Python 3 uses banker's rounding: halves go to the nearest even integer, so 2.5 rounds down to 2.",
        b="3. Python rounds .5 up, as in standard arithmetic, so round(2.5) is 3.",
    ),
    dict(
        id="tcp",
        prompt="Does TCP preserve message boundaries across send()/recv()?",
        a="No. TCP is a byte stream: one send may arrive across several recvs, so applications must frame messages.",
        b="Yes. Each send() maps to one recv() on the peer, so boundaries survive while the connection stays open.",
    ),
    dict(
        id="reset",
        prompt="What does git reset --soft HEAD~1 do?",
        a="Moves the branch back one commit; the undone commit's changes remain staged; working tree untouched.",
        b="Moves the branch back one commit and unstages those changes, leaving them as edits in your working tree.",
    ),
    dict(
        id="sky",
        prompt="Why is the sky blue?",
        a="Air molecules scatter sunlight; shorter blue wavelengths scatter far more, so scattered blue dominates.",
        b="The sky reflects the blue of the oceans, which is why it looks grey far inland on overcast days.",
    ),
    # The two pairs below are designed to be close: both answers are correct,
    # and the rubric juror's always-prefer-shorter rule points the opposite
    # way from the persona juror's always-prefer-more-instructive rule.
    dict(
        id="http404",
        prompt="What does HTTP status 404 mean?",
        a="The server cannot find the requested resource.",
        b="404 Not Found: the server cannot find the requested resource. It does not say whether the absence is temporary or permanent; typical causes are mistyped URLs or deleted pages.",
    ),
    dict(
        id="float",
        prompt="What is 0.1 + 0.2 in Python?",
        a="0.30000000000000004",
        b="0.30000000000000004. Floats are binary fractions, so 0.1 and 0.2 cannot be stored exactly; use math.isclose for comparisons or decimal.Decimal for money.",
    ),
]

# Deterministic simulated recusal: in dpo_jury a juror sits out any pair
# written by its own model family (self-preference recusal). All three
# framings here share one underlying model, so we hard-code one recusal to
# reproduce the same missing-cell shape in the vote matrix.
RECUSALS: set[tuple[str, str]] = {("persona", "fib")}


# ---------------------------------------------------------------------------
# Agreement Metrics - pure stdlib
# ---------------------------------------------------------------------------
# The matrix is pairs x jurors; a cell may be None (recused juror). Only
# krippendorff_alpha, raw_agreement, and cohen_kappa handle missing cells;
# fleiss_kappa requires complete rows.
Matrix = list[list[Optional[str]]]


def raw_agreement(matrix: Matrix) -> float:
    # Observed (raw) agreement: for each item, the fraction of juror pairs
    # that cast the same vote, averaged over items:
    #   P_o = (1/N) * sum_i [ agreeing_pairs_i / total_pairs_i ]
    # Items with fewer than two votes are skipped.
    per_item = []
    for row in matrix:
        values = [v for v in row if v is not None]
        if len(values) < 2:
            continue
        pairs = list(combinations(values, 2))
        agree = sum(1 for x, y in pairs if x == y)
        per_item.append(agree / len(pairs))
    if not per_item:
        raise ValueError("raw_agreement needs at least one item with two votes")
    return sum(per_item) / len(per_item)


def fleiss_kappa(matrix: Matrix) -> float:
    # Fleiss' kappa (equal raters per item, no missing cells):
    #   n_ik  = number of jurors casting vote k on item i
    #   n     = jurors per item, N = items
    #   P_i   = (sum_k n_ik^2 - n) / (n * (n - 1))   per-item agreement
    #   P_bar = (1/N) * sum_i P_i                    observed agreement
    #   p_k   = sum_i n_ik / (N * n)                 vote proportions
    #   P_e   = sum_k p_k^2                          chance agreement
    #   kappa = (P_bar - P_e) / (1 - P_e)
    # Fleiss' kappa has no native missing-data handling: callers must pass
    # the complete-rows subset (see __main__ below).
    if any(v is None for row in matrix for v in row):
        raise ValueError("fleiss_kappa requires complete rows (no missing cells)")
    n = len(matrix[0])
    categories = sorted({v for row in matrix for v in row if v is not None})
    p_bar = 0.0
    totals = {c: 0 for c in categories}
    for row in matrix:
        counts = {c: row.count(c) for c in categories}
        for c in categories:
            totals[c] += counts[c]
        p_bar += (sum(counts[c] ** 2 for c in categories) - n) / (n * (n - 1))
    p_bar /= len(matrix)
    total = len(matrix) * n
    p_e = sum((totals[c] / total) ** 2 for c in categories)
    if p_e == 1.0:
        return 1.0 if p_bar == 1.0 else 0.0
    return (p_bar - p_e) / (1 - p_e)


def krippendorff_alpha(matrix: Matrix) -> float:
    # Krippendorff's alpha for nominal data; missing cells allowed.
    # 1. Keep only units (items) with >= 2 pairable (non-missing) values -
    #    the recused cell simply contributes no pairs.
    # 2. Coincidence matrix: within each unit with m_u values, every ordered
    #    pair of values (c, k) from different jurors adds 1/(m_u - 1) to o_ck.
    # 3. Marginals: n_c = sum_k o_ck, n = sum_c n_c.
    # 4. Nominal disagreement (delta = 1 when c != k, else 0):
    #      D_o = sum_{c != k} o_ck
    #      D_e = sum_{c != k} n_c * n_k / (n - 1)
    #    alpha = 1 - D_o / D_e
    categories = sorted({v for row in matrix for v in row if v is not None})
    o = {c: {k: 0.0 for k in categories} for c in categories}
    for row in matrix:
        values = [v for v in row if v is not None]
        m = len(values)
        if m < 2:
            continue
        for i, c in enumerate(values):
            for j, k in enumerate(values):
                if i != j:
                    o[c][k] += 1 / (m - 1)
    n_c = {c: sum(o[c].values()) for c in categories}
    n = sum(n_c.values())
    d_o = sum(o[c][k] for c in categories for k in categories if c != k)
    d_e = sum(
        n_c[c] * n_c[k] / (n - 1) for c in categories for k in categories if c != k
    )
    if d_e == 0.0:
        return 1.0 if d_o == 0.0 else 0.0
    return 1 - d_o / d_e


def cohen_kappa(a: list[Optional[str]], b: list[Optional[str]]) -> float:
    # Cohen's kappa for two jurors, over the items both voted on:
    #   p_o   = fraction of items with identical votes
    #   p_e   = sum_k p_a(k) * p_b(k)   (product of per-juror marginals)
    #   kappa = (p_o - p_e) / (1 - p_e)
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n == 0:
        raise ValueError("cohen_kappa needs at least one co-voted item")
    p_o = sum(1 for x, y in pairs if x == y) / n
    categories = sorted({v for pair in pairs for v in pair})
    p_e = sum(
        (sum(1 for x, _ in pairs if x == c) / n)
        * (sum(1 for _, y in pairs if y == c) / n)
        for c in categories
    )
    if p_e == 1.0:
        return 1.0 if p_o == 1.0 else 0.0
    return (p_o - p_e) / (1 - p_e)


# ---------------------------------------------------------------------------
# Self Check - assert each metric against hand-derived cases, including a
# missing cell for alpha
# ---------------------------------------------------------------------------
def self_check() -> None:
    # Case 1: perfect agreement with mixed votes -> every metric is 1.0.
    perfect: Matrix = [["a"] * 3, ["b"] * 3, ["a"] * 3, ["tie"] * 3]
    assert abs(raw_agreement(perfect) - 1.0) < 1e-9
    assert abs(fleiss_kappa(perfect) - 1.0) < 1e-9
    assert abs(krippendorff_alpha(perfect) - 1.0) < 1e-9
    assert (
        abs(cohen_kappa([r[0] for r in perfect], [r[1] for r in perfect]) - 1.0) < 1e-9
    )

    # Case 2: 3 jurors x 3 items with one missing cell, derived by hand.
    #   item 1: a, a, None   item 2: a, b, b   item 3: b, b, b
    # Raw agreement per item: 1 (one pair, agrees), 1/3, 1 -> mean 7/9.
    # Alpha: coincidences o[a][a]=2 (item 1, m=2, weight 1), item 2 (m=3,
    #   weight 1/2) adds o[a][b]=o[b][a]=1 and o[b][b]=1, item 3 adds
    #   o[b][b]=3. Marginals n_a=3, n_b=5, n=8. D_o=2,
    #   D_e=2*(3*5)/(8-1)=30/7, alpha = 1 - 2/(30/7) = 8/15.
    # Fleiss on the complete rows (items 2 and 3): P_i = 1/3 and 1, so
    #   P_bar = 2/3; totals a=1, b=5 of 6 -> P_e = 1/36 + 25/36 = 13/18;
    #   kappa = (2/3 - 13/18) / (1 - 13/18) = -0.2 (below-chance agreement).
    missing: Matrix = [["a", "a", None], ["a", "b", "b"], ["b", "b", "b"]]
    assert abs(raw_agreement(missing) - 7 / 9) < 1e-9
    assert abs(krippendorff_alpha(missing) - 8 / 15) < 1e-9
    complete = [row for row in missing if None not in row]
    assert abs(fleiss_kappa(complete) - (-0.2)) < 1e-9


# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
def cast_vote(juror: Agent, pair: dict) -> str:
    prompt = (
        f"PROMPT:\n{pair['prompt']}\n\nANSWER a:\n{pair['a']}\n\nANSWER b:\n{pair['b']}"
    )
    for _ in range(3):  # retry schema breaks, never coerce
        run: RunOutput = juror.run(prompt)
        if isinstance(run.content, Vote):
            return run.content.winner
    raise RuntimeError("juror failed to produce a valid Vote")


if __name__ == "__main__":
    self_check()
    print("self_check passed: metrics match the hand-derived values")

    matrix: Matrix = []
    for pair in PAIRS:
        row: list[Optional[str]] = []
        for name, juror in JURORS.items():
            if (name, pair["id"]) in RECUSALS:
                print(
                    f"recusal: {name} sits out '{pair['id']}' "
                    "(simulated self-preference recusal)"
                )
                row.append(None)
            else:
                row.append(cast_vote(juror, pair))
        matrix.append(row)

    juror_names = list(JURORS)
    print()
    print("pair x juror vote matrix:")
    print(f"{'pair':<10}" + "".join(f"{name:>10}" for name in juror_names))
    for pair, row in zip(PAIRS, matrix):
        cells = "".join(f"{(v if v is not None else '--'):>10}" for v in row)
        print(f"{pair['id']:<10}{cells}")

    votes_cast = [v for row in matrix for v in row if v is not None]
    distribution = Counter(votes_cast)
    a_share = distribution["a"] / len(votes_cast)
    print()
    print(f"vote distribution: {dict(distribution)} ({a_share:.0%} of votes are 'a')")

    complete_rows = [row for row in matrix if all(v is not None for v in row)]
    raw = raw_agreement(matrix)
    alpha = krippendorff_alpha(matrix)
    fleiss = fleiss_kappa(complete_rows)
    print()
    print(f"raw agreement      : {raw:.3f}  (pairable votes, all {len(matrix)} pairs)")
    print(f"krippendorff alpha : {alpha:.3f}  (missing cell handled natively)")
    print(
        f"fleiss kappa       : {fleiss:.3f}  (no native missing-data handling: "
        f"computed on the {len(complete_rows)}/{len(matrix)} complete rows only)"
    )
    for (i, a_name), (j, b_name) in combinations(enumerate(juror_names), 2):
        cols_a = [row[i] for row in matrix]
        cols_b = [row[j] for row in matrix]
        pairwise = cohen_kappa(cols_a, cols_b)
        print(f"cohen kappa        : {pairwise:.3f}  ({a_name} vs {b_name})")

    print()
    print(
        f"under label skew ({a_share:.0%} of votes are 'a'), raw agreement "
        f"{raw:.3f} collapses to alpha {alpha:.3f} once chance agreement on "
        "the majority label is removed"
    )
    print(
        "a jury passing an agreement >= 0.75 filter can still carry far less "
        "beyond-chance signal than the raw number suggests; report alpha "
        "next to raw agreement"
    )

    n_recused = sum(1 for row in matrix for v in row if v is None)
    unanimous = sum(1 for row in matrix if len({v for v in row if v is not None}) == 1)
    print()
    print(
        f"{len(PAIRS)} pairs x {len(JURORS)} jurors: {len(votes_cast)} votes "
        f"cast, {n_recused} recused, {unanimous} pairs unanimous among "
        "sitting jurors"
    )
