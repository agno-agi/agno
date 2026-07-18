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
```

Requires `GOOGLE_API_KEY`. `dpo_jury.py` additionally requires `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, and `MISTRAL_API_KEY`.
