# Test Log: interfaces/a2a

> Library upgraded to `a2a-sdk>=1.0`. Interface-level smoke tests passed; the
> per-cookbook PASS/FAIL rows below still require real model API keys to run
> end-to-end.

## Interface smoke test (no model calls)

**Status:** PASS

**Description:** Boot AgentOS with the A2A interface enabled and exercise the
endpoints via FastAPI TestClient against a stub Agent (no OpenAI call). Verified:

- `GET /a2a/agents/{id}/.well-known/agent-card.json` returns a v1 AgentCard with
  `supportedInterfaces[0]` (`protocolBinding: JSONRPC`, `protocolVersion: 1.0`),
  `capabilities.extendedAgentCard`, and v1-shaped skills.
- `POST /a2a/agents/{id}/v1/message:send` round-trips with both v1 strict
  (`role: ROLE_USER`) and legacy lowercase (`role: user`) clients.
- Response body is a JSON-RPC 2.0 envelope around `SendMessageResponse` with
  oneof `task` payload; history Messages use flat `Part` with `mediaType`,
  enum strings are uppercased (`ROLE_AGENT`, `TASK_STATE_COMPLETED`).
- Invalid `params.message` returns 400 with a clear error.

**Result:** Interface is A2A 1.0 wire-compliant.

---

### basic.py

**Status:** PENDING

**Description:** Basic A2A-exposed Agno agent.

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
