# TEST_LOG

### basic.py

**Status:** PASS

**Description:** Agent using `Tzafon(id="tzafon.sm-1")` answering a simple prompt ("Share a 2 sentence horror story") across sync, sync + streaming, async, and async + streaming.

**Result:** All four variants run and return completions against `https://api.tzafon.ai/v1`. `tzafon.sm-1` is the small general-purpose chat model (see Lightcone pricing) and a sensible default.

---

### tool_use.py

**Status:** PASS

**Description:** Agent using `Tzafon(id="tzafon.northstar-cua-fast")` with `WebSearchTools()` (DuckDuckGo) answering "Whats happening in France?".

**Result:** Runs and invokes the web search tool.

**Note:** `northstar-cua-fast` is a computer-use model priced ~5x higher on output than `tzafon.sm-1`. Tool calling works over the OpenAI-compatible API, but using `tzafon.sm-1` here would be cheaper and consistent with the other examples.

---

### structured_output.py

**Status:** PASS

**Description:** Agent using `Tzafon(id="tzafon.sm-1")` with a `MovieScript` Pydantic `output_schema`, run in both JSON mode (`use_json_mode=True`) and native structured output (default).

**Result:** Both agents return valid structured JSON matching the schema.

---
