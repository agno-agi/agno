# Instruction Generation

Generate synthetic training instructions from a small amount of hand-written
input - the definitional synthetic-data workload. Three classic recipes:
grow a pool from seed instructions (Self-Instruct), increase complexity with
typed evolution operators (Evol-Instruct), and expand a topic tree into
SFT-ready chat data. The self-instruct and evolution files run every
candidate through a stdlib filter; the topic tree caps counts by slicing.
Every row carries provenance (seed ids, parent instruction, or tree branch)
so downstream curation can trace and prune.

## Files

- `basic.py` - Self-Instruct: 8 hand-written seeds, 2 rounds of generation
  with 3 seeds as few-shot examples per round, word-set Jaccard dedupe
  (threshold 0.7) against seeds and already-accepted instructions.
- `evol_instruct.py` - Evol-Instruct: 5 seeds x 2 chained evolution steps.
  Operators (`add_constraints`, `deepen`, `concretize`,
  `increase_reasoning`, `in_breadth`) are assigned by deterministic
  round-robin so all five appear. A stdlib eliminator drops no-op
  evolutions (Jaccard vs parent > 0.85) and degenerate ones (< 4 words).
- `topic_tree.py` - topic -> subtopic -> question -> response with three
  agents (expander, question writer, answerer). Output is SFT-ready chat
  format: each row is `{"messages": [user, assistant], "provenance": ...}`,
  loadable directly by most fine-tuning stacks.

Rows are written to `data/generated/` (gitignored - run the scripts to
regenerate). Abridged rows from a real run:

```json
{"instruction": "Design three fictional plants that would thrive in a volcanic, sulfur-rich soil environment. For each plant, provide its common name, its scientific-sounding name, and a one-sentence description of its survival mechanism.", "seed_ids": ["seed-01", "seed-02", "seed-03"], "round": 1}
{"instruction": "Explain how a hash table works to a junior software developer by using the concrete scenario of storing and retrieving 10,000 employee records ...", "parent": "Explain how a hash table works.", "operator": "concretize", "depth": 1}
{"messages": [{"role": "user", "content": "How do B+ Tree indexes and Log-Structured Merge (LSM) Tree indexes differ in their write amplification behavior ...?"}, {"role": "assistant", "content": "During high-throughput insert workloads, B+ Trees suffer from high write amplification due to their in-place update model. ..."}], "provenance": {"topic": "database indexing", "subtopic": "Index Data Structures and Algorithms", "depth": 3}}
```

## When to use

When you need instruction or SFT data and have only a handful of seeds or a
topic list:

- Self-Instruct when you want breadth from a tiny seed pool
- Evol-Instruct when you have easy instructions and need harder ones
- Topic tree when you want coverage of a domain with traceable structure

Generation is only half the pipeline: pass the output through
[`_22_dataset_curation/`](../_22_dataset_curation/) to filter and dedupe at
scale. If you can verify responses (tests, checkers, judges), use
[`_21_rejection_sampling/`](../_21_rejection_sampling/) to keep only
verified generations.

## Run

```bash
python cookbook/data_labeling/_20_instruction_generation/basic.py
python cookbook/data_labeling/_20_instruction_generation/evol_instruct.py
python cookbook/data_labeling/_20_instruction_generation/topic_tree.py
```

Requires `GOOGLE_API_KEY`.
