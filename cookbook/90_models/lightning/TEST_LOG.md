# Lightning Tests

### basic.py

**Status:** PASS

**Description:** Basic Lightning model cookbook covering sync, streaming, async, and async streaming agent responses with `openai/gpt-5-nano`.

**Result:** All four variants returned responses against the live Lightning API (2026-07-21).

---

### tool_use.py

**Status:** PASS

**Description:** Lightning model with WebSearchTools covering sync, streaming, and async streaming tool use.

**Result:** All three variants completed with tool calls and grounded answers. One `search_news` call raised a transient ddgs "No results found" tool error; the agent recovered by falling back to `web_search` in the same run.

---
