# Dynamic Subagents

Dynamic subagents let an Agent or Team's LLM **spawn, use, and discard** ephemeral specialist agents mid-run — entirely on its own initiative, with no extra code from the developer after initial setup.

---

## The core idea

Normally, every tool call an agent makes dumps its raw output into the agent's message history. A database query that returns 50,000 tokens of JSON lives in that context forever (or until a CompressionManager shrinks it). Every subsequent model call pays that cost again.

Dynamic subagents solve this differently: the **raw data never enters the parent's context at all**.

```
Without subagents:
  orchestrator.run(...)
    → LLM calls query_db directly
    → 80,000 token JSON lands in orchestrator's run_messages
    → every future turn pays 80,000 tokens in input
    → context fills up, quality degrades

With dynamic subagents:
  orchestrator.run(...)
    → LLM calls spawn_agent(role="data_fetcher", task="query orders for CUS-123", tools=["query_db"])
    → subagent runs with its OWN isolated run_messages
    → subagent calls query_db → 80,000 token JSON stays in SUBAGENT's context
    → subagent returns "Customer has 23 orders; most recent: ORD-9921, $142, delivered"
    → orchestrator's context gains: 1 tool-result message (~20 tokens)
    → subagent discarded, its context garbage-collected
```

This is **context isolation by architecture** — not compression of what's already there, but prevention of it entering.

---

## Relationship to CompressionManager

These two features are complementary, not competing:

| Situation | Right tool |
|-----------|------------|
| Tool already ran, result is in context, context is growing | `CompressionManager` — retroactive compression |
| About to make a tool call that will return large output | `spawn_agent` — proactive isolation |
| Many small tool results accumulating | `CompressionManager` after N results |
| Complex multi-tool subtask, parent only needs the final answer | `spawn_agent` — full isolation |

You can use both simultaneously: enable `compress_tool_results=True` on your orchestrator *and* `enable_dynamic_subagents=True`. The subagent handles heavy isolation; compression handles anything that slips through.

---

## Quick start

```python
from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses

agent = Agent(
    name="orchestrator",
    model=OpenAIResponses(id="gpt-5.4"),
    enable_dynamic_subagents=True,
)

agent.print_response("Write a poem about Python, then explain its history.")
```

That's it. The LLM decides when spawning helps. You define nothing else.

---

## Full API

### `Agent` / `Team` fields

```python
Agent(
    enable_dynamic_subagents=True,   # opt-in flag

    subagent_template=Agent(...),    # base agent cloned per spawn (optional)
                                     # inherits parent model when None

    subagent_config=SubAgentConfig(...),  # spawn-time policy (optional)
)
```

### `SubAgentConfig` — spawn-time policy

```python
from agno.agent.subagent import SubAgentConfig

SubAgentConfig(
    # ── Tool delegation ──────────────────────────────────────────────
    inherit_parent_tools=False,   # give every subagent ALL parent tools
    allowed_tools=None,           # whitelist of delegatable tool names (None = all)
    allow_tool_selection=True,    # let LLM choose which tools each subagent gets
    context_heavy_tools=None,     # tool names → injected as "ALWAYS route via spawn_agent"

    # ── Model tier selection ─────────────────────────────────────────
    model_tiers=None,             # {"fast": "gpt-5.4-mini", "standard": "gpt-5.4", ...}
    allow_model_tier_selection=False,  # expose model_tier param to the LLM
    tier_hints=None,              # {tier_label: usage hint} shown to LLM; merged with defaults

    # ── Context injection ────────────────────────────────────────────
    inject_session_state=False,   # embed parent session_state as read-only JSON

    # ── Concurrency ──────────────────────────────────────────────────
    max_concurrent=5,             # enforced via threading + asyncio semaphore

    # ── Observability ────────────────────────────────────────────────
    log_subagent_runs=True,       # log spawn + completion lines (role, tokens, duration, depth)
    show_subagent_output=False,   # print subagent's full response to stdout (dev/debug only)
)
```

### `subagent_template`

The template is an ordinary `Agent`.  Every time `spawn_agent` is called, the framework does:

```python
spawned = template.deep_copy(update={
    "name": role,               # set by LLM
    "instructions": ...,        # set by LLM
    "tools": resolved_tools,    # filtered from template + parent tools
    "model": resolved_model,    # from model_tier or template
    "db": None,                 # always ephemeral
    "telemetry": False,
    "num_history_runs": 0,
    "enable_dynamic_subagents": False,  # no recursion
    "metadata": { lineage },
})
```

The template's model, knowledge base, markdown setting, tool_call_limit — everything carries over unless overridden.

---

## `spawn_agent` tool parameters

The LLM sees this tool:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `role` | str | yes | Name/persona for the subagent (e.g. `"sql_analyst"`) |
| `instructions` | str | yes | System-level instructions for the subagent |
| `task` | str | yes | The concrete task to run |
| `tools` | list[str] | no | Parent tool names to delegate (filtered by `allowed_tools`) |
| `expected_output` | str | no | Desired output format description |
| `model_tier` | str | no | `"fast"` / `"standard"` / `"powerful"` (requires `allow_model_tier_selection=True`) |

---

## Model tier selection

Define tiers once at setup. The LLM picks labels, never raw model strings — no hallucination risk, and you can rotate models without changing LLM behaviour.

