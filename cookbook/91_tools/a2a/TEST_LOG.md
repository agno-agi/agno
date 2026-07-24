# Test Log: 91_tools/a2a

### 01_call_agno_a2a_agent.py

**Status:** PASS

**Description:** Agno orchestrator calls `cookbook/05_agent_os/interfaces/a2a/basic.py` via `A2AClientTools`. Verified live: orchestrator emitted a `send_message(message=...)` tool call, the toolkit forwarded it to `basic_agent` at `localhost:7777`, the remote agent's response (multilingual greetings) came back, and the orchestrator surfaced it to the user. Tested 2026-05-19.

---
