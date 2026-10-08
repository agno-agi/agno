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
