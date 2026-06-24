# Time Travel — Test Log

### 01_continue_from.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** `continue_from="end"`, `"last_user"`, and numeric `K` boundaries; COMPLETED runs auto-fork.

**Result:** Syntax/compile verified. Boundary resolution + pair-safe snapping are covered by unit tests in `test_unified_continue.py` (`TestTruncateHelper`, `TestTruncatePairSafety`).

---

### 02_fork_run.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** `fork=True` + a boundary to create an explicit non-destructive sibling run.

**Result:** Syntax/compile verified. Fork semantics (new run_id, lineage, non-destructive) covered by `TestForkHelper`.

---
