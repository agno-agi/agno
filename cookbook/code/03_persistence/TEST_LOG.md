# Test Log - 03_persistence

Tested 2026-08-21 against `gpt-5.5` (OpenAIResponses), ipykernel 7.3.0, jupyter_client 8.9.1, dill 0.4.1, with the worktree's Python (agno from this branch, `from agno.tools.code import CodeMode`).

Every run prints one ipykernel line on stderr, `[IPKernelApp] WARNING | Kernel is running over TCP without encryption...`. It comes from ipykernel 7 at kernel start, does not apply to the loopback-only kernel CodeMode runs, and is not something this branch changes.

### basic.py

**Status:** PASS

**Description:** Variables survive a deliberate kernel kill. The example stores `readings` and `notes`, flushes a snapshot, kills the kernel, then asks again; it also prints the in-band `<code_mode_restored>` notice the model received.

**Result:** The second run answered sum 31 and note text "first pass" from the restored state, and printed `<code_mode_restored> Restored 2 variables: notes, readings. </code_mode_restored>` as the tool message the model was given. Exit 0, no traceback.

---

### developer_surface.py

**Status:** PASS

**Description:** The developer-facing surface: `run`, `variables`, `value`, `shutdown`, with no model.

**Result:** Ran clean three times with deterministic, correct output at all five print sites. Exit 0, no traceback.

---

