# Test log

## 2026-10-09

### compaction.py

**Status:** PASS

**Description:** Seeds a fact, adds three turns including a 1200-line filler document, sends `/compact` as the run input with a `PreCompact` hook registered through `options_kwargs`, prints the transcript rows the compaction produced, then resumes the session from a second agent instance with a different working directory.

**Result:** 35 transcript rows before, 45 after. The hook fired with trigger `manual`. Rows 39 and 40 were the `compact_boundary` system entry and the `isCompactSummary` user entry. Replica B resumed from the database alone and answered `tangerine-walrus-88` from the summary. A conversation of one turn returns "Not enough messages to compact", which is why the cookbook adds turns first.

---

### continue_from.py (finished runs always fork)

**Status:** PASS

**Description:** Reran after `continue_run(fork=False)` on a completed run was changed to behave like native agents: the continuation becomes a new sibling run with fork lineage instead of rewriting the source run. Also exercised live with `background=True` on a completed run (ALPHA -> BETA -> GAMMA, three runs in the session, source run untouched).

**Result:** Checkpoints listed at 3, 5 and 6; branch from step 3 kept only `echo alpha`; replayed turn returned DONE. The in-place-with-background ValueError is gone.

---

### continue_from.py (review fixes)

**Status:** PASS

**Description:** Reran after the review fixes: checkpoints are exposed per tool batch (one per sequential step, one per parallel batch, anchored at the batch's last transcript entry), `continue_from=0` starts a branch before the prompt, `continue_from="last_user"` replays the selected user turn rather than only the first, cancelled runs are rejected, and in-place continuation refuses `background=True`. The cookbook now asserts on the tool results the branch carries instead of on the model's wording, so a run where Claude batches both commands still passes.

**Result:** Sequential run: checkpoints at messages 3, 5 and the end; the branch from step 3 carried only the first result and answered with the first command. Replay of the whole turn completed. A separate parallel run exposed a single checkpoint at the batch end.

---
## 2026-10-09

### transcript_store.py

**Status:** PASS

**Description:** Replaces `session_store.py`. Runs replica A (first turn, stores a fact) and replica B (second agent instance, different working directory) against one database in a single process, printing the `agno_transcripts` rows after each step. Ran with the demo environment, claude-agent-sdk 0.2.110, Claude Code 2.1.250 and macOS Keychain login, both without flags (SQLite) and with `--postgres` (pgvector container).

**Result:** On this branch's schema (positions numbered from 1, `framework` and `agno_session_id` columns): SQLite: replica A mirrored rows 1 to 12; replica B replied with the stored password, kept the same Claude session id, and appended rows 13 to 21. Postgres: same, 12 rows then 9 new. A Postgres table left over from the earlier branch schema raised a schema mismatch and had to be dropped first; it is recreated on first use. No API key or custom `CLAUDE_CONFIG_DIR` was needed because the SDK copies credentials into the temporary config directory it uses for a store-backed resume.

---

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


### Transcript mirror failure regression (2026-10-08)

**Status:** PASS

**Description:** The installed SDK parser and mirror batcher were driven with synthetic transport
frames and a transcript store that rejects every append. All three attempts failed. The completed
response retained its content and exposed `transcript_persistence_failed` in run metadata.
Streaming/non-streaming unit regressions also verify warning serialization and persisted history.

**Result:** Durability failure is visible without reexecuting completed work. This is a local SDK
fault-injection test, not a live provider run. Phase 1 agent tests: 78 passed. Format and validation pass.

### Lifecycle persistence review regressions (2026-10-09)

**Status:** PASS

**Description:** Injected terminal database failures in sync/async SQLite queue runs, with both
streaming modes and transient/permanent failures. Tickets retry and do not report success over
an unfinished run. Real sync/async PostgreSQL tests cover session-identity fencing and rollback
when session storage fails. In-memory SQLite async polling retains the completed run.

**Result:** 751 unit/regression tests, 12 external-agent PostgreSQL integration tests and 13 existing
native PostgreSQL tests passed. Format and validation passed. These are persistence fault-injection
checks; the earlier live provider cancellation runs were not repeated.

---

### session_store.py (transcript schema revision)

**Status:** PASS

**Description:** Reran the two-process verification after scoping transcript rows by framework, project, session and subpath, numbering positions per transcript and recording the owning Agno session. Used claude-agent-sdk 0.2.95 from the demo environment, the `ANTHROPIC_API_KEY` from `.envrc` and empty config directories.

**Result:** Process A replied `OK`; process B, with its Agno run deleted, replied `cobalt orchard 742`. The PostgreSQL contract test (PostgresDb and AsyncPostgresDb) passed against PostgreSQL 14.

---

### continue_from.py (2026-10-08)

**Status:** PASS

**Description:** Live run with claude-agent-sdk 0.2.95 and `claude-sonnet-4-6` on SQLite transcript storage. A two-step Bash turn listed checkpoints at both tool results and the end. Continuing from the first tool result with a question produced a branch that only knew `echo alpha`; `continue_from="last_user"` replayed the turn as a forked sibling. Separately, with `claude-haiku-4-5`, exercised AgentOS `/checkpoints` and `/continue` (non-stream and SSE), an in-place streamed continue, and a replay of a non-first turn that kept earlier context.

**Result:** Continue and checkpoints work end to end against the real SDK. Files touched after a checkpoint are not rewound.
