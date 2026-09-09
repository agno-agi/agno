# Quickstart

Seven single-file examples that cover the whole arc — run an agent K times, score
every attempt, read the grid, export what passed. No folder hopping: each file
stands alone and runs end to end.

Start here if you want the shortest path from nothing to a working environment.
Once a file makes sense, the numbered folders that follow go deeper on the same
ideas, one option per file.

## Files

- `_01_first_env.py` — the smallest complete environment: tasks, a scorer, K
  attempts, and the pass-rate grid.
- `_02_export_sft.py` — keep the attempts that passed and write a conversational
  SFT dataset.
- `_03_tool_reliability.py` — verify an agent that calls tools, and check the
  calls actually executed.
- `_04_judge_rubric.py` — grade with a rubric when code cannot express the check.
- `_05_compare_models.py` — run the same environment under two policies and read
  the difference.
- `_06_drilldown_demo.py` — inspect a single attempt: verdict, transcript, tokens.
- `_07_support_triage.py` — a realistic classification environment end to end.

## Run

One file:

```bash
python cookbook/environments/_00_quickstart/_01_first_env.py
```

The whole folder, in order, with the shared runner:

```bash
python cookbook/scripts/cookbook_runner.py cookbook/environments/_00_quickstart \
    --batch --timeout-seconds 1800 --json-report /tmp/quickstart.json
```

Each file makes real model calls, so `OPENAI_API_KEY` must be set and a full
folder run costs real tokens. `--timeout-seconds 0` disables the per-file limit
if a task needs longer.

## Where to go next

- [`_01_first_environment/`](../_01_first_environment/) — the same first
  environment, broken into one option per file.
- [`_06_learning_zone/`](../_06_learning_zone/) — why tasks the agent
  *sometimes* passes are the ones worth training on.
- [`_10_export_sft/`](../_10_export_sft/) — the export path in full, including
  provenance.
