# Tool-call Scorer

Verify that an agent actually executed the tool a task depends on. A fluent
answer is not enough: `ToolCallScorer` reads successful executions from the run
record and scores the evidence.

## Files

- `basic.py` — require one named tool execution.
- `with_arguments.py` — require both the tool name and an exact argument subset.
- `strict_tools.py` — reject clean executions of unexpected tool names with
  `allow_additional=False`.

## When to use

Use this scorer when reliability depends on grounding, lookup, or action rather
than answer text alone. Start with name matching, add argument checks when the
called resource matters, and use strict mode when unexpected tool types are unsafe
or expensive. Strict mode uses tool-name set semantics; it does not enforce exact
call cardinality for an expected tool.

This follows [`_04_judge_scorer/`](../_04_judge_scorer/) and its rubric-based
checks. Next, [`_06_learning_zone/`](../_06_learning_zone/) turns mixed outcomes
into a task-selection signal.

## Run

```bash
python cookbook/environments/_05_tool_call_scorer/basic.py
python cookbook/environments/_05_tool_call_scorer/with_arguments.py
python cookbook/environments/_05_tool_call_scorer/strict_tools.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
