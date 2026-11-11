# Otari Tests

### basic.py

**Status:** PASS

**Description:** Basic Otari model cookbook covering sync, streaming, async, and async streaming agent responses with `openai:gpt-5.6-luna` against otari.ai.

**Result:** All four variants returned complete responses.

---

### tool_use.py

**Status:** PASS

**Description:** Agent with `WebSearchTools()` covering sync, streaming, async, and async streaming tool calls with `openai:gpt-5.6-luna` against otari.ai.

**Result:** All four variants called `web_search` and returned summaries. `reasoning_effort="none"` is required: with reasoning enabled, gpt-5.6-luna rejects function tools on `/v1/chat/completions` with a 400. Some searches logged "No results found" from the search backend; the agent retried and still answered.

---

### structured_output.py

**Status:** PASS

**Description:** Agent with `output_schema=MovieScript` prompted with "New York", using `openai:gpt-5.6-luna` against otari.ai.

**Result:** Returned a populated `MovieScript` instance.

---

### Unit tests

`libs/agno/tests/unit/models/test_otari.py`: 9 passed, without network access.
