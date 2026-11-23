"""
Inter-Annotator Agreement - Basic
=================================

Three instruction framings of the same sentiment-labeling task act as three
independent annotators over one set of texts. The resulting item x rater
matrix feeds four agreement metrics implemented in pure stdlib - raw
agreement, Fleiss' kappa, Krippendorff's alpha (nominal), and pairwise
Cohen's kappa - and every item without a unanimous label is routed to a
review list.

Raw agreement alone flatters a labeling pipeline; the chance-corrected
metrics tell you whether the guideline is actually reproducible.
"""

from itertools import combinations
from typing import Literal, Optional

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class SentimentLabel(BaseModel):
    label: Literal["positive", "negative", "neutral"] = Field(
        ..., description="The assigned sentiment label"
    )


# ---------------------------------------------------------------------------
# Create Agents - three genuinely different framings of one guideline
# ---------------------------------------------------------------------------
# Judges run at temperature=0 so disagreement comes from the instructions,
# not sampling noise. Labels can still drift with model updates and
# serving-side nondeterminism.
terse_rater = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions="Label the sentiment of the text: positive, negative, or neutral.",
    output_schema=SentimentLabel,
)

rubric_instructions = """\
Label the sentiment of the text as positive, negative, or neutral.

Rules:
- Sarcasm and irony: label the intended sentiment, not the literal words.
- Mixed sentiment: when the text contains both clearly positive and clearly
  negative aspects, label neutral - the aspects cancel.
- Faint or heavily qualified praise ("fine, I guess") is neutral, not
  positive.
- Purely factual or descriptive statements are neutral.
"""

rubric_rater = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=rubric_instructions,
    output_schema=SentimentLabel,
)

persona_instructions = """\
You are a crowd annotator on a product-review sentiment project. Judge each
text by its bottom line for a shopper: if it would nudge a shopper toward
buying, label it positive; if it would make a shopper hesitate, label it
negative. Reserve neutral for texts with no purchase signal either way,
such as purely factual statements.
"""

persona_rater = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions=persona_instructions,
    output_schema=SentimentLabel,
)

RATERS: dict[str, Agent] = {
    "terse": terse_rater,
    "rubric": rubric_rater,
    "persona": persona_rater,
}


# ---------------------------------------------------------------------------
# Items - 8 clear cases plus 4 designed to be genuinely ambiguous
# ---------------------------------------------------------------------------
ITEMS: list[str] = [
    "Absolutely love this keyboard - the keys feel amazing and it looks great.",
    "The package arrived crushed and the item inside was shattered.",
    "The manual says to charge the device for four hours before first use.",
    "Best purchase I have made all year, worth every penny.",
    "Terrible support - three emails over two weeks and not a single reply.",
    "The box contains the charger, a cable, and a quick start guide.",
    "Setup took two minutes and everything worked on the first try.",
    "It stopped working after two days and the seller refuses a refund.",
    # Ambiguous: sarcasm - literally positive words, negative intent.
    "Oh great, another update that wipes all my settings. Just what I always wanted.",
    # Ambiguous: balanced mixed sentiment - two positives, two negatives.
    "Gorgeous screen and superb speakers, but the battery dies by lunch and the hinge already creaks.",
    # Ambiguous: faint praise - mildly positive words, no endorsement.
    "Honestly, better than I expected. I would not buy it again, but it does the job.",
    # Ambiguous: ambivalence - the author cannot decide.
    "Three stars. Some days I love it, some days I want to throw it out the window.",
]


# ---------------------------------------------------------------------------
# Agreement Metrics - pure stdlib
# ---------------------------------------------------------------------------
# The matrix is items x raters; a cell may be None (missing rating). Only
# krippendorff_alpha and raw_agreement handle missing cells; fleiss_kappa
# requires complete rows.
Matrix = list[list[Optional[str]]]


def raw_agreement(matrix: Matrix) -> float:
    # Observed (raw) agreement: for each item, the fraction of rater pairs
    # that assigned the same label, averaged over items:
    #   P_o = (1/N) * sum_i [ agreeing_pairs_i / total_pairs_i ]
    # Items with fewer than two ratings are skipped.
    per_item = []
    for row in matrix:
        values = [v for v in row if v is not None]
        m = len(values)
        if m < 2:
            continue
        pairs = list(combinations(values, 2))
        agree = sum(1 for x, y in pairs if x == y)
        per_item.append(agree / len(pairs))
    if not per_item:
        raise ValueError("raw_agreement needs at least one item with two ratings")
    return sum(per_item) / len(per_item)


