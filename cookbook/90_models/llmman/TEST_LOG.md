# TEST_LOG

**Environment:** Windows 11, Python 3.12, `llmman serve qwen3:0.6b-q4_K_M` on `127.0.0.1:17434`.

### basic.py

**Status:** PASS

**Description:** Sync and streaming responses to "Share a 2 sentence horror story". Confirms the bare
model reference passed to `Llmman(id=...)` resolves against the running server.

**Result:** Both runs returned a completed response. The model emits a thinking block before the
answer, which renders as a separate panel. Sync 3.6s, streaming 1.5s.

---

### tool_use.py

**Status:** PASS

**Description:** Agent with `WebSearchTools()` answering "Whats happening in France?". Exercises tool
calling through llmman's OpenAI-compatible endpoint.

**Result:** The model selected `search_news(query=whats happening in France)` and summarised the
results into a numbered list. Tool calling works on a 0.6B model. Response 11.8s.

---

### structured_output.py

**Status:** PASS

**Description:** Agent with `output_schema=MovieScript` prompted with "New York". Exercises the
`supports_json_schema_outputs = True` path.

**Result:** Returned a fully populated `MovieScript` — every field set, `characters` a list of two
names, `storyline` three sentences. The json_schema flag is correct for this provider.

---

### Notes

On a cp1252 console, examples whose output contains non-cp1252 characters die with
`UnicodeEncodeError` in rich's legacy Windows renderer. Not a provider issue — set
`PYTHONIOENCODING=utf-8` when running the cookbook on Windows.

A `retry.py` example was dropped from this cookbook: it used a deliberately wrong model id to trigger
retries, but llmman treats an unknown id as a request to pull it and returns a normal 200 completion
whose content is the pull error, so no exception is raised and the retry path is never entered.

---

### Unit tests

`libs/agno/tests/unit/models/llmman_model/` — 2 passed.
