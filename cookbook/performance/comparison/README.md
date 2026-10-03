# Cross-Framework Comparison Benchmarks

Compares Agno against LangGraph, PydanticAI and CrewAI on the costs a
framework imposes before any model is called: cold import and agent
construction (one OpenAI model reference plus one function tool, the same
shape for every framework).

Construction and import never call a provider, so these benchmarks run with
a placeholder API key and no network.

## Setup

These benchmarks need the performance environment, which holds all four
frameworks next to an editable install of this checkout's agno:

```bash
./scripts/perf_setup.sh
```

## Running

```bash
.venvs/perfenv/bin/python cookbook/performance/comparison/run_all.py
```

Results land in `cookbook/performance/results/comparison/summary.json`
(with framework versions recorded) and are picked up automatically by
`report.py`.

## Fairness notes (tool-call run)

The mocked model requests one tool call; the framework dispatches and
executes the real function; a second model turn answers. Every variant
asserts the tool actually executed. This is where Agno pays its deferred
tool-schema extraction (the flip side of its construction number). CrewAI
is excluded: with a custom model its tool use goes through a text-based
action protocol whose format is internal to the framework version, so a
mock would be testing the mock rather than the framework.

## Fairness notes (conversations: in-memory and durable)

The conversation benchmarks come in matched configurations in both
directions, so neither side's persistence philosophy is silently
advantaged:

- **In-memory** (5-turn and 25-turn): Agno runs with `cache_session=True`
  over an in-memory database — the closest analogue of LangGraph's
  always-cached `InMemorySaver`; PydanticAI passes `message_history`;
  CrewAI chains tasks through `Task.context`. Nothing is durably
  persisted by anyone.
- **Durable** (25-turn): Agno with `SqliteDb`, LangGraph with
  `SqliteSaver`; both serialize and write to a SQLite file every turn,
  with a fresh database file per conversation. Both adapters run
  SQLite's WAL journal mode (SqliteSaver configures it on its
  connection; SqliteDb enables it on every new connection), so the row
  compares frameworks rather than journal configurations. LangGraph's
  figure includes one graph compile (the checkpointer binds at
  compile). PydanticAI ships no persistence layer and CrewAI has no
  conversation primitive, so neither appears in this row.

Agno wins the 25-turn in-memory configuration and loses the durable one
by a narrow margin: its per-turn write path re-serializes conversation
state that grows with length. The results are published as measured;
the growth term is a known optimization target. Every variant asserts
after the final turn that history actually accumulated, so a silently
stateless conversation fails instead of producing a flattering number.

All conversation variants raise Agno's default history cap
(`num_history_runs=3`) so the full conversation stays in context, matching
the other frameworks, which carry uncapped history. CrewAI's conversation
rows use task-context chaining because it has no lightweight conversation
primitive, and its memory feature requires an embedding provider, which
would violate the no-network constraint.

## Fairness notes (run overhead)

The single-turn run benchmark replaces the model at each framework's own
model boundary: Agno via a `Model` subclass, LangGraph via langchain's
`GenericFakeChatModel`, PydanticAI via its public `TestModel`, CrewAI via a
`BaseLLM` subclass. Each framework skips its own provider wire-format work,
so every number is that framework's floor. CrewAI builds a fresh `Task` and
`Crew` per run because a crew kickoff is its unit of request execution; its
`Agent` is reused like the other frameworks' agents.

## Fairness notes

- Every framework builds the same thing: an agent object holding an OpenAI
  model reference and one plain function tool.
- Model clients are constructed but never invoked; no framework pays
  network costs.
- Telemetry is disabled for every framework that has it.
- Frameworks differ in how much construction work they defer. Agno defers
  tool schema extraction to the first run; the run-loop benchmarks in the
  parent suite measure that deferred cost. A framework doing schema work at
  construction pays it here instead. Both designs are valid; the numbers
  answer "what does creating an agent cost", not "which framework is
  better".
- LangGraph is measured through `langgraph.prebuilt.create_react_agent`,
  which compiles a state graph per call. LangGraph 1.x deprecates this
  entrypoint in favor of the separate langchain package's `create_agent`;
  it remains the canonical langgraph-only API.
- PydanticAI is installed as `pydantic-ai-slim[openai]`, its documented
  minimal install. The full `pydantic-ai` bundle hard-requires the logfire
  SDK, whose pydantic plugin loads whenever the first pydantic model class
  is defined — in a shared environment that inflates the measured cold
  import of every framework here, not just PydanticAI's. All benchmarked
  code paths (`TestModel`, the agent, message history) live in the slim
  package; only the observability bundle is omitted.
