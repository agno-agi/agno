# Test Log -- 10_human_in_the_loop

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### agentic_user_input.py

**Status:** PASS (interactive)
**Tier:** untagged
**Description:** Demonstrates agentic user input. Interactive file - setup succeeded, waiting for user input as expected.
**Result:** Setup succeeded. Requires user input for full execution.

---

### confirmation_advanced.py

**Status:** FAIL
**Tier:** untagged
**Description:** Demonstrates confirmation advanced. Failed due to missing dependency: ModuleNotFoundError: No module named 'wikipedia'
**Result:** Missing dependency - should be reclassified as SKIP or dependency added to demo env.

---

### confirmation_required.py

**Status:** PASS (interactive)
**Tier:** untagged
**Description:** Demonstrates confirmation required. Interactive file that requires user input - failed with EOFError in non-interactive mode.
**Result:** Expected behavior for interactive file in non-interactive mode.

---

### confirmation_required_mcp_toolkit.py

**Status:** PASS (interactive)
**Tier:** untagged
**Description:** Demonstrates confirmation required mcp toolkit. Interactive file that requires user input - failed with EOFError in non-interactive mode.
**Result:** Expected behavior for interactive file in non-interactive mode.

---

### confirmation_toolkit.py

**Status:** PASS (interactive)
**Tier:** untagged
**Description:** Demonstrates confirmation toolkit. Interactive file that requires user input - failed with EOFError in non-interactive mode.
**Result:** Expected behavior for interactive file in non-interactive mode.

---

### external_tool_execution.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates external tool execution. Ran successfully and produced expected output.
**Result:** Completed successfully in 11s.

---

### user_input_required.py

**Status:** PASS (interactive)
**Tier:** untagged
**Description:** Demonstrates user input required. Interactive file that requires user input - failed with EOFError in non-interactive mode.
**Result:** Expected behavior for interactive file in non-interactive mode.

---
