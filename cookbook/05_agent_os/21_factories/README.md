# Factories

Factories let AgentOS construct an Agent, Team, or Workflow from the current
request instead of registering one long-lived component. They are useful when
tenant identity, validated client configuration, or trusted authorization
claims must change the component that handles each run.

The public run routes do not change: register an `AgentFactory`,
`TeamFactory`, or `WorkflowFactory` in the matching AgentOS collection, then
call the factory ID through the normal `/agents`, `/teams`, or `/workflows`
API.

## Files

| File | What it teaches |
|---|---|
| `01_basic.py` | Build a fresh tenant-aware Agent per request and verify the factory identity and persistence contract. |
| `02_with_input_schema.py` | Validate untrusted `factory_input` with Pydantic and observe invalid input map to HTTP 400. |
| `03_with_jwt_rbac.py` | Grant tools from verified JWT claims and scopes, with `FactoryPermissionError` mapped to HTTP 403. |
| `04_tiered_model.py` | Select an approved model configuration from a trusted subscription tier. |
| `05_team_factory.py` | Generalize per-request construction to a two-member Team. |
| `06_workflow_factory.py` | Generalize per-request construction to a two-step Workflow. |
| `07_async_factory.py` | Register synchronous and asynchronous factory callables on one AgentOS. |

## Prerequisites

Install the demo environment and export an OpenAI key:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

The examples use SQLite files under `tmp/`; no external database service is
required.

## Run

Start one factory server at a time:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/01_basic.py
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/02_with_input_schema.py
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/03_with_jwt_rbac.py
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/04_tiered_model.py
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/05_team_factory.py
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/06_workflow_factory.py
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/07_async_factory.py
```

Then run the same file with `--demo` in another terminal. The demo checks
`/health`, discovers the factory through its collection endpoint, and performs
the live run or error-path assertions for that lesson:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/21_factories/01_basic.py --demo
```

Every standalone server uses `http://localhost:7777`.

## Resolution contract

AgentOS invokes a registered factory for every request. Resolution validates
`factory_input`, calls the factory, checks the returned component type, and
then applies these invariants:

- the factory ID overrides the ID returned by the component;
- the factory database is inherited when the component does not set one; and
- `store_events` is enabled on the resolved component.

The returned component is fresh and request-scoped. A factory callable is
therefore on the request's latency and cost path: keep reusable model clients,
database objects, and other expensive resources outside the callable, and
construct only the configuration that must vary per request.

## Trusted and untrusted inputs

`factory_input` is supplied by the caller. Use `input_schema` to validate its
shape and use it only for configuration the caller is allowed to choose.

Authorization belongs in `ctx.trusted`. Authentication middleware populates
`ctx.trusted.claims` with verified token claims and
`ctx.trusted.scopes` with verified scopes. `03_with_jwt_rbac.py` demonstrates
that boundary: a role claim controls tool grants, while unsupported roles raise
`FactoryPermissionError` before a model runs.

## Synchronous and asynchronous factories

AgentOS resolves both callable kinds through the same async request path. A
synchronous factory may do ordinary in-memory construction; an asynchronous
factory can await request-time discovery or policy work. Avoid blocking I/O in
a synchronous factory.
