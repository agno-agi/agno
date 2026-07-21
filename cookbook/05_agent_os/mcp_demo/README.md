# Mcp Demo Cookbook

Examples for `mcp_demo` in AgentOS.

## Files
- `mcp_server_example.py` — Example AgentOS app with MCP enabled.
- `custom_mcp_tool_example.py` — Expose ONE custom MCP tool routed through an agent, with the built-in tools disabled (uses `MCPServerConfig`).
- `oauth_builtin_example.py` — Add OAuth so claude.ai / ChatGPT can connect by pasting the `/mcp` URL, using the built-in authorization server (`AgentOSBuiltinAuth.from_env()`).
- `oauth_authkit_example.py` — Same, but with an external authorization server (WorkOS AuthKit) for production / multi-user.
- `mcp_tools_advanced_example.py` — Example AgentOS app where the agent has MCPTools.
- `mcp_tools_example.py` — Example AgentOS app where the agent has MCPTools.
- `mcp_tools_existing_lifespan.py` — Example AgentOS app where the agent has MCPTools.
- `test_client.py` — First run the AgentOS with `mcp_server=True` (`mcp_server_example.py`), then run this client against it.

## The MCP tool surface

`mcp_server=True` serves 8 built-in tools at `/mcp` — an operator surface for LLM
frontends (Claude, ChatGPT, Claude Code, Cursor), not a database console:

| Tool | Tag | What it does |
|------|-----|--------------|
| `get_agentos_config` | `core` | Discover agents/teams/workflows (ids + descriptions) and database ids. Call first. |
| `run_agent` / `run_team` / `run_workflow` | `core` | Run a component. Results are trimmed for the consuming model: answer text + media blocks + `run_id`/`session_id`/`status` (set `MCPServerConfig(result_mode="full")` for the complete run object). Long runs report MCP progress. |
| `continue_run` | `core` | Resume a PAUSED (human-in-the-loop) run by passing back its resolved requirements. |
| `cancel_run` | `core` | Request cancellation of a run by `run_id`. |
| `get_sessions` | `session` | List past conversations (read-only). |
| `get_session_runs` | `session` | Read a conversation's history (read-only, auto-detects session type). |

Session writes and memory CRUD live on the REST surface; anything else can be exposed as a
custom tool.

## Customizing the MCP server

Pass `mcp_server=MCPServerConfig(...)` to register your own tools, scope
the built-ins, gate the server, and protect it — all with data, no middleware classes to write:

```python
from agno.os import AgentOS
from agno.os.config import MCPServerConfig

agent_os = AgentOS(
    agents=[my_agent],
    mcp_server=MCPServerConfig(
        tools=[my_tool],            # custom tools (plain callables or Agno @tool / Function)
        enable_builtin_tools=False,  # ship ONLY your tools; or scope with:
        # include_tags={"core"},     # keep only tools tagged "core"
        # exclude_tags={"session"},  # drop the read-only session tools
        authorize=lambda user_id: user_id in OWNER_IDS,  # 401 non-owners before the model runs
        allowed_hosts=["my-app.example.com"],            # DNS-rebinding protection (localhost is automatic)
        # middleware=[Middleware(MyMiddleware)],          # escape hatch for anything else
    ),
)
```

Built-in tools are tagged `core` (config + run/continue/cancel) and `session` (the read-only
session tools). With plain `mcp_server=True`, all built-ins are registered. Custom tools share the same
`/mcp` mount, lifespan, and JWT middleware as the built-ins.

**Identity in custom tools.** Declare a `user_id` parameter on a custom tool and AgentOS fills it
with the authenticated caller's id (the JWT subject), hidden from the client-facing schema so it
can't be spoofed. Tools that need the full request can declare a FastMCP `Context` parameter, which
FastMCP injects natively.

**Gating.** `authorize=fn(user_id) -> bool` runs after JWT verification and returns 401 before any
tool or model runs — use it for an owner-only or allow-listed server.

**Transport security.** `allowed_hosts=[...]` turns on built-in DNS-rebinding protection: the request
Host (and Origin, when present) is validated against your list plus localhost defaults, so an
always-on local server can't be driven by a malicious web page via a rebound DNS name. You list only
your deploy/tunnel host; localhost works out of the box. `allowed_origins=[...]` is an advanced extra.

**Escape hatch.** `middleware=[...]` takes `starlette.middleware.Middleware` instances for anything
the options above don't cover.

