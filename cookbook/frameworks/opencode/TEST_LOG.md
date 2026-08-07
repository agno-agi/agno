# Test Log

Tested against OpenCode v1.17.20 (`opencode serve --port 4096`), using the
built-in `opencode` provider (default model).

### opencode_basic.py

**Status:** PASS

**Description:** Standalone `.print_response()` with streaming. The agent used
its read tools to inspect the server's working directory and streamed back a
summary with tool calls rendered in the terminal panels.

**Result:** Streaming content and tool-call panels rendered correctly.

---

### opencode_session.py

**Status:** PASS

**Description:** Two turns on the same Agno session_id with SqliteDb
persistence. First turn establishes a fact ("favorite language is Rust"),
second turn asks for it back.

**Result:** Second turn answered "Rust" — the Agno session correctly mapped to
a persistent OpenCode server session. Runs persisted to tmp/opencode_sessions.db.

---

### opencode_agentos.py

**Status:** PASS

**Description:** Served the OpenCode agent through AgentOS on port 7777.
Verified GET /agents lists the agent with framework metadata, non-streaming
POST /agents/opencode-dev/runs returns completed content, and streaming
returns the SSE lifecycle (RunStarted, RunContent, RunCompleted).

**Result:** All three endpoints behaved as expected.

---

### opencode_structured_output.py

**Status:** PASS

**Description:** Structured output via output_schema (Pydantic ProjectSummary
model) plus usage metrics. The agent analyzed the server's working directory
and returned a validated model instance; RunOutput.metrics reported token
totals and cost.

**Result:** Content was a ProjectSummary instance with populated fields;
metrics showed total tokens and cost. Also verified separately: streaming
structured output (RunCompleted carries the parsed model), run cancellation
via acancel_run ends the stream with RunCancelled and CANCELLED status, and
ClaudeAgent metrics capture (real cost reported from a Claude Code run).

---
