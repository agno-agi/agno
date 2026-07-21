# Reward Calibration

A pass rate is only as trustworthy as the scorer that produced it. These two
examples measure the scorer itself — once against labels, and then over time
against a held-out verifier.

## Files

- `basic.py` — `calibrate` a scorer against hand-labelled traces: agreement,
  false positive rate, false negative rate, and every disagreement.
- `audit_gap.py` — run an `ImprovementLoop` with an `audit_scorer` and watch the
  per-round gap between the training scorer and the audit.

Both run fully offline and deterministically. No model is called.

## Why this comes before training

A false positive is the expensive kind of wrong: the exporter keeps whatever the
scorer passed, so a lenient scorer writes its own mistakes into the training set
and the fine-tune teaches them. Calibrating first costs nothing; discovering it
afterwards costs a training run.

`expected` is part of every labelled trace because that is what the scorer is
given at score time. A bare `(run, gold)` pair would score everything against
`expected=None`, which under a permissive scorer greens the whole set — so it is
rejected rather than accepted quietly.

## Reading the audit gap

The audit scorer re-scores each round's **tuned measurement rollout** — never the
exported rows, which all passed the training scorer by construction and would
pin the training rate at 1.00.

The signal is the **trend**, not any single round:

- The gap **widening** round over round — training rising while the audit stalls
  or falls — is reward hacking.
- A stricter audit sitting **uniformly lower** from round one is calibration.

agno reports the per-round numbers and nothing else: there is no verdict field
and no trend helper, because every useful threshold is task-relative. Read the
series yourself, and only at a sane n. `IterationReport.audit_scorer_digest`
identifies which verifier produced a reading, so two runs are comparable only
when their digests match.

## Run

```bash
python cookbook/environments/_30_reward_calibration/basic.py
python cookbook/environments/_30_reward_calibration/audit_gap.py
```

## Requirements

None. Both files are offline.
