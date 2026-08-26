"""
Dataset Curation - Benchmark Decontamination
============================================

Drop training rows that overlap an evaluation set, without any LLM calls.
The protected set is every lowercase word 13-gram from the benchmark
questions in data/benchmark_sample.jsonl (an invented fixture, not a real
benchmark); any training row sharing at least one 13-gram is flagged and
dropped. 13-gram overlap is the classic n-gram check from LLM training-data
decontamination reports.

What this catches and what it misses, demonstrated on planted rows:
- train-02 is a verbatim copy of a benchmark question - the check flags it.
- train-04 is a close paraphrase of another benchmark question - the check
  misses it by design, because a paraphrase shares no 13 consecutive words.
  Paraphrase contamination needs fuzzy or embedding-based methods.
"""

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NGRAM_SIZE = 13

# Planted rows, referenced when printing the honest-limitation line.
CONTAMINATED_ROW_ID = "train-02"  # verbatim copy of bench-01
PARAPHRASE_ROW_ID = "train-04"  # close paraphrase of bench-03


# ---------------------------------------------------------------------------
# Fixture: 8 training rows
# ---------------------------------------------------------------------------
TRAINING_ROWS = [
    {
        "id": "train-01",
        "instruction": (
            "Explain the difference between compile time and run time errors "
            "in a programming language."
        ),
        "response": (
            "Compile time errors are caught before the program runs, such as "
            "syntax errors or type mismatches in statically typed languages. "
            "Run time errors occur while the program executes, such as "
            "dividing by zero or dereferencing a null pointer."
        ),
    },
    {
        # Planted contamination: instruction is a verbatim copy of the
        # bench-01 question.
        "id": "train-02",
        "instruction": (
            "A train travels 180 kilometers in 2 hours and 15 minutes. What "
            "is its average speed in kilometers per hour?"
        ),
        "response": (
            "2 hours and 15 minutes is 2.25 hours, so the average speed is "
            "180 / 2.25 = 80 kilometers per hour."
        ),
    },
    {
        "id": "train-03",
        "instruction": "Write a haiku about the changing of the seasons.",
        "response": (
            "Green leaves turn to gold / a cold wind counts the branches / "
            "snow keeps the last word"
        ),
    },
    {
        # Planted paraphrase of the bench-03 question: same problem, reworded,
        # so it shares no 13 consecutive words with the benchmark text.
        "id": "train-04",
        "instruction": (
            "The perimeter of a rectangle is 36 meters and the length is "
            "double the width. Find the area in square meters."
        ),
        "response": (
            "Let the width be w and the length 2w. Then 2(w + 2w) = 36, so "
            "6w = 36 and w = 6. The length is 12, so the area is 12 * 6 = 72 "
            "square meters."
        ),
    },
    {
        "id": "train-05",
        "instruction": ("What are the primary colors in subtractive color mixing?"),
        "response": (
            "In subtractive color mixing, as used in printing, the primary "
            "colors are cyan, magenta, and yellow."
        ),
    },
    {
        # Shorter than 13 words in total, so it cannot produce a single
        # 13-gram: the n-gram check can never flag rows this short.
        "id": "train-06",
        "instruction": "What is 2 + 2?",
        "response": "4",
    },
    {
        "id": "train-07",
        "instruction": (
            "A car uses 6 liters of fuel per 100 kilometers. How much fuel "
            "does it need for a 250 kilometer trip?"
        ),
        "response": (
            "Fuel needed is 250 / 100 * 6 = 15 liters for the 250 kilometer trip."
        ),
    },
    {
        "id": "train-08",
        "instruction": (
            "Describe how photosynthesis converts sunlight into chemical energy."
        ),
        "response": (
            "Chlorophyll absorbs light, which drives the splitting of water "
            "and the production of ATP and NADPH; the Calvin cycle then uses "
            "that energy to fix carbon dioxide into glucose."
        ),
    },
]


# ---------------------------------------------------------------------------
# Create N-gram Index
# ---------------------------------------------------------------------------
def tokenize(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text.lower())


def ngrams(tokens: list, n: int) -> set:
    # A row with fewer than n tokens yields zero n-grams, so it can never be
    # flagged - the empty set falls out of the range() below naturally.
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    benchmark_path = Path(__file__).parent / "data" / "benchmark_sample.jsonl"
    benchmark_rows = [
        json.loads(line)
        for line in benchmark_path.read_text().splitlines()
        if line.strip()
    ]

    # Protected set: every 13-gram from every benchmark question, mapped back
    # to its source row for provenance. Benchmark answers are single tokens
    # here and contribute no 13-grams, so only question text is protected.
    protected = {}
    for bench in benchmark_rows:
        for gram in ngrams(tokenize(bench["question"]), NGRAM_SIZE):
            protected[gram] = bench["id"]
    print(
        f"protected set: {len(protected)} distinct 13-grams "
        f"from {len(benchmark_rows)} benchmark questions"
    )
    print()

    kept = 0
    flagged_ids = []
    for row in TRAINING_ROWS:
        tokens = tokenize(row["instruction"] + " " + row["response"])
        overlap = ngrams(tokens, NGRAM_SIZE) & protected.keys()
        if overlap:
            flagged_ids.append(row["id"])
            gram = sorted(overlap)[0]
            print(f"FLAGGED {row['id']} (overlaps {protected[gram]})")
            print(f"  matching 13-gram: '{gram}'")
            print(f"  instruction: {row['instruction'][:70]}")
        else:
            kept += 1

    print()
    if PARAPHRASE_ROW_ID in flagged_ids:
        print(f"unexpected: paraphrase row {PARAPHRASE_ROW_ID} was flagged")
    else:
        print(
            f"limitation: {PARAPHRASE_ROW_ID} paraphrases bench-03 but was "
            f"NOT flagged - it shares no 13 consecutive words with the "
            f"benchmark. Paraphrase contamination needs fuzzy or "
            f"embedding-based methods; exact n-gram overlap cannot see it."
        )
    print()
    print(
        f"kept {kept} of {len(TRAINING_ROWS)} training rows, dropped "
        f"{len(flagged_ids)} contaminated: {flagged_ids}"
    )
