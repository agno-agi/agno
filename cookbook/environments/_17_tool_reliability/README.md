# Tool Reliability

Measure whether the agent executed the required tool with the required
arguments across repeated attempts. A requested, refused, paused, or errored
call does not count as a clean execution.

## Files

- `basic.py` — score clean validation-code submissions with an exact argument.
- `with_reliability_eval.py` — apply `ReliabilityEval` to the same captured
  attempts and compare its execution evidence with `ToolCallScorer`.
- `repeated_reliability.py` — aggregate one reliability result per rollout
  attempt instead of trusting a single clean transcript.

## When to use

Use this when correctness depends on grounding, side effects, or a required
tool path. Continue to
[`_18_execution_matching/`](../_18_execution_matching/) for errored calls and
more exact argument cases.

The SFT exporter is text-only and excludes these tool-bearing runs. Tool
verification produces reliability evidence, not a training dataset.

## Run

```bash
python cookbook/environments/_17_tool_reliability/basic.py
python cookbook/environments/_17_tool_reliability/with_reliability_eval.py
python cookbook/environments/_17_tool_reliability/repeated_reliability.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
