# Agent Factories

Per-request, context-driven agent construction for multi-tenant AgentOS deployments.

Factories let you build agents dynamically on each request based on who is calling,
what they're allowed to do, and what they asked for. Instead of pre-building a fixed
set of agents, you register a callable that AgentOS invokes with a `RequestContext`.

## Examples

| File | Description |
|------|-------------|
| `01_basic_factory.py` | Simplest factory -- per-tenant instructions |
| `02_input_schema_factory.py` | Factory with a pydantic input schema for client-controlled parameters |
| `03_jwt_role_factory.py` | JWT-driven tool grants (RBAC) using the trusted context |

## Setup

```bash
# Start Postgres (required for session persistence)
./cookbook/scripts/run_pgvector.sh

# Use the demo venv
.venvs/demo/bin/python cookbook/05_agent_os/factories/01_basic_factory.py
```

## How it works

1. Register an `AgentFactory` alongside normal agents in `AgentOS(agents=[...])`.
2. Client hits `POST /agents/{factory-id}/runs` exactly like a prototype agent.
3. AgentOS builds a `RequestContext` from the request and calls your factory.
4. The factory returns a fresh `Agent` instance, used for that single request.

The `RequestContext` separates trusted (middleware-verified) and untrusted (client-sent)
fields so authorization decisions are visible at code review time.

## Key classes

- `AgentFactory` -- registered callable that produces an Agent per request
- `RequestContext` -- identity, input, trusted claims threaded to every factory
- `TrustedContext` -- claims/scopes from verified middleware (e.g. JWT)
- `TeamFactory` / `WorkflowFactory` -- same pattern for teams and workflows
