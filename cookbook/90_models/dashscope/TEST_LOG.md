# TEST_LOG

Tested 2026-10-19 on agno @ main (643f6e797) plus the `enable_search` change,
offline: the OpenAI client was given a mocked HTTP transport, so no request
reached DashScope. Only `web_search.py` was run.

### web_search.py

**Status:** PASS (offline, request payload only)

**Description:** Runs the sync, sync + streaming and async + streaming
variants and inspects the request body each one sends.

**Result:** All three requests carried `enable_search: true` and
`search_options: {"forced_search": true, "search_strategy": "turbo"}` next to
`enable_thinking: false`. Search results were not checked because the live
API was not called.

---