```python
SubAgentConfig(
    model_tiers={
        "fast":     "gpt-5.4-mini",   # extraction, formatting, classification
        "standard": "gpt-5.4",        # summarisation, code, analysis
        "powerful": "o3",             # complex reasoning, research synthesis
    },
    allow_model_tier_selection=True,
)
```

**Cost impact:** If 40% of your production subagent calls are "fast" tier on the mini variant instead of the standard model, you reduce those calls' cost by 20–30x. At 10,000 requests/day this is material.

---

## Context-heavy tool routing

Tell the framework which tools produce large outputs. The LLM receives explicit guidance to always route them through `spawn_agent`:

```python
SubAgentConfig(
    context_heavy_tools=["query_orders_db", "fetch_webpage", "read_csv"],
)
```

This injects into the parent's system prompt:

```
ALWAYS route these tools through spawn_agent (they produce large outputs):
  - query_orders_db
  - fetch_webpage
  - read_csv
```

The LLM now has a deterministic rule for those tools. For everything else, it uses judgment.

---

## Auto-injected guidance

When `enable_dynamic_subagents=True`, the framework automatically appends a guidance block to the parent's instructions. You don't write it — the framework generates it from your config:

```
--- Dynamic Subagent Guidance ---
You have a spawn_agent tool that creates isolated specialist subagents.
Subagent tool outputs stay inside the subagent's own context — they
never appear in your message history, keeping your context clean.

USE spawn_agent when:
  - A tool returns large data (DB queries, file reads, API responses)
  - A subtask is self-contained: you only need the final answer
  ...
ALWAYS route these tools through spawn_agent (they produce large outputs):
  - query_orders_db
  ...
Model tier selection (use the model_tier parameter):
  - 'fast' → gpt-5.4-mini  (best for: extraction, formatting, classification)
  ...
--- End Subagent Guidance ---
```

---

## Lineage and observability

Every spawned subagent carries lineage in its `metadata`:

```python
{
    "spawned_by_agent_id": "parent-agent-id",
    "spawned_by_agent_name": "orchestrator",
    "spawn_role": "sql_analyst",
    "spawn_task": "Get total revenue for Q3 2024",   # actual task, not system prompt
    "spawn_depth": 1,    # 2 if the parent was itself a subagent
}
```

`spawn_depth` enables the full execution tree to be reconstructed from metadata alone. Subagents set `enable_dynamic_subagents=False` automatically — no recursive spawning.

---

## Concurrency

`max_concurrent` is enforced:
- **Async** (`aspawn_agent`): `asyncio.Semaphore` — the LLM can emit multiple `spawn_agent` calls in one turn; they all run concurrently up to the limit.
- **Sync** (`spawn_agent`): `threading.Semaphore` — same guarantee in threaded environments.

```python
SubAgentConfig(max_concurrent=3)  # at most 3 subagents at any moment
```

---

## When to use vs. when not to

**Use dynamic subagents when:**
- A tool returns large data that the parent doesn't need raw
- A subtask is fully self-contained (clear inputs → clear output)
- You want to use a cheaper model for routine subtasks
- You're building production workflows where context cost matters

**Don't use them when:**
- You need the raw output in your own reasoning chain
- The task requires back-and-forth with the user
- It's a single small tool call with minimal output
- The overhead of spawning is larger than the context savings

**How it differs from Teams:**
| | Team | Dynamic Subagents |
|--|------|-------------------|
| Members | Predefined in code | Created at runtime by the LLM |
| Lifecycle | Persistent across runs | Ephemeral (one task, then discarded) |
| Use case | Stable collaborative workflows | Ad-hoc context isolation |
| Model per member | Fixed at definition | Resolved from tier at spawn time |

---

## Cookbooks

| File | What it shows |
|------|---------------|
| `01_basic.py` | Minimal setup — LLM decides everything |
| `02_with_tools.py` | Tool delegation with whitelist |
| `03_parallel.py` | Async parallel spawning |
| `04_team.py` | Team integration with subagent_template |
| `05_model_tiers.py` | Cost-aware model tier selection |
| `06_context_isolation.py` | Full context isolation scenario with mock DB/KB tools |

---

## Technical changes introduced

### New: `agno/agent/subagent.py`

- **`SubAgentConfig`** (10 policy fields): `inherit_parent_tools`, `allowed_tools`, `allow_tool_selection`, `context_heavy_tools`, `model_tiers`, `allow_model_tier_selection`, `tier_hints`, `inject_session_state`, `max_concurrent`, `log_subagent_runs`, `show_subagent_output`
- **`SubAgentToolkit`**: uses `template.deep_copy(update={...})` instead of manual `Agent(...)` constructor; adds `threading.Semaphore` + `asyncio.Semaphore` for real concurrency enforcement; `build_guidance()` generates system-prompt injection; `spawn_agent` / `aspawn_agent` gain `model_tier` parameter; `spawn_task` in metadata now records the actual *task* string, not instructions

### Modified: `agno/agent/agent.py`

- New field: `subagent_template: Optional[Agent] = None`

### Modified: `agno/agent/_utils.py`

- `deep_copy_field`: `subagent_template` now handled like `reasoning_agent` — calls `.deep_copy()` instead of `deepcopy()`

### Modified: `agno/agent/_init.py`

- `set_dynamic_subagents`: builds guidance from config and injects it into `agent.instructions` (handles `str` / `list` / `None` / callable)

### Modified: `agno/team/team.py`

- New field: `subagent_template: Optional[Any] = None`

### Modified: `agno/team/_init.py`

- `_set_dynamic_subagents`: same guidance injection as agent side
