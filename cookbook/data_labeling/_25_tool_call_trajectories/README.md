# Tool Call Trajectories

Function-calling SFT data from real agno tool schemas and real tool-executing
rollouts - the framework generates its own training data. Single-call pairs
are validated in pure code against the exact JSON schemas the agent runtime
uses; multi-turn trajectories come from a simulated user talking to an
assistant that actually executes CalculatorTools calls, with the executed
calls (name, arguments, result) extracted from the RunOutput and a
temperature-0 judge deciding which rollouts are good enough to keep.

## Files

- `basic.py` - schema-validated (query, tool call) pairs. Pulls the real
  JSON schema of every CalculatorTools and DuckDuckGoTools function
  (via `Function.process_entrypoint()`), a generator agent writes 8
  candidate pairs against them, and a stdlib validator checks each pair:
  known tool, parseable JSON arguments, all required params present, no
  unknown params, primitive types match. Survivors carry `schema_source`
  provenance.
- `multi_turn_simulation.py` - 2 persona user-sim agents (dinner-bill
  splitting, homework checking) each pursue a multi-step calculation goal
  over up to 3 turns against an assistant that executes CalculatorTools
  calls for real. One row per conversation with messages, executed tool
  calls, and turn count.
- `judge_filter.py` - re-runs the simulation (imported from
  `multi_turn_simulation.py`, so it is standalone), then a temperature-0
  judge verifies each trajectory against the persona's goal and the
  executed tool calls. Kept rows carry the judge's reason in provenance.

Execution is deliberately limited to the offline CalculatorTools toolkit in
this demo: the DuckDuckGo tools appear schema-only in `basic.py` and are
never called, so runs are deterministic on the tool side and need no
network beyond the model API.

Rows are written to `data/generated/` (gitignored - run the scripts to
regenerate). Abridged rows from a real run:

```json
{"query": "Calculate the sum of 124.5 and 89.2", "tool_name": "add", "arguments": {"a": 124.5, "b": 89.2}, "schema_source": "agno.tools.calculator"}
{"persona": "dinner_host", "messages": [{"role": "user", "content": "Hey! I'm planning a dinner with some friends ..."}, ...], "tool_calls": [{"tool_name": "multiply", "arguments": {"b": 18.5, "a": 4}, "result": "{\"operation\": \"multiplication\", \"result\": 74.0}"}, ...], "turns": 3}
{"persona": "math_student", "messages": [...], "tool_calls": [...], "turns": 3, "provenance": {"judge": "gemini-3.5-flash", "reason": "The assistant correctly checked if 97 is prime using the 'is_prime' tool and computed 12 factorial divided by 10 factorial ... obtaining the correct result of 132."}}
```

## When to use

When you need function-calling or agentic SFT data and already run agents
with typed tools:

- Single-call pairs when you are teaching a model to emit well-formed calls
  against a fixed schema
- Multi-turn trajectories when you are teaching multi-step tool use with
  real execution results in context
- The judge filter when only verified-successful rollouts should reach
  training

The keep-what-passes shape is the same as
[`_21_rejection_sampling/`](../_21_rejection_sampling/) - here the sample
is a whole trajectory instead of a single response. To dedupe, filter, and
mix the kept rows at scale, use
[`_22_dataset_curation/`](../_22_dataset_curation/).

## Run

```bash
python cookbook/data_labeling/_25_tool_call_trajectories/basic.py
python cookbook/data_labeling/_25_tool_call_trajectories/multi_turn_simulation.py
python cookbook/data_labeling/_25_tool_call_trajectories/judge_filter.py
```

Requires `GOOGLE_API_KEY`.
