# TEST_LOG

### stored_responses_without_chaining.py

**Status:** PASS

**Description:** Executed with `.venvs/demo/bin/python` using the real Agent and
OpenAI SDK with a mocked HTTP transport. The example performs a regular first
turn and a streaming follow-up in the same in-memory session.

**Result:** Both requests sent `store=True` and omitted `previous_response_id`.
The follow-up included the current instructions and the previous user/assistant
exchange. Live provider execution was not run because `OPENAI_API_KEY` was not
configured. Separate unit tests cover sync/async request construction and
encrypted reasoning plus tool-call replay.

---

### reasoning_effort.py

**Status:** PASS

**Description:** Runs `OpenAIResponses(id="gpt-5.5", reasoning_effort="xhigh", reasoning_summary="auto")` against the live API and asks the three-switches riddle.

**Result:** The API accepted `xhigh`, the run streamed a thinking summary for 4.0s and answered the riddle correctly.

---

### agent_flex_tier.py

**Status:** PASS

**Description:** Moved off `o4-mini`, which OpenAI shut down on 2026-10-23 (404), to `gpt-5.6-terra`. Runs `OpenAIResponses(id="gpt-5.6-terra", service_tier="flex")` against the live API.

**Result:** The flex tier request is accepted and the two-sentence story prints.

---

### zdr_reasoning_agent.py

**Status:** PASS

**Description:** Moved off `o4-mini` to `gpt-5.6-terra`. Runs three turns with `store=False`, `reasoning_summary="auto"` and history from `InMemoryDb`.

**Result:** All three turns answer and the follow-ups resolve "that country" from history.

---

### deep_research_agent.py

**Status:** PASS

**Description:** `o4-mini-deep-research` was shut down on 2026-07-23; OpenAI lists `gpt-5.6-sol` as the replacement. The deep-research id was what added `web_search_preview`, so the example now passes that tool itself.

**Result:** The semaglutide report streams with web-sourced figures. Real OpenAI calls, no mocks.

---

### reasoning_o3_mini.py

**Status:** PASS

**Description:** Moved the reasoning model off `o3-mini`, which OpenAI shut down on 2026-10-23 (404), to its listed replacement `gpt-5.6-sol`.

**Result:** The agent calls `get_current_stock_price` and prints the NVDA report.

---
