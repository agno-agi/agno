# Expert Iteration

Close the loop. Everything up to here verifies an agent and exports what it got
right; this trains on that export and measures whether it helped.

One `ImprovementLoop` runs the whole round: sample the base model, keep the
learning-zone attempts that passed, fine-tune on them, serve the checkpoint, run
it back through the same environment, and diff. Same tasks, same scorer, same
agent design — the only thing that changes is the weights.

## Files

- `basic.py` — one round end to end, offline by default.

## Offline by default

`basic.py` defines a small scripted model and stub trainer inline so the loop
runs with no GPU and no API key. They are stand-ins, not agno API: a real
trainer serves real checkpoints. Set `TINKER_API_KEY` and the same file runs
against `TinkerTrainer`, fine-tuning `Qwen/Qwen3.6-35B-A3B` for real.

## What has to be true for a gain to exist

The base must be in the **learning zone** — passing some attempts and failing
others. A base that passes everything exports nothing (`converged_reason
"saturated"`); one that passes nothing exports nothing either (`"all_failing"`).
Expert iteration amplifies what a model already does sometimes; it cannot teach
what the model never does.

Tool-using agents export nothing in this release — the text-only SFT format has
no tool representation, so the loop reports `"not_exportable"` and trains
nothing. See [`_10_export_sft/`](../_10_export_sft/).

## If you run the live path

A thinking model spends a long time inside `<think>` before the visible answer: a
2000-token sample from a 35B MoE routinely takes minutes. The environment here sets
`timeout_seconds=900` for that reason — the 120s default times out every attempt, which
surfaces as a rollout of unscored triangles and a `None` pass rate rather than as a
timeout you would notice.

Budget for that: at 3 tasks and k=4 the loop samples 12 attempts for the baseline and
12 more to measure the tuned checkpoint, either side of the fine-tune itself.

## Reading the numbers honestly

This is rejection-sampling fine-tuning, and it saturates. Three caveats worth
saying out loud:

- A rising pass rate is progress **on this verifier**. Keep the verifier honest
  with [`_30_reward_calibration/`](../_30_reward_calibration/).
- The loop trains on the same tasks it re-measures, so part of any gain is
  memorization. For a generalization claim, measure held-out tasks:
  `run_rollouts(env, tasks=held_out, model=trainer.as_model(ckpt))`.
- At small n the numbers are noisy. A pass rate over n scored attempts has
  standard error around `sqrt(p(1-p)/n)`, so at this demo's 3 tasks and k=4 a
  swing of 0.10 is noise. Prefer 20 or more tasks and k of at least 8 before
  trusting a delta.

## Run

```bash
python cookbook/environments/_29_expert_iteration/basic.py
```

## Requirements

| Variable | Needed for |
|---|---|
| none | the offline run |
| `TINKER_API_KEY` | the live fine-tune branch |
