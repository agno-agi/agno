# Text Pairwise Preference

Given a prompt and two candidate responses, decide which is better. This is
the data shape used for RLHF/DPO preference datasets.

## Files

- `basic.py` — pick the winner with no further structure.
- `with_rubric.py` — pick based on an explicit rubric supplied in the
  instructions.
- `with_rationale.py` — winner plus a one-sentence explanation.

## When to use

- Building a preference dataset to fine-tune a reward model.
- Comparing two model versions on a held-out prompt set.
- Bake-offs between prompts.

If you want a single score against a rubric rather than a pairwise
comparison, use [`llm_as_judge/`](../llm_as_judge/).

## Run

```bash
python cookbook/data_labeling/text_pairwise_preference/basic.py
python cookbook/data_labeling/text_pairwise_preference/with_rubric.py
python cookbook/data_labeling/text_pairwise_preference/with_rationale.py
```

Requires `OPENAI_API_KEY`.
