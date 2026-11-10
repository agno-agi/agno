# TEST_LOG

All examples run against the live Inception OpenAI-compatible endpoint
(`https://api.inceptionlabs.ai/v1`) with `INCEPTION_API_KEY` set, on
2026-05-29. Default model id is `mercury-2` (the `mercury` model is
restricted to accounts created before 2026-02-24).

### basic.py

**Status:** PASS

**Description:** Sync, sync+streaming, async, and async+streaming runs of
`mercury-2` via `print_response` / `aprint_response`.

**Result:** All four modes returned answers with no API errors. Streaming
emits chunks incrementally; async paths complete normally.

---

### tool_use.py

**Status:** PASS

**Description:** Agent calling `WebSearchTools` (web search), with streaming.

**Result:** Model issued the search tool call, consumed the results, and
streamed a final answer. Multi-turn tool flow round-tripped cleanly.

---

### structured_output.py

**Status:** PASS

**Description:** Two agents against `MovieScript` (six fields incl. a list):
a JSON-mode agent (`use_json_mode=True`) and a native structured-output agent
(`output_schema` without JSON mode).

**Result:** Both agents returned a valid `MovieScript` instance with all
fields populated. The JSON-mode agent worked as expected; the native
structured-output path also returned clean JSON that parsed into
`MovieScript`, so both routes yield JSON-shaped output on `mercury-2`.

---
