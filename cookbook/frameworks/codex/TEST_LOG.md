# Codex cookbook test log

Tested 2026-10-08 with openai-codex 0.161.0 (bundled Codex CLI 0.161.0), model gpt-5.6-luna, ChatGPT login.

### codex_basic.py

**Status:** PASS

**Description:** Smoke test -- `CodexAgent.print_response(..., stream=True)` in a read-only sandbox.

**Result:** Streamed a three-sentence answer; Response panel rendered with framework `codex`.

---

### codex_tools.py

**Status:** PASS

**Description:** Streaming run where Codex executes shell commands; verifies command executions show up as Agno tool calls.

**Result:** Codex ran `rg`/`ls` style commands in the read-only sandbox and produced a repository summary. Commands surfaced as `shell` tool calls with command and cwd args and aggregated output as the result.

---

### codex_session.py

**Status:** PASS

**Description:** Two-turn session with SqliteDb; verifies the Codex thread id is stored on the session and the second turn remembers the first.

**Result:** Turn 2 answered "Rust" from turn 1 context. `agno_sessions.session_data` holds `{"codex_thread_id": "<uuid>"}` and turn 2 resumed that thread.

---

### codex_mcp_tools.py

**Status:** PASS

**Description:** Connect Codex to the Agno docs MCP server via `config` overrides; verifies MCP tool calls surface as Agno tool calls.

**Result:** Tool Calls panel showed `mcp__agno_docs__search_docs(query=..., ...)` and the answer cited the Agno documentation.

---

### codex_structured_output.py

**Status:** PASS

**Description:** Non-streaming run with `output_schema`; verifies the content parses as JSON matching the schema.

**Result:** `json.loads(run_output.content)` returned an object with title, year, genres and one_line_pitch.

---

### codex_agentos.py

**Status:** PASS

**Description:** Serve a CodexAgent through AgentOS; verify /agents list and /runs.

**Result:** `GET /agents` listed `codex-assistant`; `POST /agents/codex-assistant/runs` (stream=false) returned status COMPLETED with the expected content.

---

### codex_session_agentos.py

**Status:** PASS

**Description:** Same as codex_agentos.py with SqliteDb-backed sessions; verify sessions persist across requests.

**Result:** Streaming run emitted RunStarted, RunContent deltas and RunCompleted over SSE. A second non-streaming request with the same `session_id` recalled the magic number from turn 1. `GET /sessions?type=agent` listed the session.

---

### ../00_quickstart/codex_agent.py

**Status:** PASS

**Description:** Quickstart: CodexAgent in a workspace-write sandbox on AgentOS with SQLite storage and tracing.

**Result:** `POST /agents/codex-agent/runs` returned status COMPLETED.
