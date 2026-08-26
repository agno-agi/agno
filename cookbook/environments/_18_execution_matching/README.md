# Execution Matching

Match required behavior against tool executions rather than assistant-side
requests. Clean execution means the tool ran without an error or paused state;
argument matching reads the parsed arguments recorded on that execution.

## Files

- `basic.py` — combine a required validation tool with an exact computed argument.
- `failed_calls.py` — show that an attempted tool call which raises does not
  satisfy the scorer.
- `argument_matching.py` — use subset matching for an exact validation code
  while allowing extra actual arguments.

## When to use

Use this after [`_17_tool_reliability/`](../_17_tool_reliability/) when a model
can request the right tool but still execute the wrong operation. Continue to
[`_19_error_analysis/`](../_19_error_analysis/) to inspect failures in detail.

These tool-bearing runs are reliability evidence. The text-only SFT exporter
excludes them rather than dropping the tool trace and teaching an ungrounded
answer.

## Run

```bash
python cookbook/environments/_18_execution_matching/basic.py
python cookbook/environments/_18_execution_matching/failed_calls.py
python cookbook/environments/_18_execution_matching/argument_matching.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
