# Fork Session — Test Log

### 01_fork_session.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** `fork_session()` / `afork_session()` and `forked_from_session_id` lineage across nested forks.

**Result:** Syntax/compile verified. Session-fork behavior (new session, copied runs with fresh ids, non-destructive, lineage) is covered by unit tests in `test_unified_continue.py` (`TestForkSession`).

---
