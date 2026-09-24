# MCP

AgentOS can expose its agents, teams, and workflows as an MCP server at
`/mcp`. These examples cover the server side of that boundary: the default
operator surface, agents served directly as tools, custom tools, toolkits, PAT
authentication, tool scoping, and two OAuth deployment choices. Examples where
an Agno agent consumes another MCP server belong in `cookbook/91_tools/mcp`.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Serve the eight default AgentOS MCP tools. |
| `agents_as_tools.py` | Turn the default tools off and expose agents directly as named MCP tools. |
| `mcp_client.py` | Discover, pause, continue, cancel, and inspect runs with a protocol-level client. |
| `custom_tools.py` | Disable the default tools and expose one purpose-built tool. |
| `server_identity.py` | Set the name, version and instructions the server reports to connecting clients. |
| `toolkit_tools.py` | Serve a whole toolkit, flattened into one MCP tool per method. |
| `secure_mcp.py` | Mint a PAT, authorize its principal, restrict hosts and tool tags, and return full results. |
| `stateless.py` | Serve `/mcp` with no session between requests, so any replica can answer any request. |
| `oauth_builtin.py` | Run AgentOS's database-backed OAuth authorization server. |
| `oauth_authkit.py` | Use WorkOS AuthKit as an external authorization server. |

## Prerequisites

Install the MCP extras through the demo environment and set the model key:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

The examples use the current `mcp=` / `MCPConfig` API. The deprecated
spellings (`mcp_server=`, `MCPServerConfig`, `enable_builtin_tools`) are still
accepted as silent aliases.

## Default MCP tools

Plain `mcp=True` exposes eight tools:

| Tag | Tools |
|---|---|
| `core` | `get_agentos_config`, `run_agent`, `run_team`, `run_workflow`, `continue_run`, `cancel_run` |
| `session` | `get_sessions`, `get_session_runs` |
| `lifecycle` | `continue_run`, `cancel_run` (also tagged `core`) -- the pair rides along whenever components are exposed; include the tag explicitly to serve just the pair |

Run the server and client in separate terminals:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/basic.py
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/mcp_client.py
```

The client calls the tools directly. It continues one confirmation-required
run, cancels a second paused run, and reads the continued session from SQLite.
Run tools return a trimmed result by default: answer content plus
`run_id`, `session_id`, `status`, and unresolved requirements when paused.

## Server name, version and instructions

`server_identity.py` sets what a client learns in the initialize response:

```python
agent_os = AgentOS(
    name="Support AgentOS",
    version="1.4.0",
    agents=[support_agent],
    mcp=MCPConfig(
        name="Acme Support",
        version="1.4.0",
        instructions="This server answers questions about Acme products. Start with run_agent ...",
    ),
)
```

`name` defaults to the AgentOS name and `version` to `AgentOS(version=...)`.
`instructions` tells the calling model what the tools are for and how to use them;
Claude, Cursor and ChatGPT read it when they connect.

Open `/mcp` in a browser and you are sent to `/mcp/server-card`, a JSON Server Card
with the name, description and endpoint URL in the shape of the MCP Server Card
extension. The `version` is the one the server reports at connect time, so set it on
`MCPConfig` or `AgentOS` to publish your deployment's version rather than the default.
`MCPConfig(server_card=False)` turns it off.

The card also lists the served tools in the same shape `tools/list` returns — name,
title, description and `inputSchema` — built from each tool's own MCP representation,
so it cannot drift from the live surface. That makes the endpoint readable by people
and crawlers who never speak the protocol, while `tools/list` stays the authority a
connected client calls.

Behind a proxy or load balancer, set the public endpoint explicitly:

```python
mcp=MCPConfig(name="Acme Support", server_card_url="https://docs.agno.com/mcp")
```

Without it the URL is derived from the request, and `X-Forwarded-Host` is honoured only
when that hostname is itself listed in `allowed_hosts` — the card is publicly cacheable,
so an unvalidated forwarded host is never echoed into it.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/server_identity.py
```

## Agents as tools

`agents_as_tools.py` serves the deployment's agents as the whole MCP surface:

```python
agent_os = AgentOS(
    agents=[chief, researcher],
    mcp=MCPConfig(
        default_tools=False,
        tools=[
            chief,
            researcher.as_tool(
                name="deep_research",
                description="Thorough, sourced research. Send one clear question.",
            ),
        ],
    ),
)
```

