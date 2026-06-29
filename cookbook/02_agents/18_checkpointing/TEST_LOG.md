# Checkpointing & Crash Recovery — Test Log

### 01_crash_recovery.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** Cancels an in-flight run to simulate a crash, then resumes via `/continue`.

**Result:** Syntax/compile verified. Not executed in this environment (needs a live model). The `asyncio.sleep(5.0)` crash window is empirically tuned and may need adjustment on slower machines.

---

### 02_tool_error_persistence.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** Tool-exception (caught) vs model-call failure (escapes, flushed to ERROR row), then `/continue` retry.

**Result:** Syntax/compile verified. Scenario B mutates `OPENAI_API_KEY` to force an auth error and restores it in a `finally` block.

---

### 03_checkpoint_endpoints.py

**Status:** NOT RUN (requires OPENAI_API_KEY)

**Description:** Exercises the `/checkpoints` timeline and snapshot GET endpoints via an in-process TestClient.

**Result:** Syntax/compile verified. Not executed.

---
