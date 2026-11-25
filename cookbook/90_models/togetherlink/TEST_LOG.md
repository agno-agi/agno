# TogetherLink Cookbook Test Log

Tested against the live gateway at `https://gateway.togetherlink.dev/v1` with a Together API key.

---

### basic.py

**Status:** PASS

**Description:** Runs the default `auto` model (sync, non-streaming), then a pinned `zai-org/GLM-5.3-Flash` agent with sync streaming and async streaming.

**Result:** All three runs returned a two sentence story. Reasoning content from the gateway was surfaced in the Reasoning panel.

---

### tool_use.py

**Status:** PASS

**Description:** Agent with a local `get_weather` function tool, sync streaming and async streaming.

**Result:** The model called `get_weather` for Paris and Tokyo and answered from the tool result.

---

### structured_output.py

**Status:** PASS

**Description:** Agent with `output_schema=MovieScript` using `zai-org/GLM-5.3-Flash`.

**Result:** Returned a validated `MovieScript` with sensible values in every field. Before `TogetherLink` switched to JSON mode, the native `json_schema` path sometimes filled fields with unrelated text (for example an empty character name). Over 64 runs across 4 models and 2 schemas, JSON mode was correct 64/64 and native mode 54/64.

---

### Integration suite (libs/agno/tests/integration/models/togetherlink/)

**Status:** PASS (44/44)

**Description:** Covers every catalog model, sync/async and streaming runs, token metrics, reasoning content, multi-turn history with reasoning and tool-call replay, session isolation, unicode input, `max_tokens` pass-through, custom headers, invalid API key, unknown model, an unreachable gateway falling back to Together (sync and async stream), timeouts, 8 concurrent runs on one agent, serialization round-trip, single, multiple and parallel tool calls, tool exceptions, `tool_call_limit`, flat and nested structured output, JSON mode, streaming structured output, and tools plus `output_schema` through a `parser_model`.

**Result:** All pass. With tools and `output_schema` in one call, most gateway models answer straight in JSON without calling the tool. Direct Together behaves the same way. A `parser_model` fixed this in 22 of 24 runs.

---
