# MCP

AgentOS can expose its agents, teams, and workflows as an MCP server at
`/mcp`. These examples cover the server side of that boundary: the built-in
operator surface, custom tools, PAT authentication, tool scoping, and two OAuth
deployment choices. Examples where an Agno agent consumes another MCP server
belong in `cookbook/91_tools/mcp`.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Serve the eight built-in AgentOS MCP tools. |
| `mcp_client.py` | Discover, pause, continue, cancel, and inspect runs with a protocol-level client. |
| `custom_tools.py` | Disable the built-ins and expose one purpose-built tool. |
| `secure_mcp.py` | Mint a PAT, authorize its principal, restrict hosts and tool tags, and return full results. |
| `oauth_builtin.py` | Run AgentOS's database-backed OAuth authorization server. |
| `oauth_authkit.py` | Use WorkOS AuthKit as an external authorization server. |

## Prerequisites

Install the MCP extras through the demo environment and set the model key:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

The examples use the current `mcp_server=` API and omit the legacy MCP
constructor aliases.

## Built-in MCP tools

Plain `mcp_server=True` exposes eight tools:

| Tag | Tools |
|---|---|
| `core` | `get_agentos_config`, `run_agent`, `run_team`, `run_workflow`, `continue_run`, `cancel_run` |
| `session` | `get_sessions`, `get_session_runs` |

Run the server and client in separate terminals:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/basic.py
.venvs/demo/bin/python cookbook/05_agent_os/14_mcp/mcp_client.py
```

The client calls the tools directly. It continues one confirmation-required
run, cancels a second paused run, and reads the continued session from SQLite.
Run tools return a trimmed result by default: answer content plus
`run_id`, `session_id`, `status`, and unresolved requirements when paused.

## Custom and scoped surfaces

`custom_tools.py` passes an Agno `@tool` through
`MCPServerConfig(tools=[...])` and sets `enable_builtin_tools=False`, leaving a
single client-visible tool.

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
