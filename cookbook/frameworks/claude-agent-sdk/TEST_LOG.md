# Test log

## 2026-10-08

### session_store.py

**Status:** FAIL

**Description:** Launched the real two-process verification with claude-agent-sdk 0.2.148 using the shared demo environment and this worktree on PYTHONPATH. Both processes use fresh config directories.

**Result:** Process A reached Claude but returned `Not logged in`. Authentication for an empty config directory is not configured. Cross-process transcript resume remains unverified; this is not a passing integration run.

---

### Transcript and adapter unit tests

**Status:** PASS

**Description:** 70 agent tests passed, including SDK store conformance through one bound store per project, SQLite/AsyncSQLite persistence, key rewriting, retries, tools, and resume fallback. The optional summary contract is not implemented.

**Result:** Unit coverage passes; real SDK verification is separate.

---

### session_store.py (authenticated rerun)

**Status:** PASS

**Description:** Used the existing `ANTHROPIC_API_KEY` exported by `.envrc`, inherited by both child processes. No credential values were read or printed. Ran the demo environment with this worktree's `libs/agno` on PYTHONPATH and debug/monitor flags unset.

**Result:** Process A replied `OK` and stored the SDK transcript. Its Agno run history was deleted. Process B, with a separate empty config directory, replied `cobalt orchard 742`. Verified with the per-run ClaudeSDKClient implementation.

---

### PostgreSQL transcript conformance

**Status:** PASS

**Description:** Executed the SDK store contracts on PostgresDb and AsyncPostgresDb against disposable schemas in PostgreSQL 18. SQLite and AsyncSQLite also pass. The optional summary contract is not implemented. Tests use one bound store per project to reconcile the SDK suite's caller-selected project keys with this adapter's binding.

**Result:** Both PostgreSQL variants pass. A database transaction serializes position allocation across processes; the SQLite restart test resets the in-memory counter while holding time constant and verifies append order.

---

### Exact phase 1 source verification

**Status:** PASS

**Description:** Checked the committed phase 1 source independently of phase 2 in an isolated archive. Verified the imported Agno path before testing.

**Result:** 72 phase 1 agent tests passed and the original query-based adapter passed the real two-process resume test. Four additional missing-table/empty-batch tests cover every transcript DB adapter. Guard mutation checks all failed their named tests when the guard was removed and passed after restoration.

**Environment:** Python 3.12; claude-agent-sdk 0.2.148; openai-codex 0.162.0; SQLAlchemy 2.0.52, matching the demo environment. Fresh setup resolved SQLAlchemy 2.1.4, which reproduced six unrelated mypy errors on the unchanged base; validation passes with 2.0.52.

---

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
