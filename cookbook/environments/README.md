# Environments

Run an agent many times against a set of tasks, score every attempt automatically, and
do something useful with the result.

That answers two questions, in this order:

1. **Does my agent actually work?** Agent output is sampled, so one run proves nothing.
   Running each task K times and counting gives you a real pass rate, and re-running
   after a prompt edit, a tool change, or a model swap tells you what moved.
2. **Can I train on the runs that worked?** The attempts that passed are, with no
   further labelling, a supervised fine-tuning dataset.

Model trainers call this artifact an RL environment, and some vocabulary here is
borrowed from that field. You do not need to know anything about RL to use it for the
first question.

## Files

| File | What it shows |
|------|---------------|
| `_01_first_env.py` | The whole thing in twenty lines: `Env`, a typed `CodeScorer`, `run_rollouts`, the live grid, `summary()` |
| `_02_export_sft.py` | The second job: `learning_zone()`, `to_sft_jsonl`, the export report, and the provenance sidecar |

## Setup

```bash
export OPENAI_API_KEY=***
.venvs/demo/bin/python cookbook/environments/_01_first_env.py
.venvs/demo/bin/python cookbook/environments/_02_export_sft.py
```

No database or services needed: rollouts are hermetic (each attempt runs on a fresh
copy with an in-memory db, fresh session and user ids, and the response cache off), so
nothing touches your stores.

## Choosing a door

- Gating a release in CI, one attempt read by a person: `agno.eval` (`Case`,
  `run_cases`).
- Measuring a distribution over K attempts, or exporting training data:
  `agno.environments` (`EnvTask`, `run_rollouts`).

Exports land in `data/generated/`, which is gitignored.
