# Agent / Team / Workflow Factories

Per-request, context-driven construction for multi-tenant AgentOS deployments.

Factories let you build agents, teams, and workflows dynamically on each request
based on who is calling, what they're allowed to do, and what they asked for.

## Examples

### Agent Factories

| File | Description |
|------|-------------|
| `agent/01_basic_factory.py` | Simplest factory -- per-tenant instructions |
| `agent/02_input_schema_factory.py` | Factory with a pydantic input schema for client-controlled parameters |
| `agent/03_jwt_role_factory.py` | JWT-driven tool grants (RBAC) using the trusted context |
| `agent/04_tiered_model_factory.py` | Model selection based on subscription tier |

### Team Factories

| File | Description |
|------|-------------|
| `team/01_basic_team_factory.py` | Per-tenant team with billing and tech support members |
| `team/02_tiered_team_factory.py` | Team size and model quality scale with subscription tier |

### Workflow Factories

| File | Description |
|------|-------------|
| `workflow/01_basic_workflow_factory.py` | Per-tenant content pipeline (draft + edit) |
| `workflow/02_tiered_workflow_factory.py` | Pipeline depth scales with subscription tier (2 vs 3 steps) |

## Setup

```bash
# Start Postgres (required for session persistence)
./cookbook/scripts/run_pgvector.sh

# Use the demo venv
.venvs/demo/bin/python cookbook/05_agent_os/factories/agent/01_basic_factory.py
```

## How it works

1. Register an `AgentFactory` / `TeamFactory` / `WorkflowFactory` in `AgentOS(agents=[...])`, `teams=[...]`, or `workflows=[...]`.
2. Client hits the same endpoint as a prototype component (e.g. `POST /agents/{id}/runs`).
3. AgentOS builds a `RequestContext` from the request and calls your factory.
4. The factory returns a fresh instance, used for that single request.

The `RequestContext` separates trusted (middleware-verified) and untrusted (client-sent)
fields so authorization decisions are visible at code review time.

## Key classes

- `AgentFactory` / `TeamFactory` / `WorkflowFactory` -- registered callables that produce components per request
- `RequestContext` -- identity, input, trusted claims threaded to every factory
- `TrustedContext` -- claims/scopes from verified middleware (e.g. JWT)
