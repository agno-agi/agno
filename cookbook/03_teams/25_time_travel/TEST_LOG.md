# Team Time Travel — Test Log

### 01_continue_from.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** `continue_from="end"`, `"last_user"`, and numeric `K` boundaries; COMPLETED team runs auto-fork.

**Result:** Syntax/compile verified. Boundary + pair-safe snapping covered by `test_team_checkpointing.py` (`TestTeamTruncate`).

---

### 02_fork_run.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** `fork=True` + `continue_from="last_user"` for an explicit non-destructive sibling team run.

**Result:** Syntax/compile verified. Fork semantics (deep-copy, lineage, members not re-parented) covered by `TestTeamFork`.

---
