# LLM as Judge

Score a generated output against criteria. The same machinery as labeling -
input is the (prompt, response) pair, output is a structured score - but
applied to evaluating models rather than producing training labels.

## Files

- `basic.py` — single 1-5 score on overall quality.
- `single_rubric.py` — explicit multi-criterion rubric, per-criterion
  scores plus an overall.
- `with_rationale.py` — score plus a one-sentence rationale.

## When to use

- Evaluating model outputs in a test harness.
- Building eval dashboards for production agent workloads.
- Building reward-model training data (combine with
  [`text_pairwise_preference/`](../text_pairwise_preference/)).

## Run

```bash
python cookbook/data_labeling/llm_as_judge/basic.py
python cookbook/data_labeling/llm_as_judge/single_rubric.py
python cookbook/data_labeling/llm_as_judge/with_rationale.py
```

Requires `OPENAI_API_KEY`.
