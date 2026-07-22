# Expert Iteration

Close the loop. Everything up to here verifies an agent and exports what it got
right; this trains on that export and measures whether it helped.

One `ImprovementLoop` runs the whole round: sample the base model, keep the
learning-zone attempts that passed, fine-tune on them, serve the checkpoint, run
it back through the same environment, and diff. Same tasks, same scorer, same
agent design — the only thing that changes is the weights.

## Files

- `basic.py` — one round end to end, offline by default, with a swappable
  trainer backend.

## One loop, swappable trainers

The trainer is the `Trainer` protocol's seam, and `basic.py` demonstrates it:
the same `ImprovementLoop` runs against three backends, selected with
`AGNO_TRAINER`:

| `AGNO_TRAINER` | Backend | What it shows |
|---|---|---|
| `stub` (default) | inline stand-ins | the shape of the loop; no GPU, no key, no spend |
| `tinker` | `TinkerTrainer` | agno drives the training loop (forward/backward per batch) |
| `fireworks` | `FireworksTrainer` | a managed fine-tuning job + on-demand serving |

The stub trainer and scripted models are stand-ins defined in the file, not agno
API: a real trainer serves real checkpoints.

## Offline by default, and what consent means

The live paths cost money, so they are gated on an explicit opt-in flag *on top
of* the provider key: `AGNO_RUN_FINE_TUNE=1`. A key alone never triggers spend.
A key is capability, not consent: with only `TINKER_API_KEY` or
`FIREWORKS_API_KEY` set (as direnv does in many shells) the file still runs the
free offline stub. (`AGNO_RUN_TINKER_FINE_TUNE=1`, the original Tinker-only
spelling, still works and implies `AGNO_TRAINER=tinker`; combining it with an
explicit different `AGNO_TRAINER` is an error rather than a silent override.)

```bash
# offline (default)
python cookbook/environments/_29_expert_iteration/basic.py

# live Tinker fine-tune of Qwen/Qwen3.6-35B-A3B
AGNO_TRAINER=tinker AGNO_RUN_FINE_TUNE=1 python cookbook/environments/_29_expert_iteration/basic.py

# live Fireworks fine-tune of accounts/fireworks/models/qwen3-4b-instruct-2507
AGNO_TRAINER=fireworks AGNO_RUN_FINE_TUNE=1 python cookbook/environments/_29_expert_iteration/basic.py
```

## What has to be true for a gain to exist

The base must be in the **learning zone** — passing some attempts and failing
others. A base that passes everything exports nothing (`converged_reason
"saturated"`); one that passes nothing exports nothing either (`"all_failing"`).
Expert iteration amplifies what a model already does sometimes; it cannot teach
what the model never does.

Tool-using agents export nothing in this release — the text-only SFT format has
no tool representation, so the loop reports `"not_exportable"` and trains
nothing. See [`_10_export_sft/`](../_10_export_sft/).

## If you run the live Tinker path

A thinking model spends a long time inside `<think>` before the visible answer: a
2000-token sample from a 35B MoE routinely takes minutes. The environment here sets
`timeout_seconds=900` for that reason — the 120s default times out every attempt, which
surfaces as a rollout of unscored triangles and a `None` pass rate rather than as a
timeout you would notice.

Budget for that: at 3 tasks and k=4 the loop samples 12 attempts for the baseline and
12 more to measure the tuned checkpoint, either side of the fine-tune itself.

## If you run the live Fireworks path

Fireworks trains as a managed job (LoRA SFT is around $0.50 per million training
tokens for this model tier — a run this size costs pennies) but **serving is the
real cost**: neither the tuned LoRA nor the small tunable bases are serverless,
so measuring either side of the before/after needs an on-demand deployment.
`FireworksTrainer` creates one (BF16, addons enabled, scale-to-zero, max one
replica, order $7/hour of GPU time while serving) and serves base and tuned from
it so the comparison runs on identical hardware. `basic.py` calls
`trainer.teardown()` at the end of the run to delete it; if a run dies hard,
check the Fireworks dashboard for deployments named `agno-*`.

The first request after a scale-up pays a cold-start delay — another reason the
environment's `timeout_seconds` is generous. You will also need
`FIREWORKS_ACCOUNT_ID` set (the trainer refuses before any spend without it),
and the key must belong to a user or service account allowed to create
fine-tuning jobs — an inference-scoped role gets `403` on the training
endpoints.

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
| `AGNO_TRAINER` | `stub` (default), `tinker`, or `fireworks` |
| `AGNO_RUN_FINE_TUNE=1` | opting in to a live fine-tune (spends money) |
| `TINKER_API_KEY` | the Tinker live path (`pip install agno[tinker]`) |
| `FIREWORKS_API_KEY`, `FIREWORKS_ACCOUNT_ID` | the Fireworks live path (`pip install agno[fireworks]`) |
