# Prime Agent cookbook test log

### prime_basic.py

**Status:** PENDING

**Description:** Standalone response with text and tool event streaming.

**Result:** Not run. Testing awaits user authorization.

---

### prime_session.py

**Status:** PENDING

**Description:** Two-turn conversation with SQLite persistence and native session resume.

**Result:** Not run. Testing awaits user authorization.

---

### prime_agentos.py

**Status:** PENDING

**Description:** AgentOS registration, streaming runs, and Postgres-backed session persistence.

**Result:** Not run. Testing awaits user authorization.

---

### prime_tools.py

**Status:** PENDING

**Description:** Stream native tool results while reviewing the sample shipping project.

**Result:** Not run. Testing awaits user authorization.

---

### prime_metrics.py

**Status:** PENDING

**Description:** Inspect reported usage/cost and persisted session totals.

**Result:** Not run. Testing awaits user authorization.

---

### prime_compaction.py

**Status:** PENDING

**Description:** Compact a native Prime session and continue the conversation.

**Result:** Not run. Testing awaits user authorization.

---

### prime_media.py

**Status:** PENDING

**Description:** Stage native image/text inputs and clean up uploaded files.

**Result:** Not run. Testing awaits user authorization.

---

### prime_retries.py

**Status:** PENDING

**Description:** Retry configuration and ephemeral native sessions.

**Result:** Not run. Testing awaits user authorization.

---

### Prime parity unit tests

**Status:** PENDING

**Description:** SDK identity, run-mode tool/metrics parity, usage aggregation,
session totals, native tool errors, ephemeral sessions, attachment cleanup,
input rejection, cancellation, and sync/async compaction guards.

**Result:** Authored in `libs/agno/tests/unit/agents/test_prime.py`; not run.
Unit tests and live Prime calls remain unrun. Static-check results are recorded below.

---

### prime_async.py

**Status:** PENDING

**Description:** Async non-streaming run and streamed response printing, with
terminal-status and expected-answer checks.

**Result:** Not run. Testing awaits user authorization.

---

### prime_background.py

**Status:** PENDING

**Description:** Submit a background run, poll its persisted terminal result,
and check that it completed with the expected answer.

**Result:** Not run. Testing awaits user authorization.

---

### prime_background_cancel.py

**Status:** PENDING

**Description:** Cancel a background SSE stream after its first text chunk and
check that both the terminal run and persisted result are cancelled.

**Result:** Not run. Testing awaits user authorization.

---

### prime_skills.py

**Status:** PENDING

**Description:** Load the included cookbook-report skill by explicit path with
automatic discovery disabled, then check its response marker.

**Result:** Not run. Testing awaits user authorization.

---

### prime_ephemeral.py

**Status:** PENDING

**Description:** Save two Agno runs while native persistence is disabled; check
recalled history and the absence of a native session ID.

**Result:** Not run. Testing awaits user authorization.

---

### prime_session_recovery.py

**Status:** PENDING

**Description:** Recreate the adapter with the same database, user, ID and native
session directory; check the recalled fact and retained native session ID.

**Result:** Not run. Testing awaits user authorization.

---

### prime_session_agentos.py

**Status:** PENDING

**Description:** Serve a local SQLite AgentOS and use the README's HTTP requests
to exercise session continuity, saved runs, SDK metadata and SSE streaming.

**Result:** Not run. Testing awaits user authorization.

---

## Static checks — 2026-10-12

- `./scripts/format.sh`: PASS with repository-pinned Ruff 0.15.20.
- `./scripts/validate.sh`: FAIL in the Agno mypy step, with mypy 2.1.0.
- All Ruff checks, agnoctl mypy and the quickstart pattern check pass.
- Both isolated adapter branches report the same 83 errors in 21 unchanged files,
  including existing typing errors and untyped optional dependencies. Neither
  new adapter has reported type errors after the fixes.
- These are static checks only. No unit suite, cookbook, provider call or server
  was executed. The PR remains a draft pending validation and runtime verification.
