# TEST_LOG

Run against the live Router API on 2026-08-19 with `.venvs/demo/bin/python`.

### basic.py

**Status:** PASS

**Description:** Sync, sync streaming, async and async streaming runs on `gpt-5.6-luna`, half of
them through the `RampRouter(...)` constructor and half through the `"ramp:gpt-5.6-luna"` model
string.

**Result:** All four runs returned a two sentence horror story. The model string resolved to
`RampRouter` through the provider registry.

---

### tool_use.py

**Status:** PASS

**Description:** Four runs with `WebSearchTools()` on `gpt-5.6-luna`, covering sync, sync
streaming, async and async streaming.

**Result:** All four called `search_news` and answered from the results. Two of the four runs
logged `No results found.` from the search tool before retrying with a different query; no model
errors.

An earlier revision failed all four with `Item 'fc_...' of type 'function_call' was provided
without its required 'reasoning' item: 'rs_...'`. Reasoning models bind the call to the reasoning
item that preceded it by item id, and Agno does not carry that item across turns, so `RampRouter`
now replays function calls without their `id`. `call_id`, which pairs the call with its output,
is untouched.

---

### structured_output.py

**Status:** PASS

**Description:** `output_schema=MovieScript` on `gpt-5.6-luna`, through the native structured
output path.

**Result:** Returned a fully populated `MovieScript`. The same schema also round-tripped on
`claude-haiku-4-5`, so structured output is not specific to the OpenAI backing.

---

### fallback.py

**Status:** PASS

**Description:** `models=[...]` across three candidates instead of a single `id`, with
`provider_timeout` and `metadata` set.

**Result:** Streamed a haiku. Router selected a candidate and served it; `model` was omitted from
the request body, which is what `models` requires.

---
