# Code Fixes

Verify repair decisions against constrained, reviewable choices. These examples
score patch and regression-test ids instead of executing model-written code.

## Files

- `basic.py` — chooses the smallest safe fix for subtle production bugs.
- `patch_selection.py` — distinguishes patches whose hidden concurrency or
  protocol behavior differs.
- `regression_tests.py` — selects the minimal tests needed to lock in a fix.

## When to use

Use this pattern when a task can be expressed as a bounded repair decision and
checked deterministically. Keep untrusted generated code out of the cookbook
process; execute code only inside a separately designed sandbox.

This follows the SQL verification examples in
[`_22_sql_generation/`](../_22_sql_generation/). Continue to
[`_24_structured_extraction/`](../_24_structured_extraction/) for typed evidence
reconciliation.

## Run

```bash
python cookbook/environments/_23_code_fixes/basic.py
python cookbook/environments/_23_code_fixes/patch_selection.py
python cookbook/environments/_23_code_fixes/regression_tests.py
```

Requires `OPENAI_API_KEY`. Every model call uses `OpenAIResponses` with
`gpt-5.5`.
