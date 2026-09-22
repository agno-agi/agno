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
