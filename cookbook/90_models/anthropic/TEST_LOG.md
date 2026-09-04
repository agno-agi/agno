# TEST_LOG

### thinking.py

**Status:** PASS

**Description:** Extended thinking with sync and streaming responses. Model id bumped from the retired claude-3-7-sonnet-20250219 to claude-sonnet-4-5.

**Result:** Both runs return a thinking block followed by the response.

---

### adaptive_thinking.py

**Status:** PASS

**Description:** Adaptive thinking with output_config effort on claude-sonnet-4-6.

**Result:** Response streams with thinking and a full markdown answer.

---

### financial_analyst_thinking.py

**Status:** PASS

**Description:** Interleaved thinking with calculator and yfinance tools, streaming. Exercises replay of stored thinking blocks alongside tool_use blocks inside a single tool-use turn. Model id bumped from the retired claude-sonnet-4-20250514 to claude-sonnet-4-5.

**Result:** Thinking, tool calls and the final response complete. A transient TLS read error on one request was retried by the Anthropic SDK and did not affect the run.

---
