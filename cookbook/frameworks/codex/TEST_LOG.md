# Codex cookbook test log

All examples now live in this directory. Earlier entries retain the paths and
filenames used at the time of each run. See the final section for validation
of the consolidated paths.

## Earlier framework examples


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


## Refreshed starting examples


**Date:** 2026-10-09 (Europe/London)

**Source:** main `ff9b86d5be5245bd349e55c459bce45ba3d3cc21` plus this PR's cookbook/test changes, run from an isolated worktree before commit. The imported Agno path was the worktree's `libs/agno/agno/__init__.py`, not a released wheel or the user's checkout.

**Environment:** Python 3.12.8; editable Agno 3.1.2; SQLAlchemy 2.0.52; pytest 9.1.1. Fresh worktree development venv. Existing local CLI authentication; no credential values read or printed.

**Harness:** openai-codex 0.162.1; bundled codex-cli 0.162.1; model gpt-5.6-luna.

**Command:** `AGNO_TEST_CLAUDE_SDK=1 AGNO_TEST_CODEX_SDK=1 .venv/bin/python -m pytest libs/agno/tests/integration/agents/test_harness_cookbooks.py -q -o addopts=''`. Both providers together: 8 passed in 70.07 seconds; none skipped; no retries.

### basic.py

**Status:** PASS

**Description:** Real one-shot Agno wrapper run with the inclusive shipping-threshold prompt.

**Result:** Returned zero-dollar shipping and a COMPLETED RunOutput. A separate run with an invalid model exited 1 at the terminal-status assertion. A provider failure cannot silently pass this example.

---

### native_sdk.py

**Status:** PASS

**Description:** Same prompt/model using the native SDK directly.

**Result:** Returned zero-dollar shipping, a native Codex thread ID and successful terminal status. This is a one-shot API comparison, not a timing benchmark or native-resume test.

---

### tools.py

**Status:** PASS

**Description:** Real streamed review of shipping.py and orders.json through the Agno wrapper.

**Result:** Text deltas and tool start/end events appeared; returned tool data contained the fixture's subtotal and boundary values. The answer correctly explained fees 8, 0, 0. The final RunOutput completed with successful tool data. Fixture file hashes stayed unchanged.

---

### agent_os.py

**Status:** PASS

**Description:** Started this exact server script on a loopback port with a temporary SQLite directory. Exercised health, agent discovery, one non-streaming tool run and one SSE tool run in independent sessions. Retrieved both runs through GET /agents/{id}/runs/{run_id}?session_id=... .

**Result:** Both runs were COMPLETED and retained one shell result each. The SSE response contained 125 events in this run, including RunStarted, RunContent, ToolCallStarted, ToolCallCompleted and RunCompleted. IDs were consistent; no RunError/RunCancelled appeared. Both answers correctly explained the boundary. Fixture hashes were unchanged. Event counts vary and are not acceptance thresholds.

---

## Limits

**Clean-install follow-up:** This provider's four cases also passed in the
minimal README environment: agno[os,sqlite], the pinned SDKs, pytest and
pytest-asyncio, with SQLAlchemy 2.1.4. Both providers together: 8 passed in
74.15 seconds. The first collection attempt exposed a missing pytest-asyncio
setup instruction; it was corrected before rerunning. See the root test log.

No browser disconnect, server restart, native transcript recovery, production authorization, queue retry, compaction, approval, subagent or sandbox-replacement claim is made by these tests. API access was real loopback HTTP, not an in-process ASGI mock. The SQLite result checks are separate from native conversation durability. Older tests in cookbook/frameworks retain their historical scope.


## Claude API update regression — 2026-10-09

**Status:** PASS

**Description:** Reran all four Codex cases from the normal checkout as part of
the expanded nine-case harness suite. Codex code and model configuration were
unchanged. Used openai-codex 0.162.1, `gpt-5.6-luna`, and existing CLI credentials.

**Result:** All four passed; the combined suite passed nine cases in 70.28s.
Each HTTP run retained one successful shell tool result. The fixture remained
unchanged and the answers gave fees 8, 0, 0. See the root log for environment details.


## Shared adapter API update — 2026-10-09

### basic.py, native_sdk.py, tools.py and agent_os.py

**Status:** PASS

**Description:** Reran the combined opt-in live suite after switching basic.py
to the shared failure-aware printer and making adapter constructors keyword-only.

**Result:** All nine Claude/Codex cases passed in 61.99s, including the four
Codex script/HTTP cases. The full run also checks native Claude options.
Model and SDK versions are unchanged from the preceding entry. Runs used the
normal checkout at `924d4ceb90` plus the API update. Fixture integrity and stored
tool output checks passed. Full evidence and limits are in the
[root test log](../TEST_LOG.md#shared-adapter-dx-for-32--2026-10-09).

The shared regression suite passed 265 cases, including both sync/async printers
for success, error and cancellation, keyword-only signatures, unsupported media
rejection, SDK metadata compatibility and public typing.


### Live failed-run printing

**Status:** PASS

**Description:** Loaded each basic example without its main block, changed the
model only in memory to `invalid-harness-cookbook-model`, and invoked the printer.

**Result:** Both native providers rejected the request. Each wrapper displayed
`Run failed` and `Status: ERROR`, raised `AgentRunException`, and exited 1.
No example source or model default was changed, and neither check was retried.


## Consolidated paths — 2026-10-09

### codex_basic.py, codex_native_sdk.py, codex_tools.py and codex_agentos.py

**Status:** PASS

**Description:** Ran the actual examples from this directory, alongside the
existing advanced examples, through the updated live acceptance suite.

**Result:** All nine combined Claude/Codex cases passed in 60.23s with no skips
or retries. Correct shipping answers, actual tool data, HTTP/SSE, saved results
and fixture integrity checks passed. Native Claude options reuse also passed.
Source was `1d91efd765` plus the path consolidation in the normal checkout;
SDK/model versions are unchanged from the preceding runs. See the
[root log](../TEST_LOG.md#consolidated-framework-paths--2026-10-09) for complete
evidence and limits. This does not rerun this directory's advanced examples.
