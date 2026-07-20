# Environments

Verification and dataset generation for agents. 28 progressive folders contain 79
single-file runnable examples: run an agent K times against difficult tasks, score
every attempt, inspect the pass-rate grid, and export passing text trajectories as a
supervised fine-tuning dataset.

Each subfolder covers one theme. Its `basic.py` is the smallest complete example;
variants add one task-meaningful option at a time.

The central signal is the learning zone: tasks with `0 < pass_rate < 1`. Tasks that
always pass are already saturated, while tasks that always fail provide no successful
trajectory to export. The useful middle band shows where the policy is capable but
inconsistent. The examples use tasks calibrated against `gpt-5.5`; an all-full grid is
a prompt to make the task harder, not a successful demonstration.

This release performs independent rollouts and scores them after completion. It does
not run a live RL reward loop, and exporting JSONL does not train a model. A live
turn-by-turn environment is a later release.

Start with [`_01_first_environment/basic.py`](_01_first_environment/basic.py). Every
other cookbook mirrors its structure and builds on the vocabulary introduced there.

## Layout

````
cookbook/environments/
├── README.md
├── <theme>/
│   ├── README.md
│   ├── basic.py            # smallest readable example
│   ├── <variant>.py        # one file per task-meaningful option
│   ├── schemas.py          # shared Pydantic types, if any
│   ├── data/               # checked-in tasks; generated/ is ignored
│   └── TEST_LOG.md         # observed live pass rates for every file
└── ...
````

## Cookbooks

### Quickstart

- [`_00_quickstart/`](_00_quickstart/): seven single-file examples covering the
  whole arc — run K times, score, read the grid, export what passed. Start here
  for the shortest path; the numbered folders below go deeper on the same ideas.

### Verification basics

- [`_01_first_environment/`](_01_first_environment/): create an `Environment`, run K
  isolated attempts, and read the grid and `summary()`.
- [`_02_task_sets/`](_02_task_sets/): declare tasks inline, load strict JSONL, and
  select metadata-defined slices without changing environment identity.
- [`_03_code_scorer/`](_03_code_scorer/): verify typed outputs with Boolean, graded,
  and explicit `Score` results.
- [`_04_judge_scorer/`](_04_judge_scorer/): grade criteria that code cannot express
  with binary and numeric rubrics.
- [`_05_tool_call_scorer/`](_05_tool_call_scorer/): require clean tool executions,
  exact arguments, and no unexpected tools.
- [`_06_learning_zone/`](_06_learning_zone/): surface the partial pass-rate band and
  separate it from saturated and failed tasks.
- [`_07_difficulty_calibration/`](_07_difficulty_calibration/): grow task difficulty
  until a strong model stops producing a wall of full bars.
- [`_08_async_rollouts/`](_08_async_rollouts/): use `arun_rollouts` and the async SFT
  exporter inside an existing event loop.
- [`_09_task_selection/`](_09_task_selection/): run a proven subset and rerun only
  tasks that need more evidence.

### Dataset export

- [`_10_export_sft/`](_10_export_sft/): select learnable tasks, keep passing attempts,
  and write portable conversational JSONL.
- [`_11_export_provenance/`](_11_export_provenance/): inspect the score and fingerprint
  sidecar that keeps training rows auditable.
- [`_12_trainer_loader/`](_12_trainer_loader/): validate and stream exported messages
  through a small trainer-facing loader without pretending training occurred.

### Comparing runs

- [`_13_saved_baselines/`](_13_saved_baselines/): save, reload, and protect plaintext
  rollout evidence for later comparison.
- [`_14_environment_diff/`](_14_environment_diff/): diff identical environments under
  different `gpt-5.5` policy settings and handle fingerprint mismatches.
- [`_15_prompt_comparison/`](_15_prompt_comparison/): compare before/after prompt
  summaries when the environment fingerprint changes by design.
- [`_16_policy_settings/`](_16_policy_settings/): compare low and high reasoning effort
  while keeping the model family fixed.

### Reliability and evidence

- [`_17_tool_reliability/`](_17_tool_reliability/): measure tool grounding over a
  distribution and compare repeated `ReliabilityEval` verdicts with the scorer.
- [`_18_execution_matching/`](_18_execution_matching/): distinguish clean executions
  from requested, failed, or wrong-argument calls.
- [`_19_error_analysis/`](_19_error_analysis/): inspect unscored attempts, scorer
  errors, and public `StopReason` values without folding them into failures.
- [`_20_report_drilldown/`](_20_report_drilldown/): move from the grid to failed-only
  reports and a single attempt's full transcript.

### Task domains

- [`_21_math/`](_21_math/): exact arithmetic ladders whose difficulty grows past
  single-operation saturation.
- [`_22_sql_generation/`](_22_sql_generation/): execute generated SQL against
  in-memory fixtures, including joins and window functions.
- [`_23_code_fixes/`](_23_code_fixes/): verify constrained bug fixes against explicit
  regression cases.
- [`_24_structured_extraction/`](_24_structured_extraction/): score typed extraction
  when dates, fields, and nested records conflict.
- [`_25_support_triage/`](_25_support_triage/): apply precedence rules to genuinely
  multi-intent support tickets.
- [`_26_multi_step_tools/`](_26_multi_step_tools/): verify required tool chains,
  arguments, and execution order.

### From evidence to a gate

- [`_27_verified_dataset/`](_27_verified_dataset/): run, curate the middle band,
  export passing text attempts, and inspect the resulting manifest end to end.
- [`_28_ci_gating/`](_28_ci_gating/): turn `summary()` and per-task floors into a
  process exit decision suitable for CI.

## Running a cookbook

From the Agno repository root, create the demo environment if needed:

```bash
./scripts/demo_setup.sh
```

Load the repository environment and run the first file:

```bash
direnv exec . .venvs/demo/bin/python cookbook/environments/_01_first_environment/basic.py
```

Every runnable file uses `OpenAIResponses` with `gpt-5.5`. Folder READMEs list all
commands and call out any local fixture they use.

| Variable | Used by |
|---|---|
| `OPENAI_API_KEY` | Every environment cookbook |

## Reading “learning zone” precisely

For Boolean scores, `results.learning_zone()` and `0 < pass_rate < 1` select the same
tasks. Numeric scorers can vary in score while every attempt remains on the same side
of the pass threshold; those examples call that *score variation*, not a partial
pass-rate learning zone. SFT examples use Boolean verdicts before exporting.

Tool-using rollouts can be verified but are not exportable with the current text-only
SFT format. The exporter skips them rather than dropping the tool evidence and
teaching the model to answer without its tools.
