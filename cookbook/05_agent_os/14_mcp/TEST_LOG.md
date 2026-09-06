# Test Log: 14_mcp

Tested on 2026-07-24 against Agno source commit
`a463d3be3563d30d11d32d4f0f9dc23ccefdb4d2`.
`agents_as_tools.py` first tested LIVE on 2026-08-27 on the
`feat/mcp-agents-as-tools` branch (pre-lifecycle: `tools/list` showed exactly
`chief` and `deep_research`), alongside the folder-wide move to the `mcp=` /
`MCPConfig` / `default_tools` spellings (behavior unchanged; the old spellings
remain accepted aliases). Re-run LIVE on 2026-08-28 after the lifecycle
ride-along and the review-round fixes landed; the entry below records the
2026-08-28 run. Re-run LIVE again on 2026-08-30 after tool presentation
metadata (`title`, `annotations`) landed -- see the entry below the first.
`toolkit_tools.py` added and first tested LIVE on 2026-08-29, when a
`Toolkit` passed to `MCPConfig.tools` began flattening into one MCP tool per
method with the framework's own arguments filled server-side.

### agents_as_tools.py

**Status:** PASS

**Test mode:** LIVE (2026-08-28)

**Description:** Started the checked-in server (two gpt-5.6-luna agents,
`default_tools=False`, one exposed bare and one via
`researcher.as_tool(name="deep_research", description=...)` in
`MCPConfig(tools=[...])`) and drove it with a FastMCP streamable-HTTP client:
listed tools, checked the generated schemas and descriptions, ran `chief`
twice -- once sessionless, once continuing the returned session.

**Result:** `tools/list` returned `chief`, `deep_research`, and the riding
lifecycle pair (`continue_run`, `cancel_run`) introduced after the first run
of this cookbook. The `chief` tool carried the agent's own description plus
the session sentence; `deep_research` carried the as_tool override pitch. The
client-facing schema was `message` (required), `session_id`, `user_id`;
structuredContent carried `agent_id` ("chief") alongside
run_id/session_id/status, and (verified in a same-day re-run after the fix
landed) mirrors the answer text in its `content` key, so structuredContent-
rendering clients show the answer. The sessionless call minted a session and
completed with content "Earth"; the follow-up call on the returned session_id
recalled "Earth", proving live session continuity through the exposed tool.
The same re-run verified the publication bound on the riding pair:
`cancel_run` acted on the published `researcher` but refused an id outside
the publication list with the "published components" error.

---

### agents_as_tools.py (tool presentation metadata)

**Status:** PASS

**Test mode:** LIVE (2026-08-30)

**Description:** Re-ran the checked-in server after `title` / `annotations`
landed on `as_tool`, and drove it with a FastMCP streamable-HTTP client:
listed tools and read the presentation each one publishes, then called both
exposed tools.

**Result:** `tools/list` returned `chief`, `deep_research`, `continue_run`,
`cancel_run`. `chief` (bare) titled itself from the agent name and carried
the published-component defaults (`readOnlyHint` false, `destructiveHint`
true, `openWorldHint` true). `deep_research` carried the cookbook's
`title="Deep Research"` and its annotation override (`readOnlyHint` true,
`destructiveHint` false) merged over those defaults, with `openWorldHint`
still true from the default. Every tool's title also appeared in
`annotations.title`, so a client reading either slot shows the same name.
`deep_research` then ran to COMPLETED with a minted session and answered the
question; `chief` ran to COMPLETED.

---

### agents_as_tools.py (corrected annotations)

**Status:** PASS

**Test mode:** LIVE (2026-08-30, second run)

**Description:** Re-ran after two corrections: the cookbook's `deep_research`
override no longer claims `readOnlyHint` (a run writes a session row and a run
row, so the claim was false), and every tool the server composes now states all
three of `readOnlyHint`, `destructiveHint`, and `openWorldHint` rather than
leaving the ones that "do not apply" unset.

