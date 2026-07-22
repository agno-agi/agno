# Judge Scorer

Ask a model judge to apply a written rubric when correctness is qualitative.
The judge model is explicit and contributes to the environment fingerprint.

## Files

- `basic.py` — binary judging of constrained customer-support replies.
- `numeric_rubric.py` — graded 1-10 judging with an explicit pass threshold
  and separate score-variation versus partial-pass reporting.
- `with_reference.py` — supplies `Task.expected` as fenced reference data to
  the judge.

## When to use

Use a judge for tone, completeness, faithfulness, or semantic equivalence
that cannot be checked reliably with code. Keep the rubric precise and
inspect failed reasons; a judge adds another model call to every attempt.

Prefer [`_03_code_scorer/`](../_03_code_scorer/) for executable invariants.
Continue to [`_05_tool_call_scorer/`](../_05_tool_call_scorer/) when the fact
being verified is tool execution rather than answer quality.

In numeric mode, `learning_zone()` means score-value variation. It does not
by itself guarantee `0 < pass_rate < 1`; `numeric_rubric.py` prints both sets.

## Run

```bash
python cookbook/environments/_04_judge_scorer/basic.py
python cookbook/environments/_04_judge_scorer/numeric_rubric.py
python cookbook/environments/_04_judge_scorer/with_reference.py
```

Requires `OPENAI_API_KEY`. Both policy and judge use `OpenAIResponses` with
`gpt-5.5`.
