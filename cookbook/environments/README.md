# Environments

Run an agent many times against a set of tasks, score every attempt automatically, and
do something useful with the result.

That answers two questions, in this order:

1. **Does my agent actually work?** Agent output is sampled, so one run proves nothing.
   Running each task K times and counting gives you a real pass rate, and re-running
   after a prompt edit, a tool change, or a model swap tells you what moved.
2. **Can I train on the runs that worked?** The attempts that passed are, with no
   further labelling, a supervised fine-tuning dataset.

Some vocabulary here -- environment, rollout, policy -- is borrowed from RL, where
model trainers build a similar artifact. What ships here is verification and dataset
generation; you do not need to know anything about RL to use it.

## Files

| File | What it shows |
|------|---------------|
| `_01_first_env.py` | The whole thing in twenty lines: `Environment`, a typed `CodeScorer`, `run_rollouts`, the live grid, `summary()` |
| `_02_export_sft.py` | The second job: `learning_zone()`, `to_sft_jsonl`, the export report, and the provenance sidecar |
| `_03_tool_reliability.py` | `ToolCallScorer`: did the lookup tool actually EXECUTE, or did the agent answer from its head? Executions, not requests |
| `_04_judge_rubric.py` | `JudgeScorer` with a graded rubric: a pass rate for quality you cannot check with code (tone, commitments, next steps) |
| `_05_compare_models.py` | The cost-review question: same env, `model=` override, `save`/`load`/`diff` -- can the cheaper model ship? Tasks from JSONL |
| `_06_drilldown_demo.py` | Reading the evidence: `errors()`, `print_report(only="all")`, `print_attempt` -- and where this goes next |

The three scorers cover the three kinds of pass criteria: a typed field you can compare
in code (`_01`), a tool that must have done real work (`_03`), and quality only a judge
can grade (`_04`). `_02` and `_05` are the two things you do with the artifact
afterwards: export the runs that worked, and compare runs across time or models. `_06`
is how you read the per-attempt evidence when a number needs investigating.

## Setup

```bash
export OPENAI_API_KEY=***
.venvs/demo/bin/python cookbook/environments/_01_first_env.py
.venvs/demo/bin/python cookbook/environments/_02_export_sft.py
.venvs/demo/bin/python cookbook/environments/_03_tool_reliability.py
.venvs/demo/bin/python cookbook/environments/_04_judge_rubric.py
.venvs/demo/bin/python cookbook/environments/_05_compare_models.py
.venvs/demo/bin/python cookbook/environments/_06_drilldown_demo.py
```

No database or services needed: each attempt runs against a fresh in-memory store and
a fresh user id (with the response cache off), so attempts can't contaminate each
other or your real data. State owned by your own tools is the one thing the runner
cannot isolate for you -- `_03` keeps its lookup table read-only for exactly that
reason.

## Choosing a door

- Gating a release in CI, one attempt read by a person: `agno.eval` (`Case`,
  `run_cases`).
- Measuring a distribution over K attempts, or exporting training data:
  `agno.environments` (`Task`, `run_rollouts`).

Task sets a team owns in git live in `tasks/` (checked in, strict-validated by
`Task.from_jsonl`). Exports and saved baselines land in `data/generated/`, which is
gitignored.

## The next step

Nothing here talks back to the agent mid-run: each attempt is one independent run,
scored after it finishes. What ships is verification and dataset generation -- run K
times, score, export what passed. A live multi-turn loop, where the environment
responds to each agent turn and scores during the interaction, is the next step, not
part of this release.
