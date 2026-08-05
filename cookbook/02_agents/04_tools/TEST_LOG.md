# Test Log -- 04_tools

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### 01_callable_tools.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 01 callable tools. Ran successfully and produced expected output.
**Result:** Completed successfully in 17s.

---

### 02_session_state_tools.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 02 session state tools. Ran successfully and produced expected output.
**Result:** Completed successfully in 7s.

---

### 03_team_callable_members.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates 03 team callable members. Ran successfully and produced expected output.
**Result:** Completed successfully in 87s.

---

### 04_tools_with_literal_type_param.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates using typing.Literal for tool parameters with predefined values. Tests both Toolkit methods and standalone functions with Literal type hints.
**Result:** JSON schema correctly generates enum constraints for Literal types.

---

### tool_call_limit.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates tool call limit. Ran successfully and produced expected output.
**Result:** Completed successfully in 13s.

---

### per_tool_call_limit.py

**Status:** PASS
**Tier:** untagged
**Tested:** 2026-07-14
**Environment:** .venvs/demo/bin/python, Ollama qwen3:14b
**Description:** Validated the per-tool call limit with an equivalent end-to-end Ollama flow. The first limited tool call executed, the second was blocked by `max_calls=1`, and an unrelated tool executed afterward.
**Result:** The live run completed successfully with one limited-tool success, one limit error, and one unrelated-tool success. The committed OpenAI cookbook also passed static validation.

---

### tool_choice.py

**Status:** TIMEOUT
**Tier:** untagged
**Description:** Demonstrates tool choice. Timed out after 120s - likely making many API calls or stuck.
**Result:** Timed out after 120s.

---
