# Agui Cookbook

Examples for `interfaces/agui` in AgentOS.

## Files
- `agent_with_silent_tools.py` — Silent External Tools - Suppress verbose messages in frontends.
- `agent_with_tools.py` — Agent With Tools.
- `basic.py` — Basic.
- `multiple_instances.py` — Multiple Instances.
- `reasoning_agent.py` — Reasoning Agent.
- `research_team.py` — Research Team.
- `structured_output.py` — Structured Output.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).

## Production Notes

These notes apply when deploying the AG-UI interface to the public internet or
to a frontend hosted outside the default `localhost` allow-list.

### CORS

The AG-UI router does **not** set `Access-Control-*` response headers itself.
Cross-origin handling is owned by Agno's framework-wide CORS middleware
(`agno.os.utils.update_cors_middleware`), which is configured via the
`cors_allowed_origins` argument on `AgentOS`. This matches the pattern used by
every other Agno interface (`a2a`, `slack`, `telegram`, `whatsapp`).

The default allow-list covers common local-dev origins (`http://localhost:3000`,
the AG-UI dojo, and the CopilotKit quickstart). If your frontend runs on a
different origin you must add it explicitly:

```python
from agno.agent import Agent
from agno.os import AgentOS

agent = Agent(name="my-agent")
os = AgentOS(
    agents=[agent],
    cors_allowed_origins=[
        "https://your-frontend.example.com",
        "https://staging.your-frontend.example.com",
    ],
)
app = os.get_app()
```

Without the right entry, browsers will block the SSE connection with a CORS
error visible in the network console. Server logs will show the request
arriving successfully — only the browser rejects the response.

### Request body size

Agno does **not** ship an ASGI body-size limit middleware by default. Public
deployments should add one to bound memory usage and reject pathologically
large `RunAgentInput` payloads (very large `state`, `messages`, or `tools`
arrays). Two common options:

- The `content-size-limit-asgi` package (drop-in ASGI middleware).
- A small custom Starlette middleware that inspects `Content-Length` /
  enforces a streaming cap.

The closest in-tree scaffold to model from is
`agno/os/middleware/trailing_slash.py` — same ASGI-middleware shape, applied
in the same place during `AgentOS` setup.

For HITL-heavy deployments where clients re-echo the full AG-UI state on
every resume request, a 1–4 MiB cap is usually sufficient. The router itself
enforces a hard cap of **64 tool-result requirements per resume request**;
requests over that cap are rejected with
`RunErrorEvent(code="too_many_requirements")`.

### Resume snapshot trust boundary

When no database is configured, the AG-UI router embeds a serialised run
snapshot into the `StateSnapshotEvent` so the client can echo it back on
resume. This is a **client-controlled value** and is hardened accordingly:

- `system` and `developer` role messages from the snapshot are discarded
  (silent drop with `log_warning`).
- Tool-result requirements whose `tool_call_id` is not present in the
  snapshot's tools list are dropped; when all such requirements are
  rejected, `RunErrorEvent(code="resume_unknown_tool_id")` is emitted.
- An invalid `status` in the snapshot fails closed with
  `RunErrorEvent(code="invalid_resume_state")`.

For production workloads where the client can ever be hostile, configure a
real database (`agent.db = ...`) so resume goes through the authoritative
DB path instead of the state-snapshot fallback.
