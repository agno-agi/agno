# Test Log: 20_remote

Tested live on 2026-07-24 against Agno source commit
`a7ffb023da5f99a1c43fe28a181e379d855831ba`.

Every Agno process loaded source from this worktree through
`PYTHONPATH=/Users/ab/code/worktrees/agno-agent-os-rewrite/libs/agno`.
Provider credentials were loaded with `direnv exec .`; no credential values
were recorded. The shared demo environment was not modified. The Google ADK
server ran in an isolated `uv` environment that resolved `google-adk==2.5.0`,
`a2a-sdk==0.3.26`, and `uvicorn==0.51.0`.

### servers/agentos_server.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the native AgentOS backend on port 7780 with two
Agents, one Team, one Workflow, and SQLite persistence. Restarted the same
server with `OS_SECURITY_KEY` for the authenticated example.

**Result:** Public `GET /health` returned `ok`; `GET /config` exposed
`assistant-agent`, `researcher-agent`, `research-team`, and `qa-workflow`.
After the secured restart, anonymous config and run requests returned HTTP 401
and an authorized config request returned HTTP 200.

---

### servers/a2a_server.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the Agno A2A REST backend on port 7781 and exercised it
through direct A2A and gateway requests.

**Result:** `GET /health` returned `ok`. The entity-scoped Agent card returned
`A2A Assistant`, the expected message-stream URL, and
`capabilities.streaming=true`. Live calculator requests returned 42 and 21.

---

### servers/adk_server.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the Google ADK A2A JSON-RPC backend on port 8001 in an
isolated `uv` environment and exercised it through direct and gateway requests.

**Result:** `GET /.well-known/agent-card.json` returned `facts_agent`, the root
RPC URL, and `capabilities.streaming=true`. JSON-RPC requests returned complete
facts about Saturn and Jupiter. Google ADK emitted its expected experimental
A2A-adapter warnings.

---

### 01_remote_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran one complete native `RemoteAgent` request and one typed
HTTP stream against the port 7780 backend.

**Result:** Run `2c2713c5-d7fb-48cf-9fe5-ed8d22bab167` returned 391. Streamed
run `97e89371-2846-44c1-b839-079cf0f85a01` emitted start, content, and
completion events and returned 42.

---

### 02_remote_team_and_workflow.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran a native `RemoteTeam` and `RemoteWorkflow` against the
port 7780 backend.

**Result:** Team run `7cd5aa69-8fd4-4eff-871b-f3cc9b0483a2` explained the
Agent/Workflow distinction. Workflow run
`eee0c5a8-23b0-41ad-a5bb-bed5f2acc8fe` used the calculator and returned 12.

---

### 03_remote_via_a2a.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Read the Agno REST Agent card, then ran Agno A2A REST and
Google ADK JSON-RPC `RemoteAgent` calls.

**Result:** Card-derived config identified `a2a-assistant`. Agno REST run
`818c6221-8e0d-4dda-b3ea-0b9615c5d6b5` returned 42. Google ADK JSON-RPC run
`592ef382-5616-4446-93cc-26658992c7da` returned a complete Saturn fact.

---

### 04_remote_as_team_member.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran one local Team with native AgentOS and A2A REST
`RemoteAgent` members in broadcast mode.

**Result:** Team run `a86c5c37-87be-48e3-ac58-980740cc0507` retained exactly
two member responses, synthesized their answers, and returned 96.

---

### 05_gateway.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the gateway on port 7777 after all three upstreams
were ready, checked discovery, and sent one non-streaming HTTP run to every
registered entity type.

**Result:** `GET /config` exposed four Agents (`gateway-agent`,
`assistant-agent`, `a2a-assistant`, and `facts_agent`), Team `research-team`,
and Workflow `qa-workflow`. All six requests returned complete content:
the local Agent identified itself, the native Agent returned 63, Agno A2A
returned 21, Google ADK returned a Jupiter fact, the Team explained one
Agent/Team difference, and the Workflow returned 9. Local, native AgentOS,
Team, and Workflow responses reported `COMPLETED`. The two A2A-backed responses
returned complete content with status `RUNNING`, matching the current A2A
status-mapping boundary; remote run polling and listing returned HTTP 400 as
documented.

---

### 06_remote_auth.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Passed the secured backend's development key through
`RemoteAgent.arun(auth_token=...)`.

**Result:** Authenticated run `ef0a6ce6-5ec7-4ba4-ae7e-1ef07d43b922`
completed and confirmed receipt of the request. The anonymous control request
returned HTTP 401.

---

## Validation

- All nine Python targets passed worktree-pinned compilation and targeted Ruff
  format/check.
- Recursive inventory and pattern validation checked exactly nine Python files
  with zero violations.
- Focused remote-component unit tests passed: three tests in
  `libs/agno/tests/unit/team/test_remote_team.py`.
- The three upstream readiness contracts, four direct clients, six-entity
  gateway matrix, and secured restart were executed live.
- All four listeners on ports 7777, 7780, 7781, and 8001 were stopped after the
  run.
- The assigned legacy `remote/` tree and remaining `client_a2a/servers/` files
  were removed.
- `git diff --check` passed for the rewritten and deleted paths.
