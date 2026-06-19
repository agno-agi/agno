# Agno Gateway - Test Log

The `Agno` model class talks to the gateway over httpx using the OpenAI
chat-completions schema, with no provider SDK installed. Verified two auth modes:

- **Managed** (`AGNO_API_KEY`, no provider key) against the Cloudflare account
  endpoint with Unified Billing.
- **BYOK** (provider key by id prefix) against the staging gateway.

In both, `openai` / `anthropic` are confirmed NOT imported during a full agent run.

### basic.py

**Status:** PASS

**Description:** Sync, sync+streaming, async, and async+streaming runs with
`openai/gpt-5.4`, routed through the gateway (BYOK via staging for this run).

**Result:** All four modes returned a 2 sentence horror story. No errors. No provider
SDK loaded.

---

### tool_use.py

**Status:** PASS

**Description:** Function calling with custom Python tools (`get_weather`,
`get_activities`) on `openai/gpt-5.4` (BYOK via staging for this run).

**Result:** All four scenarios passed - single tool, parallel tool calls in one turn,
streaming with tools, and async with tools. The streamed tool-call fragments
reassembled correctly. No provider SDK loaded.

**Notes:**
- Managed mode separately verified end to end: a CF-account token (no provider key)
  through the unified `/ai/v1/chat/completions` endpoint returned the normalized
  OpenAI shape and the agent run succeeded.
- Endpoint choice: the class uses `/ai/v1/chat/completions`, which normalizes every
  provider to the OpenAI shape (one parser). The `/ai/run` universal endpoint was
  evaluated and rejected: it returns provider-native shapes (Workers AI vs OpenAI vs
  Anthropic differ), which would require per-provider parsing on the client. Both
  endpoints share the same CF-account managed billing.

---

### mcp_tools.py

**Status:** PASS

**Description:** Agent on `openai/gpt-5.4` (BYOK via staging) connected to a local MCP
server (`http://localhost:8787/mcp`, Streamable HTTP) exposing a `web_search` tool.

**Result:** The gateway model issued a `web_search` tool call, the MCP server returned
live DuckDuckGo results, and the agent summarized them. MCP tools work unchanged through
the gateway (they are forwarded as standard OpenAI tools/tool_calls).

**Notes:**
- The cookbook file is named `mcp_tools.py`, not `mcp.py`, on purpose: a module named
  `mcp.py` shadows the `mcp` package and breaks the import.

---

### structured_output.py

**Status:** PASS

**Description:** `output_schema=MovieScript` on `openai/gpt-5.4` (BYOK via staging),
covering native structured outputs, JSON mode (`use_json_mode=True`), and async.

**Result:** All three returned valid JSON matching the schema. The native path now
exercises the `response_format` json_schema branch (see note below).

**Notes:**
- This required a model fix: `Agno` did not set `supports_native_structured_outputs`,
  so it inherited `False` and `output_schema` silently degraded to JSON-object mode -
  the json_schema branch in `agno.py` was dead code. Set the flag to `True` (matching
  OpenAIChat) so the gateway forwards a strict `response_format` json_schema.

---

### metrics.py

**Status:** PASS

**Description:** Per-message and aggregated metrics on `openai/gpt-5.4` (BYOK via
staging).

**Result:** Token counts (input/output/total) populated correctly. `cost` is `None`
under BYOK on staging - cost is only surfaced when the gateway bills it (managed mode);
BYOK is billed by the provider, so the gateway returns no cost field. Code handles both.

---

### image_input.py

**Status:** PASS

**Description:** Image URL input on `openai/gpt-5.4` (BYOK via staging).

**Result:** Correctly identified the Golden Gate Bridge from the image URL.

---

### pdf_input.py

**Status:** PASS

**Description:** PDF URL input (`File(url=...)`) on `openai/gpt-5.4` (BYOK via staging).

**Result:** Read the attached ThaiRecipes.pdf and returned a recipe from it.

---

### reasoning_effort.py

**Status:** PASS

**Description:** `reasoning_effort="high"` on `openai/gpt-5.4` (BYOK via staging).

**Result:** Solved the train word problem correctly (7:00 PM) with step-by-step
reasoning.

---

### db.py

**Status:** PASS

**Description:** `PostgresDb` + `add_history_to_context` on `openai/gpt-5.4` (BYOK via
staging), against the local pgvector container.

**Result:** History carried across turns - the second turn ("their national anthem")
correctly resolved to Canada. Agent-level persistence is model-agnostic and works
unchanged through the gateway.

---

### memory.py

**Status:** PASS

**Description:** `update_memory_on_run` + `enable_session_summaries` on `openai/gpt-5.4`
(BYOK via staging), against the local pgvector container.

**Result:** Extracted and recalled user memories (name "John Billings", city "NYC").
Session summary updated.

---

### knowledge.py

**Status:** PASS

**Description:** `Knowledge` + `PgVector` RAG on `openai/gpt-5.4` (BYOK via staging),
against the local pgvector container.

**Result:** Retrieved from the ThaiRecipes.pdf vector store and grounded the answer in
the retrieved content.

---

### audio_input.py / audio_output.py

**Status:** UNVERIFIED (blocked by test-credential access)

**Description:** Audio in/out on `openai/gpt-4o-audio-preview` via `request_params`
(`modalities`, `audio`).

**Result:** Could not run end to end - the BYOK OpenAI key has no access to
`gpt-4o-audio-preview` ("the model does not exist or you do not have access to it").
Notably, the error is OpenAI's own, forwarded back through the gateway, which confirms
the gateway routed the request correctly; only the audio model access is missing. The
cookbooks exercise the same audio code path the `Agno` class already implements
(`_format_message` audio handling, `_parse_provider_response` audio decode). Re-run with
an audio-enabled key or managed `AGNO_API_KEY` to confirm.

---
