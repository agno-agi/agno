# TEST_LOG

Tested against the DeepSeek V4 API (`DEEPSEEK_API_KEY` set) on 2026-05-29.

### basic.py

**Status:** PASS

**Description:** Sync, sync+streaming, async, async+streaming runs with `deepseek-v4-flash`. Thinking mode is enabled by default; the model returns content plus `reasoning_content`.

**Result:** Responses returned correctly in all four modes.

---

### thinking_mode.py

**Status:** PASS

**Description:** Compares thinking-enabled (default) vs thinking-disabled (`extra_body={"thinking": {"type": "disabled"}}`) on `deepseek-v4-flash`. Confirms `reasoning_content` is present with thinking on and absent with it off.

**Result:** Both paths returned valid answers; reasoning_content behaved as expected.

---

### reasoning_effort.py

**Status:** PASS

**Description:** `deepseek-v4-pro` with `reasoning_effort="max"` on a river-crossing puzzle, streamed with full reasoning.

**Result:** Produced a correct step-by-step solution with streamed reasoning.

---

### structured_output.py

**Status:** PASS

**Description:** `deepseek-v4-flash` with a `MovieScript` schema, run two ways: `json_mode_agent` (`use_json_mode=True`) and `structured_output_agent` (`output_schema` only, no JSON mode).

**Result:** Both modes returned valid structured JSON. DeepSeek has no native/json_schema structured output, but the `output_schema`-only agent still works via agno's prompt-based JSON fallback, so both paths produce a valid MovieScript.

---

### Related test suites

- `libs/agno/tests/unit/reasoning/test_reasoning_checkers.py` and
  `libs/agno/tests/unit/models/deepseek/test_deepseek.py`: **79 passed** (no network).
- `libs/agno/tests/integration/models/deepseek/test_basic.py`: **9 passed**
  (streaming tests updated to be thinking-aware: in thinking mode the stream first
  delivers reasoning_content deltas before content deltas).

---

### Notes

- `tool_use.py`, `structured_output.py`, `reasoning_agent.py`, `thinking_tool_calls.py`
  require optional cookbook dependencies (ddgs/yfinance) and were id-refreshed to V4;
  run them via the demo venv with those installed.
