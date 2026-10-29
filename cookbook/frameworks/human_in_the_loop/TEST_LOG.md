# Test log: harness permission requests in the chat

### agentos.py

**Status:** NOT YET RUN live with the chat flow

**Description:** AgentOS with a Docker-sandboxed Claude and Codex agent on a durable Postgres queue. A native permission request pauses the run with a confirmation tool; the chat confirms or rejects it and the same native process continues.

**Result:** Pending a live run in the AgentOS chat with a sandbox image built from this checkout. The earlier live runs for this folder covered the previous approvals flow and no longer apply.

---

### Deterministic checks

**Status:** PASS

**Description:** `tests/unit/agents/test_native_hitl.py` (74 cases, no model calls) and `tests/integration/sandbox/test_postgres.py` (real Postgres, both adapters).

**Result:** The pause is an ordinary confirmation tool with no approval fields and no approval rows; the chat's continuation delivers confirm or reject to the same waiting execution once, and a repeated or stale one is refused. The AgentOS stream ends at the pause and the continuation streams the rest. Native questions (Claude AskUserQuestion, Codex request_user_input) pause as user feedback like Agno's ask_user tool, and the selections reach the waiting execution, directly and through the sandbox runtime. Covered: expiry, cancellation, changed arguments, wrong session, snapshot failures, requests made at the same time pausing one after another, nested team and workflow requests, the sync continuation API, Codex transport shapes, queue reclaim without replay, and the conditional PAUSED to RUNNING write on Postgres and SQLite (a stale continuation after the run paused again is refused, and one of several racing connections wins), including a sandbox continuation that sees the runtime's next request without stored events.

---
