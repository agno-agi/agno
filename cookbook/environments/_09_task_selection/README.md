# Task Selection

Run a deliberate subset of an environment without changing its task identity.
Selection is useful for held-out splits, expensive domains, and targeted reruns
after the first pass-rate grid identifies weak rows.

## Files

- `basic.py` — select tasks by metadata and pass them to the runner.
- `rerun_failures.py` — rerun every row that was not saturated at a full pass rate.

## When to use

Use task selection when the complete environment is larger than the question
you need to answer. Always select the original `Task` objects from `env.tasks`;
new lookalike tasks are rejected because they are not part of that environment.

This follows async execution in
[`_08_async_rollouts/`](../_08_async_rollouts/). The selected passing attempts
become a dataset in [`_10_export_sft/`](../_10_export_sft/).

## Run

```bash
python cookbook/environments/_09_task_selection/basic.py
python cookbook/environments/_09_task_selection/rerun_failures.py
```

Requires `OPENAI_API_KEY`. Selection and reruns verify behavior; they do not
update the agent during execution.
