# Team Checkpointing & Crash Recovery — Test Log

### 01_crash_recovery.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** Cancels an in-flight team run mid-delegation to simulate a crash, then resumes via `/continue`.

**Result:** Syntax/compile verified. Not executed (needs a live model). The `asyncio.sleep(6.0)` crash window is tuned for a single delegation + checkpoint to land first; may need adjustment on slower machines.

---

### 02_tool_error_persistence.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** Team-level tool exception (caught) vs team model-call failure (escapes, flushed to ERROR row), then `/continue` retry.

**Result:** Syntax/compile verified. Scenario B mutates `OPENAI_API_KEY` and restores it in `finally`. The team flush helper is covered by `libs/agno/tests/unit/team/test_team_checkpointing.py` (`TestTeamFlushHelper`).

---

### 03_checkpoint_endpoints.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** Exercises the team `/checkpoints` timeline and snapshot GET endpoints via an in-process TestClient.

**Result:** Syntax/compile verified. Not executed.

---
