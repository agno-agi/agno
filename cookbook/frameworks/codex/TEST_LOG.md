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

## 2026-10-08: background lifecycle

### background_cancel.py

**Status:** PASS

**Description:** Ran the real SDK with this worktree imported. Started a detached streamed run, cancelled after the first content event, drained the SSE stream, and read the stored run. Claude used the API key exported by `.envrc`. Codex used `gpt-5.6-luna`, read-only sandboxing and `approval_mode="deny_all"`.

**Result:** The SDK turn was interrupted and the final output and database row were CANCELLED. Both the shared demo environment and the env-gated integration tests in the worktree's development environment passed.

---

### Lifecycle and regression suite

**Status:** PASS

**Description:** 736 tests covering external agents, native background execution, cancellation, event streams, status persistence, queue retries/fencing, scoped reads and A2A. All five real integration cases were enabled and passed: Claude two-process resume, Claude cancel, Codex cancel, sync PostgreSQL transcripts, async PostgreSQL transcripts.

**Result:** 736 unit/regression tests passed; 5 integration tests passed, none skipped. One existing AsyncMock warning arose in the unchanged native save-fencing test. Required format and validation scripts passed with SQLAlchemy 2.0.52.

---

### codex_metrics.py

**Status:** PASS (2026-10-10, openai-codex 0.161.0, gpt-5.6-luna)

**Description:** One plain turn, one streamed turn, then the session totals. Checks that `RunOutput.metrics` and the `RunCompleted` event carry the turn's token usage and duration, and that `session_data["session_metrics"]` equals the sum of the two runs.

**Result:** Run 1: 14693 input (14080 cached), 5 output, 14698 total, 4.5s. Run 2 (streamed): 15875 total, 4.7s. Session totals: 30573 tokens across 2 runs. Cost is unset because Codex does not report one.

---

### codex_metrics_agentos.py --verify

**Status:** PASS (2026-10-10, openai-codex 0.161.0, gpt-5.6-luna)

**Description:** Through the AgentOS test client: a non-streamed run, a streamed run, then `GET /sessions/{id}`, `GET /sessions` and `GET /metrics`. Asserts the session total equals the two runs and that the daily aggregation counts both runs.

**Result:** Run 1: 14700 tokens (11008 cached). Run 2 (RunCompleted event): 15877 tokens. Session: 30577; sessions list column 30577; metrics page agent_runs_count 2, total_tokens 30577.

---

### Codex turn usage across several model requests (review fix)

**Status:** PASS (2026-10-10, openai-codex 0.161.0, gpt-5.6-luna)

**Description:** Review finding: `usage.last` is one model request, not the turn, and `TurnResult.usage` is only the latest report, so a turn with tool calls under-counted on both paths. Replicated with a prompt that makes two shell calls, tapping every `thread/tokenUsage/updated` as (last, total). Fixed by computing the turn as the final thread total minus the thread total before the turn (first report's total minus its own request); the non-streaming path now consumes the notification stream itself instead of `handle.run()`. Reran `codex_metrics.py`, `codex_metrics_agentos.py --verify`, `codex_structured_output.py` and `codex_tools.py` to check the non-streaming path is unchanged.

**Result:** Before: streamed turn recorded 14972 of 44739 actual, non-streamed 14502 of 43341. After: streamed 44725 of 44725, non-streamed 43289 of 43289 (three requests each). Other cookbooks unchanged.

---
