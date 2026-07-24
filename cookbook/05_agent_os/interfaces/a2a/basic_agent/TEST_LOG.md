# Test Log — basic_agent (A2A server + client pair)

## 2026-07-07 — Rebuilt on current abstractions (a2a-sdk 1.1.0)

The previous contents of this folder targeted the pre-1.0 `a2a-sdk` API
(pydantic types, `AgentExecutor`, 0.x AgentCard schema) and no longer imported
under `a2a-sdk>=1.0`. Rebuilt as a minimal pair: `AgentOS(a2a_interface=True)`
server + `A2AClient` client.

### server.py

**Status:** PASS

**Description:** Started via uvicorn on port 9999. Fetched
`/a2a/agents/basic-agent/.well-known/agent-card.json`.

**Result:** Card is v1-shaped: `supportedInterfaces` with `protocolVersion`
"1.0" and the correct interface URL, MIME-type input/output modes,
`capabilities.streaming: true`.

---

### client.py

**Status:** PASS

**Description:** Ran against the live server. `A2AClient` resolved the
agent card, opened a persistent official-SDK client (`async with` lifecycle),
fetched the card JSON and sent a message.

**Result:** Card printed, then the agent's one-sentence introduction returned
via the streamed A2A response. Connection closed cleanly.

---