`tools/list` then shows `chief` and `deep_research`, plus the riding
`continue_run`/`cancel_run` pair (see the HITL section). A bare component is named
after its id and described by its own description; `as_tool(name=...,
description=...)` publishes it under a model-facing name and pitch instead --
a tool description is a prompt for the calling model, so it often wants to be
different from the component's human-facing description. Either way the call
runs through the same machinery as `run_agent` (fresh session minting, RBAC
scopes such as `agents:run` -- keyed on the component id, not the tool name --
per-step progress), and the result's structuredContent carries the component
id for `continue_run`/`get_sessions`. Teams and workflows expose the same way.
Exposed components must be part of the AgentOS roster, and tool-name
collisions fail at startup.

Tool names (a bare component's id, or the `as_tool` override) must start with
a letter or underscore and contain only letters, digits, hyphens, and
underscores (at most 128 characters) -- the shape OpenAI, Anthropic, and
Gemini all accept. A name outside that shape fails at startup with a suggested
clean one; auto-derived ids from names like "Research & Writing Team" are the
usual trip.
Pick MCP-safe ids before a deployment accumulates sessions: sessions and
memories are keyed by the id, so changing it later is a migration. The exposed
tool list is fixed at startup: components added to a live deployment (resync)
are immediately runnable through the generic run tools where those are served,
but appear as named tools only after a restart -- and with
`default_tools=False` a component added after boot is unreachable over MCP
until the restart (the riding `continue_run`/`cancel_run` are bounded to the
components published at build time).

HITL works out of the box: whenever components are exposed, `continue_run` and
`cancel_run` ride along -- even with `default_tools=False` -- so a run that
pauses on a confirmation-required tool is resumable over MCP (the paused
result's structuredContent carries the component id, run_id, session_id, and
requirements that `continue_run` needs). The riding pair only acts on runs of
the published components: on an exposure-only server, runs of roster
components you left off `tools=` cannot be resumed or cancelled over MCP. Set
`lifecycle_tools=False` for a tools/list that shows exactly the configured
tools; paused runs then say to resume over the REST API.

## Custom and scoped surfaces

`custom_tools.py` passes an Agno `@tool` through
`MCPConfig(tools=[...])` and sets `default_tools=False`, leaving a
single client-visible tool.

`toolkit_tools.py` passes a whole `Toolkit` instead of a single tool. AgentOS
flattens it into one MCP tool per method -- `MemoryTools(enable_think=False,
enable_analyze=False)` becomes `get_memories`, `add_memory`, `update_memory`,
and `delete_memory` -- the way an agent takes a toolkit apart. Each flattened name goes through the same
collision check as a hand-written custom tool, so a toolkit method named like a
default tool (`WorkflowTools` really does register `run_workflow`) fails at
startup instead of silently replacing it. Narrow the published set with the
toolkit's own `include_tools` / `exclude_tools`.

Toolkit methods take framework arguments: every `MemoryTools` method declares
`run_context: RunContext`. Those are kept out of the client-facing schema and
filled server-side at call time, so `add_memory` publishes just `memory` and
`topics` while its body still receives a context carrying the authenticated
caller. This is not only about tidiness -- pydantic cannot build a schema for a
`RunContext`, so a visible one would stop the server from starting. The same
rule hides `Agent`- and `Team`-typed arguments, which arrive as `None` because
an MCP call runs outside any component. Media arguments stay visible: nothing on
this surface has run media to inject, so hiding one would leave it fillable by
nobody. So does a toolkit method's own `user_id` -- agno fills identity from the
RunContext, never by that name, so a `user_id` argument on a toolkit method is a
domain value (`ZoomTools` asks which account to read) and stays the caller's to
send. `user_id` on a tool you wrote for this surface is still filled from the
JWT subject, as before.

The identity in that RunContext is only as good as the deployment's
authorization: without `AgentOS(authorization=True, ...)` there is no JWT
subject, the resolved caller is `None`, and every client shares one identity.
Configure authorization before serving a toolkit whose data is per-user.

This server runs each tool call directly, so a toolkit's `connect()` and
`close()` never fire and every call is handed a fresh `RunContext`. The shipped
connection-managing toolkits (`PostgresTools`, `RedshiftTools`) connect
themselves on use and are unaffected. A toolkit whose state is keyed on the run
is not: `CodeMode` keys its kernel by `session_id`, so over MCP it would start a
kernel per call and accumulate nothing. Serve that one over REST, where a run
owns the session.

A tool whose approval gate this surface cannot honour is refused at startup
rather than published without it. `requires_confirmation`, `requires_user_input`
and `external_execution` all live in the call path an MCP request bypasses, so
`Workspace(root=".")` -- whose `delete_file` and `run_command` are
confirmation-gated -- fails fast and names the knob that frees it. Serve the
read-only surface (`allowed=["read", "list", "search"]`) instead.

`secure_mcp.py` demonstrates the full security configuration:

- `include_tags={"core", "session"}` followed by
  `exclude_tags={"session"}` leaves the six core tools.
- `result_mode="full"` returns the complete run object for programmatic
  clients.
- `allowed_hosts=[]` in the default environment enables host and Origin
  validation with only the built-in localhost allowances. Set
  `MCP_ALLOWED_HOSTS=agentos.example.com` for a deployment or tunnel.
- `authorize=` receives the authenticated principal and rejects callers
  outside the `sa:secure-mcp-client-*` integration namespace before a tool or
  model runs.

Set a root key, then run the server and its client in separate terminals:

```bash
export OS_SECURITY_KEY=$(openssl rand -base64 32)
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/secure_mcp.py

.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/secure_mcp.py --client
```

The client authenticates `POST /service-accounts` with `OS_SECURITY_KEY`,
receives the one-time `agno_pat_` value, and passes it to FastMCP as a bearer
token. The PAT resolves to `sa:<account-name>`; that verified identity is what
the `authorize` callback sees. This uses a synchronous OS-level `SqliteDb`
because service accounts live on `AgentOS(db=...)`, not merely on an
agent-attached database. See `../07_security/service_accounts.py` for mint,
scope, and revocation details.

## Stateless transport

`stateless.py` sets `MCPConfig(stateless=True)`. Every request builds its own
transport and nothing survives between requests, so no replica owns a caller's
session and a horizontally scaled deployment needs no session affinity -- an
ordinary load balancer is enough. Responses carry no `mcp-session-id` header.

What that costs is anything requiring a retained session: server-initiated
notifications and SSE resumability. Tool calls do not need one, so a pure tool
server loses nothing. Leave the flag off (the default) whenever the server has
to push to a client or resume an interrupted stream.

The flag is only passed to the transport when set, so an unset config keeps
whatever `fastmcp.settings.stateless_http` already establishes.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/stateless.py
```

### Claude Desktop and stdio-only clients

Store the PAT outside the JSON file and bridge the remote streamable-HTTP
server with `mcp-remote`:

```json
{
  "mcpServers": {
    "agentos": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://agentos.example.com/mcp",
        "--header",
        "Authorization:${AUTH_HEADER}"
      ],
      "env": {
        "AUTH_HEADER": "Bearer agno_pat_replace_me"
      }
    }
  }
}
```

Clients with native remote-MCP support can send the same
`Authorization: Bearer agno_pat_...` header directly.

## OAuth connectors

Claude.ai and ChatGPT custom connectors use OAuth rather than a pasted bearer
token. Both OAuth examples pass an `AuthProvider` object through `mcp_auth=`.
Unauthenticated `/mcp` requests receive an RFC 9728 challenge, while discovery
is served at `/.well-known/oauth-protected-resource/mcp`.

### Built-in authorization server

`oauth_builtin.py` uses `AgentOSBuiltinAuth.from_env()`:

```bash
export AGENTOS_URL=https://agentos.example.com
export MCP_CONNECT_SECRET=$(openssl rand -base64 32)
export AGENTOS_MCP_SIGNING_KEY=$(openssl rand -base64 32)  # optional
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/oauth_builtin.py
```

`AGENTOS_URL` must be the public origin the connector reaches.
`MCP_CONNECT_SECRET` must contain at least 16 characters. The optional signing
key must contain at least 32 high-entropy characters; otherwise AgentOS
generates and persists one. SQLite is suitable for this local lesson.
Production should pass a synchronous `PostgresDb` at the AgentOS level so
OAuth clients, codes, signing keys, and rotating refresh tokens survive
restarts and are shared by replicas. Async databases and agent-only databases
cannot back the built-in authorization server.

The built-in server owns `/register`, `/authorize`, `/token`, `/revoke`, and
`/mcp-auth/consent`, along with its OAuth metadata routes. Paste the public
`https://agentos.example.com/mcp` URL into the connector and enter
`MCP_CONNECT_SECRET` on the consent page.

### WorkOS AuthKit

`oauth_authkit.py` leaves authorization to an AuthKit tenant:

```bash
export AUTHKIT_DOMAIN=https://your-tenant.authkit.app
export AGENTOS_URL=https://agentos.example.com
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/oauth_authkit.py
```

Enable Dynamic Client Registration in AuthKit, register the public `/mcp`
resource indicator, and emit AgentOS scopes in the token's `scope` or `scp`
claim. A token carrying only `openid`, `profile`, and `email` authenticates but
cannot call the AgentOS tools; typical connector scopes are `config:read`,
`agents:run`, `teams:run`, `workflows:run`, and `sessions:read`.