## OAuth: connecting claude.ai and ChatGPT

A bearer-secured `/mcp` (JWT or `agno_pat_`) works for config-file clients — Claude Code,
Cursor, and Claude **Desktop** via the `mcp-remote` bridge. But **claude.ai (web)** and
**ChatGPT** custom connectors authenticate over **OAuth only** — there is no field to paste
a token. `AgentOS(mcp_auth=...)` adds OAuth to `/mcp` so those clients connect by pasting the
URL. It is opt-in: with `mcp_auth` unset, nothing changes. Existing `agno_pat_` and JWT clients
keep working alongside it.

**Tier 1 — built-in server (out of the box, `oauth_builtin_example.py`).** AgentOS becomes its
own OAuth authorization server, backed by its Postgres db. No external accounts. Never open:
connecting requires the deployer secret on a consent page.

```python
import os

from agno.os import AgentOS, AgentOSBuiltinAuth

# The inputs are spelled out so the config documents itself; the shorthand
# AgentOSBuiltinAuth.from_env() reads these same env vars.
mcp_auth = AgentOSBuiltinAuth(
    url=os.environ["AGENTOS_URL"],
    secret=os.environ["MCP_CONNECT_SECRET"],
    signing_key_material=os.environ.get("AGENTOS_MCP_SIGNING_KEY"),  # optional; env-pins the token key
)
agent_os = AgentOS(agents=[my_agent], db=postgres_db, mcp_server=True, mcp_auth=mcp_auth)
```

```bash
export AGENTOS_URL=https://your-deployment.example.com   # the public origin the client connects to
export MCP_CONNECT_SECRET=$(openssl rand -base64 32)            # the connect-page login secret (>= 16 chars)
export AGENTOS_MCP_SIGNING_KEY=$(openssl rand -base64 32)       # optional: env-pinned token key (>= 32 chars)
```

Then in claude.ai (Settings → Connectors) or ChatGPT (custom connector), paste your public
`/mcp` URL → sign in with the connect secret → connected. Access tokens are short-lived signed
JWTs; refresh tokens rotate on every use; the connect secret gates issuance, and rotating the
signing key (`AGENTOS_MCP_SIGNING_KEY`) is the revocation kill switch.

**Tier 2 — bring your own server (production / multi-user, `oauth_authkit_example.py`).** Pass
any fastmcp `AuthProvider` for real per-user identity, RBAC, and SSO. WorkOS AuthKit is the
documented default (free to 1M MAU):

```python
from fastmcp.server.auth.providers.workos import AuthKitProvider

agent_os = AgentOS(
    agents=[my_agent], db=postgres_db, mcp_server=True,
    mcp_auth=AuthKitProvider(authkit_domain=AUTHKIT_DOMAIN, base_url=PUBLIC_BASE_URL),
)
```

The same seam carries both tiers, so moving from built-in to an external AS is a config change.
`/info` describes the OAuth surface under `mcp.oauth` (the authorization server and resource URL)
so clients (and `agno connect`) can discover it; the top-level `auth_mode` reflects the REST/WS
auth posture only.

**Tier 2 scopes.** AgentOS enforces its scope map (`agents:run`, `teams:run`, `workflows:run`,
`sessions:read`, `config:read`) on the external token, so configure your AS to emit agno-format
scopes in the token's `scope`/`scp` claim per user — a token carrying only OIDC scopes
authenticates but is denied every tool. Mapping users to agno scopes at the AS *is* the Tier-2
per-user RBAC story. (The built-in Tier-1 server issues these scopes itself.)

**Own auth middleware on a `base_app`.** If you embed AgentOS in an existing FastAPI app and
install your own `JWTMiddleware`, the OAuth flow routes must be public or connector discovery is
blocked. Pass the exempt paths to your middleware's `excluded_route_paths`:

```python
from agno.os.mcp_auth import mcp_auth_route_paths

provider = AgentOSBuiltinAuth.from_env()
base.add_middleware(JWTMiddleware, verification_keys=[...],
                    excluded_route_paths=[*my_public_routes, *mcp_auth_route_paths(provider)])
agent_os = AgentOS(base_app=base, db=db, mcp_server=True, mcp_auth=provider)
```

AgentOS raises at `get_app()` (listing the exact paths) if a manual auth middleware would block
them, so this never fails silently. `os.mcp_auth_exempt_paths()` returns the same list.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).