**Result:** `tools/list` returned `chief`, `deep_research`, `continue_run`,
`cancel_run`, and every one carried all three hints with no gaps:
`chief` false/true/true (published-component defaults), `deep_research`
false/false/true plus `idempotentHint` false (its override now refines the
default instead of contradicting it -- it appends to its own session and
destroys nothing), `continue_run` false/true/true, `cancel_run` false/true/false
(it writes this deployment's own run state and reaches nothing external).
`deep_research` ran to COMPLETED.

Re-run again the same day after `cancel_run` was corrected to
`openWorldHint` true (cancelling a Remote* component's run is an outbound
call to that deployment, so "reaches nothing external" was wrong): the four
tools published false/true/true, false/true/true, false/true/true, and
false/false/true respectively, with no hint left unset.

---

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
Re-run on 2026-08-30 after the example began declaring its presentation: the
tool published title "Ask the Workspace Agent" and all three hints
(`readOnlyHint` false -- the run persists a session, `destructiveHint` false,
`openWorldHint` true -- the agent calls a model over the network).

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

### stateless.py

**Status:** PASS

**Test mode:** LIVE (MCP transport), MOCK (model)

**Description:** Served the cookbook and checked the transport-level effect of
`MCPConfig(stateless=True)`. A raw `initialize` POST to `/mcp` was compared
against a default-config server started from the same process, since the flag's
whole observable difference is whether the server hands back a session.

**Result:** The stateless server answered `initialize` with 200 and **no**
`mcp-session-id` response header; the default server returned 200 **with** one.
Verified on fastmcp 4.0.2 / mcp 2.1.1. The four `test_mcp_server.py` stateless
unit tests pass, covering the flag being absent by default, forwarded as
`stateless_http=True` when set, absent for plain `mcp=True`, and the field
default. The agent run itself was not exercised end to end -- no
`OPENAI_API_KEY` was set in the test environment -- so the model path is
unverified here.

---

### server_identity.py

**Status:** PASS

**Test mode:** LIVE (MCP transport), MOCK (model)

**Description:** Served the cookbook (agno from this branch, fastmcp 4.0.2 / mcp
2.1.1) and connected a FastMCP streamable-HTTP client twice, once with
`mode="legacy"` and once with `mode="auto"`, to read what a client learns about
the server at connect time.

**Result:** Both handshakes reported `server_info` name `Acme Support` and version
`1.4.0` and the full instructions string from `MCPConfig(instructions=...)`; the
legacy handshake carried them in the initialize result and the 2026-07-28
negotiation exposed the same values on the client. `tools/list` returned the
eight default tools. No `OPENAI_API_KEY` was set, so `run_agent` was not
exercised. The four unit tests in `test_mcp_server.py` cover the AgentOS
defaults, the fastmcp fallback when nothing is set, the `MCPConfig` overrides,
and the initialize response.

Re-run with the Server Card: a browser-style `GET /mcp` (Accept `text/html`)
answered 302 to `/mcp/server-card`. The card came back as
`application/mcp-server-card+json` with the extension's CORS and cache headers,
name `localhost/acme-support`, title `Acme Support`, version `1.4.0`, the
AgentOS description and the endpoint URL. With `X-Forwarded-Proto: https` and
`X-Forwarded-Host: docs.agno.com` the name became `com.agno.docs/acme-support`
and the URL `https://docs.agno.com/mcp`. A GET with `Accept: text/event-stream`
was not redirected; fastmcp answered it with its own 400 for a missing session.

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

### toolkit_tools.py

**Status:** PASS

**Test mode:** LIVE (2026-08-29)

**Description:** Started the checked-in server (`MemoryTools(db=SqliteDb(...),
enable_think=False, enable_analyze=False)` passed whole to
`MCPConfig(tools=[...], default_tools=False)`) and drove it with a FastMCP
streamable-HTTP client at `http://localhost:7777/mcp`: listed tools, read every
generated schema, added a memory, read it back, and tried to supply the hidden
`run_context` from the client.

**Result:** `tools/list` returned exactly the toolkit's four methods --
`get_memories`, `add_memory`, `update_memory`, `delete_memory` -- each carrying
its own docstring as the description. `run_context`, which every one of those
methods declares, was absent from all four schemas: `add_memory` published
`memory` (required) and `topics`, `update_memory` published `memory_id`
(required) plus `memory` and `topics`, `delete_memory` published `memory_id`
(required), and `get_memories` published no arguments at all. `add_memory`
returned `success: true` with a generated `memory_id`, and `get_memories`
returned that same memory, so the server-filled RunContext reached the tool body
-- `run_context` is a required argument of `add_memory`, so the call could not
have succeeded without it. The run was unauthenticated, so the caller it carried
was None and the memory landed in the null-user bucket; the example's docstring
and the README now say so rather than implying per-caller ownership out of the
box. Supplying `run_context` from the client was
rejected by FastMCP as an unexpected keyword argument, which is the point of
hiding it rather than merely omitting it from the docs. The server was stopped
and the SQLite file removed afterwards.

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
- Recursive structure and stale-surface scans checked exactly 8 Python files
  with no violations.
- `git diff --check` passed for the lesson and consumed legacy MCP folder.
- All scoped servers were stopped after testing.
