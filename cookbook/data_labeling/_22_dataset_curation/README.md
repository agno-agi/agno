# Dataset Curation

Filter a dataset before training on it: gate rows on quality with a judge,
collapse near-duplicates, and drop rows that overlap your eval set. These are
the three filters post-training pipelines are actually judged by. Only the
quality gate uses an LLM - dedup and decontamination are deliberately LLM-free,
pure-stdlib math, because that is how they run in production and because the
numbers they print should be exactly reproducible.

## Files

- `basic.py` - LLM judge quality gate over JSONL. Scores each (instruction,
  response) row 1-5 on clarity, factual correctness, and self-containedness
  (temperature-0 judge); keeps rows scoring >= 4 and writes them out with
  score and reason attached as provenance. Reads the committed fixture
  `data/sample_rows.jsonl`. The gate expects `{"instruction", "response"}`
  rows; to point `input_path` at another generator's output, map its fields
  into that shape first (`_20_instruction_generation/` emits instructions
  without responses, and `_21_rejection_sampling/` rows use
  `prompt`/`reasoning` keys).
- `dedup.py` - no LLM. MinHash near-duplicate detection in pure stdlib: word
  3-gram shingles, 64 keyed blake2b hash functions, estimated Jaccard >= 0.7
  clustered with union-find, first row per cluster kept. Fully deterministic
  across runs. Catches verbatim copies, light edits, and close paraphrases;
  heavy rewording needs embedding-based dedup.
- `decontamination.py` - no LLM. 13-gram overlap decontamination against
  `data/benchmark_sample.jsonl` (an invented fixture, not a real benchmark).
  Flags a planted verbatim copy of a benchmark question and honestly reports
  the planted paraphrase it cannot catch - exact n-gram overlap misses
  paraphrase contamination by construction.

Example rows from `basic.py` output (kept rows carry their gate provenance):

```jsonl
{"instruction": "Convert 25 degrees Celsius to Fahrenheit and show the formula.", "response": "Using F = C * 9/5 + 32: F = 25 * 9/5 + 32 = 45 + 32 = 77. So 25 degrees Celsius is 77 degrees Fahrenheit.", "score": 5, "reason": "The response is clear, factually correct, and self-contained."}
{"instruction": "Explain what HTTP status code 404 means.", "response": "HTTP 404 Not Found means the server understood the request but could not find the requested resource at that URL. It indicates a client-side addressing problem (bad link or mistyped path), not a server failure; server failures use 5xx codes instead.", "score": 5, "reason": "The response is clear, factually correct, and self-contained."}
```

## When to use

When you have a corpus and need to decide which rows deserve to be trained
on. This folder is corpus-level curation: whole rows are kept or dropped.
For label-level review - checking and fixing individual annotations - use
[`_18_quality_review/`](../_18_quality_review/). For the judging primitive
itself, see [`_17_llm_as_judge/`](../_17_llm_as_judge/).

Typical position in a pipeline: generate candidates with
[`_20_instruction_generation/`](../_20_instruction_generation/) or
[`_21_rejection_sampling/`](../_21_rejection_sampling/), then curate here -
quality gate, then dedup, then decontaminate against your eval sets.

## Run

```bash
python cookbook/data_labeling/_22_dataset_curation/basic.py
python cookbook/data_labeling/_22_dataset_curation/dedup.py
python cookbook/data_labeling/_22_dataset_curation/decontamination.py
```

Requires `GOOGLE_API_KEY` (basic.py only; dedup.py and decontamination.py make
no API calls).
