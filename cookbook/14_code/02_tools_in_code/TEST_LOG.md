# Test Log - 02_tools_in_code

Tested 2026-08-21 against `gpt-5.5` (OpenAIResponses), ipykernel 7.3.0, jupyter_client 8.9.1, dill 0.4.1, with the worktree's Python (agno from this branch, `from agno.tools.code import CodeMode`).

Every run prints one ipykernel line on stderr, `[IPKernelApp] WARNING | Kernel is running over TCP without encryption...`. It comes from ipykernel 7 at kernel start, does not apply to the loopback-only kernel CodeMode runs, and is not something this branch changes.

### basic.py

**Status:** PASS

**Description:** `InventoryTools` is passed to `CodeMode(tools=[...])` and bound into the kernel as the awaitable handle `inventory`.

**Result:** The model called the toolkit with `await inventory.<method>(...)` inside a cell, composed the results in Python, and answered correctly for the generated inventory. Exit 0, no traceback.

---

### with_filesystem.py

**Status:** PASS

**Description:** The agent filesystem is composed into CodeMode as the awaitable `filesystem` handle.

**Result:** The agent read the data file through the handle, computed mean 16.1429 and sample standard deviation 7.9881 in the kernel, and wrote the report back through the same handle. Exit 0, no traceback.

---

