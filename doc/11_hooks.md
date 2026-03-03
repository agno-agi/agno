# Hooks System

Hooks let you inject custom logic at specific points in the agent execution lifecycle — without modifying the agent itself. They are the primary extension mechanism for cross-cutting concerns like logging, validation, transformation, and monitoring.

**Directory:** `libs/agno/agno/hooks/`
**Cookbook:** `cookbook/02_agents/09_hooks/`

---

## Hook execution points

```
User input
    │
    ▼
[pre_hooks]              ← run before the agent processes input
    │
    ▼
  Model call(s)
    │
    ▼
[Tool call] ──────────── [tool_call_hooks (before)]
    │                           │
    │                           ▼
    │                    Tool executes
    │                           │
    │                           ▼
    │                    [tool_call_hooks (after)]
    │
    ▼
[post_hooks]             ← run after the model produces a response
    │
    ▼
 (stream chunks) ──────── [stream_hooks]
    │
    ▼
  Response to user
```

---

## Hook types

| Parameter | When it runs | Receives |
|-----------|-------------|---------|
| `pre_hooks` | Before model call | `RunInput` |
| `post_hooks` | After model produces response | `RunResponse` |
| `tool_call_hooks` | Before and after each tool call | `ToolCallHookArgs` |
| `stream_hooks` | For each streaming chunk | `StreamChunk` |

---

## Pre-hooks — validate or transform input

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunInput

def log_input(run_input: RunInput) -> None:
    """Log every user message."""
    print(f"[INPUT] user_id={run_input.user_id}: {run_input.input_content[:100]}")

def uppercase_input(run_input: RunInput) -> None:
    """Transform: ensure input is never empty."""
    if not run_input.input_content.strip():
        run_input.input_content = "Hello"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    pre_hooks=[log_input, uppercase_input],
)
agent.print_response("What is 2+2?")
```

### Block with `InputCheckError`

Pre-hooks can block execution by raising `InputCheckError`:

```python
from agno.exceptions import InputCheckError, CheckTrigger
from agno.run.agent import RunInput

BLOCKED_WORDS = ["spam", "scam"]

def content_filter(run_input: RunInput) -> None:
    for word in BLOCKED_WORDS:
        if word in run_input.input_content.lower():
            raise InputCheckError(
                f"Message contains blocked content: '{word}'",
                check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
            )

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    pre_hooks=[content_filter],
)
```

---

## Post-hooks — process the response

```python
from agno.run.response import RunResponse
import json

def log_response(run_response: RunResponse) -> None:
    """Log response metrics after every run."""
    print(f"[METRICS] tokens={run_response.metrics.total_tokens} "
          f"cost=${run_response.metrics.total_cost:.4f}")

def save_to_database(run_response: RunResponse) -> None:
    """Persist response to an audit database."""
    audit_db.insert({
        "run_id": run_response.run_id,
        "content": run_response.content,
        "tokens": run_response.metrics.total_tokens,
    })

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    post_hooks=[log_response, save_to_database],
)
```

---

## Tool call hooks — intercept tool execution

**Cookbook:** `cookbook/02_agents/09_hooks/tool_hooks.py`

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.hooks.decorator import tool_hook

@tool_hook(on="before")
def before_tool(tool_name: str, tool_args: dict) -> dict:
    """Called before each tool execution. Can modify args."""
    print(f"[TOOL BEFORE] {tool_name}({tool_args})")
    # optionally modify and return new args:
    return tool_args

@tool_hook(on="after")
def after_tool(tool_name: str, tool_args: dict, tool_result: str) -> str:
    """Called after each tool execution. Can modify result."""
    print(f"[TOOL AFTER] {tool_name} → {tool_result[:50]}")
    return tool_result  # optionally transform the result

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    tool_call_hooks=[before_tool, after_tool],
)
```

### Tool hook use cases

- **Rate limiting**: track and throttle tool calls per user
- **Caching**: return cached result if identical call was made recently
- **Sanitisation**: clean up tool results before the model sees them
- **Auditing**: record every tool call with args and results
- **Cost control**: block tool calls that exceed a budget

