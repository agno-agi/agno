# Copilot Model Provider - Test Log

### basic.py

**Status:** PASS

**Description:** Tests all 4 agent invocation modes: sync, sync+streaming, async, async+streaming. Model returns coherent 2-sentence horror stories in each mode.

**Result:** All 4 modes returned valid responses (1.4s - 5.4s per call). Token auto-refresh worked correctly.

---

### structured_output.py

**Status:** PASS

**Description:** Tests structured output with a Pydantic MovieScript schema. Agent produces a valid JSON response matching the schema fields (setting, ending, genre, name, characters, storyline).

**Result:** Returned a valid MovieScript JSON with all fields populated (8.9s).

---

### tool_use.py

**Status:** PASS

**Description:** Tests tool calling with WebSearchTools. Agent correctly invokes `search_news` tool and synthesizes results into a markdown response.

**Result:** Agent called `search_news(query="latest news France")`, received results, and produced a formatted summary (14.1s). All 3 modes (sync, sync+stream, async+stream) worked.

---
