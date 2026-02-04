# Dynamic Tools (Callable Tools)

This folder demonstrates **callable tools** - a pattern where tools are created dynamically at runtime based on the run context.

## Why Callable Tools?

Instead of passing a static list of tools to an agent:

```python
# Static tools - same for all users
agent = Agent(tools=[DuckDbTools(db_path="./shared.db")])
```

You can pass a function that creates tools at runtime:

```python
# Dynamic tools - created per-user
def get_user_tools(run_context: RunContext):
    user_id = run_context.user_id or "default"
    return [DuckDbTools(db_path=f"./data/{user_id}.db")]

agent = Agent(tools=get_user_tools)
```

## Use Cases

| Example | Description |
|---------|-------------|
| `01_user_namespaced_tools.py` | Per-user DuckDB isolation |
| `02_multi_tenant_tools.py` | Multi-tenant SaaS with tenant_id |
| `03_session_scoped_tools.py` | Per-session ephemeral databases |
| `04_conditional_tools.py` | Role-based tool access |
| `05_combined_dynamic_resources.py` | Callable knowledge + tools |
| `06_api_key_scoped_tools.py` | Per-user API credentials |

## Key Concepts

### run_context

The tool factory function receives a `RunContext` with:

```python
@dataclass
class RunContext:
    run_id: str
    session_id: str
    user_id: Optional[str] = None
    session_state: Optional[Dict[str, Any]] = None
    dependencies: Optional[Dict[str, Any]] = None
    # ... more fields
```

### Function Signature

Your tool factory can accept any of these parameters:

```python
def get_tools(run_context: RunContext) -> List[Tool]:
    ...

def get_tools(agent: Agent, session_state: Dict) -> List[Tool]:
    ...

def get_tools(run_context: RunContext, agent: Agent) -> List[Tool]:
    ...
```

## Quick Start

```python
from agno.agent import Agent
from agno.run import RunContext
from agno.tools.duckdb import DuckDbTools

def get_user_tools(run_context: RunContext):
    user_id = run_context.user_id or "anonymous"
    return [DuckDbTools(db_path=f"./data/{user_id}/db.duckdb")]

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=get_user_tools,  # Pass the function, not a list
)

# Each user gets their own database
agent.run("Create a table", user_id="alice")
agent.run("Create a table", user_id="bob")
```

## Caching

By default, callable tools and knowledge are cached per `user_id` (`cache_callables=True`). This avoids creating new database connections or expensive resources on every `run()`.

```python
# First run for alice - calls get_user_tools()
agent.run("Create table", user_id="alice")

# Second run for alice - uses cached tools (no new connection)
agent.run("Insert data", user_id="alice")

# First run for bob - calls get_user_tools()
agent.run("Create table", user_id="bob")
```

To disable caching (e.g., for role-based tools that may change):

```python
agent = Agent(
    tools=get_user_tools,
    cache_callables=False,  # Resolve tools on every run
)
```

### Custom Cache Key

By default, caching uses `user_id`. Use `callable_cache_key` to cache by session, tenant, or any custom key:

```python
# Cache by session_id instead of user_id
agent = Agent(
    tools=get_session_tools,
    callable_cache_key=lambda ctx: ctx.session_id,
)

# Cache by tenant_id from dependencies
agent = Agent(
    tools=get_tenant_tools,
    callable_cache_key=lambda ctx: ctx.dependencies.get("tenant_id", "_default_"),
)

# Cache by combination of user and tenant
agent = Agent(
    tools=get_tools,
    callable_cache_key=lambda ctx: f"{ctx.user_id}:{ctx.dependencies.get('tenant_id')}",
)
```

### Cache Management

```python
# Clear cache for a specific key
agent.clear_callable_cache(key="session_123")

# Clear cache for a user (shorthand)
agent.clear_callable_cache(user_id="alice")

# Clear all cached tools and knowledge
agent.clear_callable_cache()
```

## Running Examples

```bash
# Ensure dependencies are installed
pip install duckdb chromadb

# Run any example
python cookbook/91_tools/dynamic_tools/01_user_namespaced_tools.py
```

## Related

- `cookbook/07_knowledge/dynamic_knowledge/` - Same pattern for knowledge bases
- `cookbook/demo/agents/pal_agent.py` - Real-world example with callable tools
