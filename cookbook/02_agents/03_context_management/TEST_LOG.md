# TEST LOG

Generated: 2026-02-10 UTC

Pattern Check: Checked 4 file(s) in cookbook/02_agents/context_management. Violations: 0

### few_shot_learning.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### filter_tool_calls_from_history.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### instructions.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### instructions_with_state.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Completed successfully.

---

### introduction_message.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---

### system_message.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` as a cookbook runnable example.

**Result:** Structure check passed. Exits 0.

---


---

## v2.5 Audit Results

# TEST LOG

Generated: 2026-02-11 UTC (v2.5 review)

### instructions.py

**Status:** PASS

**Description:** Agent with `add_datetime_to_context=True` and `timezone_identifier="Etc/UTC"`. Correctly reported current UTC time (2026-02-11 20:01:26) and converted to NYC EST (15:01:26).

**Result:** Completed successfully.

---

### instructions_with_state.py

**Status:** PASS

**Description:** Callable `instructions` function with RunContext + session_state injection. State `{"game_genre": "platformer", "difficulty_level": "hard"}` correctly influenced response. Agent tailored advice for platformer/hard difficulty.

**Result:** Completed successfully.

---

### few_shot_learning.py

**Status:** PASS

**Description:** Agent with `additional_input=[Message(...)]` few-shot examples for customer support. Response to "enable 2FA" followed the established patterns (empathetic tone, numbered steps, actionable guidance).

**Result:** Completed successfully.

---

### filter_tool_calls_from_history.py

**Status:** PASS

**Description:** Agent with `max_tool_calls_from_history=3`, SqliteDb storage, and `add_history_to_context=True`. Ran 8 sequential weather queries. History tool calls filtered correctly — "In Context" stayed at 1 (only current run's tool call) while "In DB" grew to 8 (all stored).

**Result:** Completed successfully. Tool call filtering and storage separation working correctly.

---
