# Test Log: 14_mcp

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in AgentOS server on port 7777, completed
its SQLite lifespan, checked `GET /health`, and connected to `/mcp` with a
FastMCP streamable-HTTP client.

**Result:** Health returned 200. MCP discovery returned exactly the eight
built-in tools: six tagged `core` and two tagged `session`, with
`operations-agent` present in `get_agentos_config`.

---

### mcp_client.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the checked-in protocol client against `basic.py`. It
discovered the server, triggered two confirmation-required agent runs, resolved
and continued the first requirement, cancelled the second paused run, and read
the continued session back through `get_session_runs`.

**Result:** Run `d8017422-1cff-4e7c-bd53-871f4b882ad5` paused, executed
`restart_service(service=billing)` after confirmation, and completed. Run
`ce32e6dd-cb6c-456a-92a0-4d01b177213c` paused and `cancel_run` acknowledged
its cancellation intent. The continued session returned one persisted run.

---

### custom_tools.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the custom-tool server, listed its MCP surface, and
called `ask_workspace` through a FastMCP streamable-HTTP client with a live
`gpt-5.5` agent response.

**Result:** The server exposed exactly one tool, `ask_workspace`, with no
built-ins. The call returned the requested exact response, `custom MCP works`.

---

### secure_mcp.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the security-key-protected server and ran its
checked-in `--client` flow. The client verified the allow-list rejection paths,
minted a service account through `POST /service-accounts`, connected to `/mcp`
with the returned PAT, listed the scoped tools, and ran the secured agent.

**Result:** The root security key was accepted for PAT minting but rejected by
the MCP `authorize` gate with 401; an untrusted Host was rejected with 400.
PAT principal `sa:secure-mcp-client-b0ebb699ad` authenticated, exactly the six
`core` tools were visible, and full-result run
`586b12d0-5bc3-47d6-b373-ede496e9d129` completed with its message list.

---

### oauth_builtin.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE

**Description:** Constructed `AgentOSBuiltinAuth.from_env()` with a synchronous
OS-level SQLite database and synthetic local deployment credentials, entered
the ASGI lifespan, and probed OAuth discovery and the unauthenticated MCP
challenge.

**Result:** `/.well-known/oauth-protected-resource/mcp` returned 200 and
`POST /mcp` returned the expected 401 with `resource_metadata`. The resolved
public route set included `/register`, `/authorize`, `/token`, `/revoke`,
`/mcp-auth/consent`, both metadata routes, and `/mcp`. A real connector login
was not claimed because no public deployment or end-user credential was used.

---

### oauth_authkit.py

**Status:** PASS

**Test mode:** CONSTRUCTION_SMOKE

**Description:** Constructed the current FastMCP `AuthKitProvider` with a
synthetic AuthKit tenant URL and local AgentOS origin, entered the ASGI
lifespan, and probed the provider-owned challenge surface without contacting a
real tenant.

**Result:** Protected-resource metadata returned 200 and unauthenticated
`POST /mcp` returned 401 with `resource_metadata`. The local route set stayed
minimal (`/mcp` plus metadata); AuthKit owns login and token endpoints. A live
AuthKit login was not claimed because no configured tenant was available.

---

## Validation

- All three credential-independent server/client paths completed with live
  model and MCP protocol calls.
- The secure flow proved root-key rejection at `/mcp`, Host rejection, PAT
  principal bridging, tag scoping, and `result_mode="full"` in one live loop.
- Both credential-gated OAuth tiers passed honest construction and route
  smokes without claiming an external login.
- The six focused MCP server, lifecycle, result, OAuth, built-in auth, and
  AuthKit source suites passed 218 tests.
- Python compilation and targeted Ruff format/check passed.
- Recursive structure and stale-surface scans checked exactly 6 Python files
  with no violations.
- `git diff --check` passed for the lesson and consumed legacy MCP folder.
- All scoped servers were stopped after testing.
