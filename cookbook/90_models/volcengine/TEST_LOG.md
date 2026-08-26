# TEST_LOG

All examples tested against the Volcengine Ark API (`doubao-seed-2-1-pro-260628`) on 2026-08-26.

### basic.py

**Status:** PASS

**Description:** Minimal Ark agent run sync, sync + streaming, async, and async + streaming.

**Result:** All four variants returned responses as expected.

---

### string_model.py

**Status:** PASS

**Description:** Agent created via the `model="volcengine:doubao-seed-2-1-pro-260628"` string shorthand.

**Result:** String syntax resolved to an `Ark` instance and streamed a response.

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

**Description:** `output_schema` with native `json_schema` to return a typed `MovieScript`.

**Result:** Returned a valid Pydantic object matching the schema.

---

### tool_use.py

**Status:** PASS

**Description:** Web search tool called with thinking mode on (exercises the `reasoning_content` history round-trip across a tool call).

**Result:** Tool invoked, result folded into the answer, no API errors on the multi-turn history.

---
