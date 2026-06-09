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
