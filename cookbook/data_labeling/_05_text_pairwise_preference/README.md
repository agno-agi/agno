# Text Pairwise Preference

Given a prompt and two candidate responses, decide which is better. This is
the data shape used for RLHF/DPO preference datasets.

## Files

- `basic.py` — pick the winner with no further structure.
- `with_rubric.py` — pick based on an explicit rubric supplied in the
  instructions.
- `with_rationale.py` — winner plus a one-sentence explanation.
- `dpo_jury.py` — a jury of 5 model families emits trainer-ready DPO records:
  typed verdicts, both-orderings position debiasing, self-preference recusal,
  gold-pair calibration, and an agreement gate that routes contested pairs to
  human review.
- `jury_calibrated.py` — calibration-first jury: three jurors are first
  scored on a balanced gold set (5 gold=a / 5 gold=b, both orderings) for
  gold accuracy, Brier score on verbalized confidence, and position bias;
  jurors below the accuracy floor are dropped, the survivors vote with
  accuracy-derived weights, and every record carries per-juror attribution.
- `jury_hardened.py` — jury hardened for adversarial inputs and juror
  failure: candidate answers are fenced as data-not-instructions (one demo
  pair embeds a prompt injection so the run shows it losing on merits), a
  juror that cannot produce a valid verdict abstains instead of crashing
  the batch, and records proceed on a 2-of-3 quorum with per-record
  voted / abstained / failed attribution.

## When to use

- Building a preference dataset to fine-tune a reward model.
- Comparing two model versions on a held-out prompt set.
- Bake-offs between prompts.

If you want a single score against a rubric rather than a pairwise
comparison, use [`_17_llm_as_judge/`](../_17_llm_as_judge/).

## Run

```bash
python cookbook/data_labeling/_05_text_pairwise_preference/basic.py
python cookbook/data_labeling/_05_text_pairwise_preference/with_rubric.py
python cookbook/data_labeling/_05_text_pairwise_preference/with_rationale.py
python cookbook/data_labeling/_05_text_pairwise_preference/dpo_jury.py
python cookbook/data_labeling/_05_text_pairwise_preference/jury_calibrated.py
python cookbook/data_labeling/_05_text_pairwise_preference/jury_hardened.py
```

Requires `GOOGLE_API_KEY`. `dpo_jury.py` additionally requires `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, and `MISTRAL_API_KEY`. `jury_calibrated.py`
and `jury_hardened.py` additionally require `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY`.
