# Test Log: interfaces/a2a

> Library upgraded to `a2a-sdk>=1.0`. Interface-level smoke tests passed; the
> per-cookbook PASS/FAIL rows below still require real model API keys to run
> end-to-end.

## Interface smoke tests

### TestClient: card + send + error path

**Status:** PASS

**Description:** AgentOS with the A2A interface enabled, exercised via FastAPI
TestClient against a stub Agent (no OpenAI call). Verified:

- `GET /a2a/agents/{id}/.well-known/agent-card.json` returns a v1 AgentCard with
  `supportedInterfaces[0]` (`protocolBinding: JSONRPC`, `protocolVersion: 1.0`),
  `capabilities.extendedAgentCard`, and v1-shaped skills.
- `POST /a2a/agents/{id}/v1/message:send` round-trips with both v1 strict
  (`role: ROLE_USER`) and legacy lowercase (`role: user`) clients.
- `POST /a2a/agents/{id}/v1` (JSON-RPC dispatch route) with `method: "SendMessage"` and the SDK-shaped body round-trips identically.
- Response body is a JSON-RPC 2.0 envelope around `SendMessageResponse` with
  oneof `task` payload; flat `Part` with `mediaType`, enum strings uppercased
  (`ROLE_AGENT`, `TASK_STATE_COMPLETED`).
- Invalid `params.message` returns 400 with a clear error.

### Live end-to-end with `a2a-sdk` Client

**Status:** PASS

**Description:** Booted `basic.py` cookbook on port 7777 (`gpt-4o` agent), used `a2a.client.create_client("http://127.0.0.1:7777/a2a/agents/basic_agent")` to fetch the card and send two prompts. Observed:

- Card fetched via `A2ACardResolver` is v1-shape (supportedInterfaces, capabilities.extendedAgentCard, JSONRPC binding).
- Streaming `send_message` yields:
  `status_update(WORKING)` → N × `artifact_update` (text chunks, `append=true`) → `status_update(COMPLETED)` → `task` (final, with full assembled history).
- All 10–14 events per run delivered to the SDK client (vs. 2 before the fix); reassembled text matches the streamed concatenation.

**Result:** Interface is wire-compliant with `a2a-sdk>=1.0.3` against the canonical SDK Client.

---

### basic.py

**Status:** PASS

**Description:** Basic A2A-exposed Agno agent. Booted on port 7777, talked to via the `a2a-sdk` `Client` end-to-end (card resolution + streaming `send_message`); see "Live end-to-end with `a2a-sdk` Client" above.

---

### agent_with_tools.py

**Status:** PENDING

**Description:** Agent with WebSearch tools over A2A.

---

### reasoning_agent.py

**Status:** PENDING

**Description:** Reasoning agent emitting reasoning step events over A2A streaming.

---

### research_team.py

**Status:** PENDING

**Description:** A team of Agno agents exposed as a single A2A endpoint.

---

### structured_output.py

**Status:** PENDING

**Description:** Agent returning a structured Pydantic response over A2A.

---
