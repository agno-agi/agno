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

## Fairness notes (multi-turn conversation)

The five-turn benchmark carries history through each framework's native
mechanism: Agno persists the session to a fresh in-memory database per
conversation with `add_history_to_context` (its default history cap of
three runs is raised so the full conversation stays in context, matching
the others); LangGraph uses an `InMemorySaver` checkpointer with one thread
per conversation; PydanticAI passes `message_history` explicitly; CrewAI
chains five tasks through `Task.context` in one crew, its native
sequential-context pattern — it has no lightweight conversation primitive,
and its memory feature requires an embedding provider, which would violate
the no-network constraint. Note the mechanisms differ in what they do per
turn: Agno's number includes reading and persisting the session every turn,
PydanticAI's includes no persistence at all. Every variant asserts after
the final turn that history actually accumulated, so a silently stateless
conversation fails instead of producing a flattering number.

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
