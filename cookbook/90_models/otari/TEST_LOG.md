# Otari Tests

### basic.py

**Status:** SKIP

**Description:** Basic Otari model cookbook covering sync, streaming, async, and async streaming agent responses.

**Result:** Not run locally because `OTARI_API_KEY` is not available in this checkout.

---

### tool_use.py

**Status:** SKIP

**Description:** Agent with `WebSearchTools()` covering sync, streaming, async, and async streaming tool calls.

**Result:** Not run locally because `OTARI_API_KEY` is not available in this checkout.

---

### structured_output.py

**Status:** SKIP

**Description:** Agent with `output_schema=MovieScript` prompted with "New York".

**Result:** Not run locally because `OTARI_API_KEY` is not available in this checkout.

---

### Unit tests

`libs/agno/tests/unit/models/test_otari.py`: 8 passed, without network access.
