# TEST_LOG

Tests were run against the Cloudflare AI Gateway OpenAI-compatible `/compat`
endpoint with `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID`. Several Workers AI
models were tried per example; the cookbooks ship with the best
price-to-performance choice for each task.

### basic.py

**Status:** PASS

**Description:** Runs the default Workers AI chat model (`@cf/meta/llama-3.3-70b-instruct-fp8-fast`) through sync, sync+streaming, async, and async+streaming.

**Result:** All four invocation modes return a 2-sentence horror story. No errors.

---

### switch_model.py

**Status:** PASS

**Description:** Demonstrates the `@cf/...` catalog-binding normalization, the `Cloudflare(id=...)` constructor form, the `"cloudflare:..."` model-string shorthand, and a second Workers AI model.

**Result:** Both the default model and the alternate (`@cf/google/gemma-4-26b-a4b-it`) respond. The string-shorthand path normalizes correctly to `workers-ai/@cf/...`.

---

### tool_use.py

**Status:** PASS

**Description:** Web search via `WebSearchTools`. Tested several function-calling-capable Workers AI models.

**Result:** Settled on `@cf/zai-org/glm-4.7-flash` — clean tool-call cycle and a usable answer. Some other function-calling models (notably the larger MoE variants) either looped on the tool call or returned an empty assistant turn after the tool result; GLM 4.7 Flash hit the right cost/reliability balance.

---

### structured_output.py

**Status:** PASS

**Description:** Pydantic-shaped output (`MovieScript`, six fields including a list) via `use_json_mode=True` and via native structured outputs (no json mode).

**Result:** Settled on `@cf/google/gemma-4-26b-a4b-it` — reliable in **both** modes (json mode and native structured outputs). Workers AI does not enforce strict `response_format`/`json_schema` server-side, so model capability matters more than the flag. Other function-calling-capable models behaved unevenly: `granite-4.0-h-micro` worked in json mode but not native; `gpt-oss-20b` worked native but not json; `gpt-oss-120b`, `llama-4-scout-17b-16e-instruct`, and `llama-3.3-70b-instruct-fp8-fast` failed both. Gemma 4 was the price-to-performance winner that handled both code paths cleanly.

---
