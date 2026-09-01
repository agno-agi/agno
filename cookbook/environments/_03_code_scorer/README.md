# Code Scorer

Score typed outputs with deterministic Python. `CodeScorer` accepts a named
function returning a Boolean, a value from 0 to 1, or a complete `Score`.

## Files

- `basic.py` — exact Boolean scoring over one typed field.
- `continuous_score.py` — partial credit for independently verified
  intermediate fields with a strict pass threshold.
- `custom_score.py` — implements the public `Scorer` protocol and returns
  reasons plus structured details.

## When to use

Use code when correctness is executable: arithmetic, schema checks, SQL test
results, or any exact invariant. Boolean scores are the clearest learning-zone
signal because score variation then means exactly `0 < pass_rate < 1`.

See [`_02_task_sets/`](../_02_task_sets/) for providing expected values. Use
[`_04_judge_scorer/`](../_04_judge_scorer/) only when quality cannot be reduced
to a deterministic check.

## Run

```bash
python cookbook/environments/_03_code_scorer/basic.py
python cookbook/environments/_03_code_scorer/continuous_score.py
python cookbook/environments/_03_code_scorer/custom_score.py
```

Requires `OPENAI_API_KEY`. Every model call uses `OpenAIResponses` with
`gpt-5.5`.