def fleiss_kappa(matrix: Matrix) -> float:
    # Fleiss' kappa (equal raters per item, no missing cells):
    #   n_ik  = number of raters assigning category k to item i
    #   n     = raters per item, N = items
    #   P_i   = (sum_k n_ik^2 - n) / (n * (n - 1))   per-item agreement
    #   P_bar = (1/N) * sum_i P_i                    observed agreement
    #   p_k   = sum_i n_ik / (N * n)                 category proportions
    #   P_e   = sum_k p_k^2                          chance agreement
    #   kappa = (P_bar - P_e) / (1 - P_e)
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
    # 1. Keep only units (items) with >= 2 pairable (non-missing) values.
    # 2. Coincidence matrix: within each unit with m_u values, every ordered
    #    pair of values (c, k) from different raters adds 1/(m_u - 1) to o_ck.
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
    # Cohen's kappa for two raters, over the items both rated:
    #   p_o   = fraction of items with identical labels
    #   p_e   = sum_k p_a(k) * p_b(k)   (product of per-rater marginals)
    #   kappa = (p_o - p_e) / (1 - p_e)
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n == 0:
        raise ValueError("cohen_kappa needs at least one co-rated item")
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
# Self Check - assert each metric against hand-computable cases
# ---------------------------------------------------------------------------
def self_check() -> None:
    # Case 1: perfect agreement with mixed categories -> every metric is 1.0.
    perfect: Matrix = [
        ["positive"] * 3,
        ["negative"] * 3,
        ["neutral"] * 3,
        ["positive"] * 3,
    ]
    assert abs(raw_agreement(perfect) - 1.0) < 1e-9
    assert abs(fleiss_kappa(perfect) - 1.0) < 1e-9
    assert abs(krippendorff_alpha(perfect) - 1.0) < 1e-9
    col_a = [row[0] for row in perfect]
    col_b = [row[1] for row in perfect]
    assert abs(cohen_kappa(col_a, col_b) - 1.0) < 1e-9

    # Case 2: 2 raters x 4 items, derived by hand.
    #   rater A: pos pos neg neg
    #   rater B: pos neg neg pos
    # Raw agreement: items 1 and 3 agree -> 2/4 = 0.5.
    # Cohen: p_o = 0.5; both raters have marginals 0.5/0.5, so
    #   p_e = 0.5*0.5 + 0.5*0.5 = 0.5; kappa = (0.5 - 0.5)/(1 - 0.5) = 0.0.
    # Fleiss: P_i is 1 for the two agreeing items, 0 for the others, so
    #   P_bar = 0.5; p_pos = p_neg = 4/8 = 0.5 so P_e = 0.5; kappa = 0.0.
    # Krippendorff: pooled values are 4 pos + 4 neg (n = 8). Each of the two
    #   mixed units contributes 2 off-diagonal coincidences (m_u = 2, weight
    #   1/(m_u - 1) = 1), so D_o = 4. Expected disagreement
    #   D_e = 2 * (4 * 4)/(8 - 1) = 32/7. alpha = 1 - 4/(32/7) = 1 - 7/8
    #   = 0.125.
    small: Matrix = [
        ["positive", "positive"],
        ["positive", "negative"],
        ["negative", "negative"],
        ["negative", "positive"],
    ]
    assert abs(raw_agreement(small) - 0.5) < 1e-9
    assert abs(fleiss_kappa(small) - 0.0) < 1e-9
    assert abs(krippendorff_alpha(small) - 0.125) < 1e-9
    small_a = [row[0] for row in small]
    small_b = [row[1] for row in small]
    assert abs(cohen_kappa(small_a, small_b) - 0.0) < 1e-9


# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
def label_text(rater: Agent, text: str) -> str:
    for _ in range(3):  # retry schema breaks, never coerce
        run: RunOutput = rater.run(text)
        if isinstance(run.content, SentimentLabel):
            return run.content.label
    raise RuntimeError("rater failed to produce a valid SentimentLabel")


if __name__ == "__main__":
    self_check()
    print("self_check passed: metrics match the hand-derived values")

    matrix: Matrix = []
    for text in ITEMS:
        matrix.append([label_text(rater, text) for rater in RATERS.values()])

    rater_names = list(RATERS)
    print()
    print("item x rater matrix:")
    header = " " * 50 + "".join(f"{name:>10}" for name in rater_names)
    print(header)
    for text, row in zip(ITEMS, matrix):
        snippet = text if len(text) <= 48 else text[:45] + "..."
        cells = "".join(f"{label:>10}" for label in row)
        print(f"{snippet:<50}{cells}")

    print()
    metrics = {
        "raw_agreement": round(raw_agreement(matrix), 3),
        "fleiss_kappa": round(fleiss_kappa(matrix), 3),
        "krippendorff_alpha": round(krippendorff_alpha(matrix), 3),
    }
    for (i, a), (j, b) in combinations(enumerate(rater_names), 2):
        cols_a = [row[i] for row in matrix]
        cols_b = [row[j] for row in matrix]
        metrics[f"cohen_kappa_{a}_vs_{b}"] = round(cohen_kappa(cols_a, cols_b), 3)
    pprint(metrics)

    review = [(text, row) for text, row in zip(ITEMS, matrix) if len(set(row)) > 1]
    print()
    print(f"routing {len(review)} of {len(ITEMS)} items to review (not unanimous):")
    for text, row in review:
        votes = ", ".join(f"{name}={label}" for name, label in zip(rater_names, row))
        print(f"- {text} -> {votes}")

    unanimous = len(ITEMS) - len(review)
    print()
    print(
        f"{len(ITEMS)} items x {len(RATERS)} raters: "
        f"{unanimous} unanimous, {len(review)} routed to review"
    )
