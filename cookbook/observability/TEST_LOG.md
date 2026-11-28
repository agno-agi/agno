### check_cookbook_pattern.py

**Status:** PASS

**Description:** Ran `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/observability --recursive` to validate module docstrings, section banners, create/run section order, main gates, and emoji rules.

**Result:** Validation passed with zero violations. Runtime execution of individual cookbook scripts was not performed in this pass.

---
### confident_ai.py

**Status:** PASS

**Description:** Sends Agno agent traces to Confident AI through `confident-trace`. Calls `init()` once at startup, runs a HackerNews agent twice (one plain run, one inside `trace_context` with tags, metadata, and a user ID), and calls `shutdown()` in a `finally` block to flush spans. Verified with `ruff format`, `ruff check`, `cookbook/scripts/check_cookbook_pattern.py`, and a module import against `confident-trace==0.1.3` in `.venvs/demo`.

**Result:** Static checks and import pass. Ran end to end with `CONFIDENT_API_KEY` and `OPENAI_API_KEY` set: both agent runs completed, tool and model calls executed, and span batches were accepted by the Confident AI collector with HTTP 200. Note that `CONFIDENT_OTEL_ENDPOINT` must match the project's region; a US project key against the EU endpoint returns 401 on export.

---
### agnost_ai_via_openinference.py

**Status:** PASS

**Description:** Instruments an Agno support agent with OpenInference and exports spans to Agnost AI over OTLP/HTTP (`https://otel.agnost.ai`, `X-Agnost-Org-ID` header). Runs two turns inside `using_attributes(session_id=..., user_id=...)` with in-memory history, so the follow-up question is answered from the first turn and Agnost AI groups both turns into one conversation. Ran end to end with `AGNOST_ORG_ID` and `OPENAI_API_KEY` set, and checked with `ruff format`, `ruff check`, and `cookbook/scripts/check_cookbook_pattern.py`.

**Result:** Both turns completed and the tool call executed. Agnost AI recorded one conversation for `user-42` containing the agent runs (`Support_Agent.run`), model calls (`OpenAIResponses.invoke`), and tool calls (`get_order_status`) as separate events, all successful.

---
