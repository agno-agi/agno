# Test Log - _22_dataset_curation

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** LLM judge quality gate over the committed fixture data/sample_rows.jsonl (12 SFT rows: 7 good plus 5 planted defects - vague, factually wrong, non-self-contained, truncated, instruction-echo). A temperature-0 Gemini judge scores each row 1-5 on clarity, factual correctness, and self-containedness; rows are written to data/generated/curated.jsonl (with score and reason as provenance) only when the verdict is keep AND the score clears the >= 4 bar, both enforced in code; structured output is isinstance-checked with retries.

**Result:** All 7 good rows kept with score 5; all 5 planted defects dropped with the correct deciding criterion in the reason (vague sleep tips: "extremely vague", 50 C boiling point: "factually incorrect as water boils at 100 degrees Celsius", missing passage: "refers to a missing passage", truncated venv steps: "incomplete and ends abruptly", instruction echo: "merely echoes the instruction back"). Summary line: "wrote 7 rows to data/generated/curated.jsonl: kept 7, dropped 5 of 12". Ran three times (including after the enforced score-bar gate was added) with identical verdicts on all 12 rows.

---

### dedup.py

**Status:** PASS

**Description:** LLM-free MinHash near-duplicate detection: word 3-gram shingles, 64 keyed blake2b hash functions, estimated Jaccard = fraction of matching signature slots, pairs >= 0.7 clustered via union-find, first row per cluster kept. Fixture is 10 module-level rows with 2 planted clusters: a light-edit cluster of 3 (one-word substitutions) and a paraphrase-level cluster of 2 (word-choice changes). Deterministic - no randomness, fixed hash keys.

**Result:** Both planted clusters detected and nothing else. Cluster 1 = [row-00, row-03, row-07] with est_jaccard(row-00, row-03) = 0.797, est_jaccard(row-00, row-07) = 0.797, est_jaccard(row-03, row-07) = 0.625 - the third pair is below threshold and joins only transitively through row-00, which the printout shows honestly. Cluster 2 = [row-02, row-06] with est_jaccard = 0.797. Summary line: "kept 7 of 10 rows: dropped 3 near-duplicates across 2 clusters". Values are exactly reproducible across runs.

---

### decontamination.py

**Status:** PASS

**Description:** LLM-free 13-gram overlap decontamination. Protected set is every lowercase word 13-gram from the 8 invented benchmark questions in data/benchmark_sample.jsonl; the 8 module-level training rows include 1 verbatim copy of bench-01 (train-02), 1 close paraphrase of bench-03 (train-04, designed to be missed), and 1 row shorter than 13 words (train-06, cannot produce a 13-gram). Any training row sharing >= 1 protected 13-gram is dropped.

**Result:** Protected set built with 56 distinct 13-grams from 8 benchmark questions. train-02 flagged with matching 13-gram "180 kilometers in 2 hours and 15 minutes what is its average speed" attributed to bench-01. train-04 not flagged, and the honest-limitation line printed: paraphrase contamination shares no 13 consecutive words and needs fuzzy or embedding-based methods. Summary line: "kept 7 of 8 training rows, dropped 1 contaminated: ['train-02']". Deterministic; identical output across both runs.

---