---

## Stream hooks — process streaming chunks

**Cookbook:** `cookbook/02_agents/09_hooks/stream_hook.py`

```python
from agno.agent import Agent, RunEvent
from agno.models.openai import OpenAIChat

tokens_seen = []

def collect_tokens(chunk) -> None:
    """Collect all streamed tokens."""
    if chunk.event == RunEvent.run_response:
        tokens_seen.append(chunk.content)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    stream_hooks=[collect_tokens],
)

for chunk in agent.run("Tell me a joke", stream=True):
    print(chunk.content, end="", flush=True)

print(f"\n\nTotal chunks: {len(tokens_seen)}")
```

---

## Session state hooks

Hooks can read and write shared session state:

**Cookbook:** `cookbook/02_agents/09_hooks/session_state_hooks.py`

```python
from agno.run.agent import RunInput, RunResponse

RUN_COUNT_KEY = "run_count"

def increment_run_counter(run_input: RunInput) -> None:
    """Track how many times this session has been used."""
    count = run_input.session_state.get(RUN_COUNT_KEY, 0)
    run_input.session_state[RUN_COUNT_KEY] = count + 1

def add_run_count_to_response(run_response: RunResponse) -> None:
    """Append run count info to every response."""
    count = run_response.session_state.get(RUN_COUNT_KEY, 0)
    run_response.content += f"\n\n[Run #{count} in this session]"

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    pre_hooks=[increment_run_counter],
    post_hooks=[add_run_count_to_response],
)
```

---

## Async hooks

Hooks can be async functions:

```python
import httpx

async def async_webhook_hook(run_response: RunResponse) -> None:
    """Send run result to external webhook."""
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://hooks.example.com/agent-run",
            json={"content": run_response.content, "run_id": run_response.run_id},
        )

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    post_hooks=[async_webhook_hook],
)
await agent.aprint_response("Hello")
```

---

## Combining multiple hooks

Hooks are called in the order they are listed:

```python
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools(), CalculatorTools()],
    pre_hooks=[
        sanitise_input,         # 1st: clean the input
        log_input,              # 2nd: log it
        rate_limit_check,       # 3rd: enforce rate limits
    ],
    post_hooks=[
        log_response,           # 1st: log the response
        save_to_audit_db,       # 2nd: persist for compliance
        notify_webhook,         # 3rd: fire webhook
    ],
    tool_call_hooks=[
        cache_tool_calls,       # check cache before tool runs
        audit_tool_calls,       # log all tool calls with args
    ],
)
```

---

## Team hooks

Hooks work identically on `Team` objects:

```python
from agno.team import Team

team = Team(
    model=OpenAIChat(id="gpt-4o"),
    members=[agent1, agent2],
    pre_hooks=[log_team_input],
    post_hooks=[log_team_output],
)
```

---

## Registering hooks across the app (app hooks)

For application-wide hooks, register via the `agno_hooks` entry in your app's hooks system:

```python
# In your app hooks registration
agno_hooks = {
    "before_agent_run": ["my_app.hooks.audit.log_all_runs"],
    "after_agent_run":  ["my_app.hooks.metrics.track_usage"],
}
```

This registers the hook for all agents in the application without needing to modify individual agent definitions.

---

## RunInput fields available in pre-hooks

```python
run_input.input_content      # the user's message text
run_input.user_id            # current user identifier
run_input.session_id         # current session identifier
run_input.session_state      # mutable dict — shared state across hooks
run_input.images             # list of Image objects (multimodal)
run_input.audio              # list of Audio objects
run_input.run_id             # unique ID for this run
```

## RunResponse fields available in post-hooks

```python
run_response.content         # final response text
run_response.run_id          # matches run_input.run_id
run_response.metrics         # tokens, cost, latency
run_response.session_state   # shared state from pre-hooks
run_response.tool_calls      # all tool calls made
run_response.status          # "success" | "paused" | "error"
```
