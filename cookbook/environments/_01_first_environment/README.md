# Your First Environment

Run one agent K times against a small task set and score every attempt. The
grid makes reliability visible: full rows are already mastered, empty rows
need a different intervention, and partial rows are the learning zone.

## Files

- `basic.py` — the smallest complete environment: typed output, tasks,
  `CodeScorer`, and a K-attempt grid.
- `with_summary.py` — reads the grid through the stable `summary()` mapping.
- `with_fingerprints.py` — inspects the environment and policy fingerprints
  stamped on a run.

## When to use

Start here when one successful agent run is not enough evidence. The examples
pair an easy anchor with chained arithmetic calibrated to produce disagreement
on `gpt-5.5`; an all-full grid is not a useful reliability example.

Continue to [`_02_task_sets/`](../_02_task_sets/) when tasks need ids,
metadata, or a checked-in JSONL file. The live turn-by-turn reward loop is not
part of this release; these environments perform verification and dataset
generation.

## Run

```bash
python cookbook/environments/_01_first_environment/basic.py
python cookbook/environments/_01_first_environment/with_summary.py
python cookbook/environments/_01_first_environment/with_fingerprints.py
```

Requires `OPENAI_API_KEY`. Every model call uses `OpenAIResponses` with
`gpt-5.5`.
