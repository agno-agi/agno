# TEST_LOG

All examples run against the live MiMo API (`mimo-v2.5-pro`) on 2026-05-29.

### basic.py

**Status:** PASS

**Description:** Minimal MiMo agent run sync, sync + streaming, async, and async + streaming.

**Result:** All four variants returned responses as expected.

---

### string_model.py

**Status:** PASS

**Description:** Agent created via the `model="xiaomi:mimo-v2.5-pro"` string shorthand.

**Result:** String syntax resolved to a `MiMo` instance and streamed a response.

---

### thinking_mode.py

**Status:** PASS

**Description:** `use_thinking=True` vs `use_thinking=False` on the same prompt.

**Result:** Thinking-on run returned `reasoning_content`; thinking-off run returned a direct answer.

---

### reasoning_agent.py

**Status:** PASS

**Description:** Logic puzzle solved with `use_thinking=True` and `show_full_reasoning=True`.

**Result:** Reasoning streamed alongside a correct step-by-step solution.

---

### structured_output.py

**Status:** PASS

**Description:** `output_schema` with `use_json_mode=True` to return a typed `MovieScript`.

**Result:** Returned a valid Pydantic object matching the schema.

---

### tool_use.py

**Status:** PASS

**Description:** Web search tool called with thinking mode on (exercises the `reasoning_content` history round-trip across a tool call).

**Result:** Tool invoked, result folded into the answer, no API errors on the multi-turn history.

---
