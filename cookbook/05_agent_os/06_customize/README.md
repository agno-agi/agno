# Customize AgentOS

Choose the extension point that owns the behavior:

| Extension point | Use it for | Example |
|---|---|---|
| `base_app` | Mount AgentOS routes on an existing FastAPI application. | `basic.py` |
| `on_route_conflict` | Choose whether AgentOS or the base app owns duplicate routes. | `route_conflicts.py` |
| `lifespan` | Initialize resources or update components at process startup and clean up at shutdown. | `lifespan.py` |
| Middleware | Apply request, response, rate-limit, or integration behavior around the whole OS. | `custom_middleware.py`, `response_middleware.py` |
| Request data | Send custom events and per-request dependencies through served runs. | `custom_events.py`, `dependencies.py` |
| Settings and CORS | Set allowed browser origins and a shared OS security key. | `cors_and_security_key.py` |
| Authorization | Configure JWT, RBAC, user isolation, and service accounts. | [`07_security`](../07_security) |

## Setup

From the repository root:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=your-key
```

Every example listens on port 7777. Start one at a time.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Preserve a `/customers` route by passing an existing FastAPI instance as `base_app`. |
| `route_conflicts.py` | Keep custom `/` and `/health` handlers with `preserve_base_app` while retaining `/config`. |
| `lifespan.py` | Add a second agent at startup and call `agent_os.resync(app)`. |
| `custom_middleware.py` | Add logging and rate limiting, with the last-added middleware running first. |
| `response_middleware.py` | Observe JSON and SSE body frames with a public ASGI wrapper and no private response imports. |
| `custom_events.py` | Carry a typed custom tool event through the AgentOS SSE stream. |
| `dependencies.py` | Resolve an instruction template from request-scoped JSON dependencies. |
| `cors_and_security_key.py` | Replace the allowed browser origins and enforce Bearer authentication with `AgnoAPISettings`. |

## Run the servers

```bash
.venvs/demo/bin/python cookbook/05_agent_os/06_customize/basic.py
```

Then inspect the custom route and AgentOS discovery route:

```bash
curl http://localhost:7777/customers
curl http://localhost:7777/config
```

`response_middleware.py`, `custom_events.py`, `dependencies.py`, and
`cors_and_security_key.py` include a checked-in `--demo` client. Start the file
without flags in terminal 1 and run the same file with `--demo` in terminal 2.

Starlette middleware order is LIFO: the middleware added last is the outermost
layer and receives an inbound request first.

For the security example, set `OS_SECURITY_KEY` in both terminals to replace
the local demonstration value:

```bash
export OS_SECURITY_KEY=replace-me
```

Passing `cors_allowed_origins` replaces AgentOS's default origins; include
every browser origin your deployment should allow.
