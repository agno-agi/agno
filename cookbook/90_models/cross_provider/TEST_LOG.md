# Cross-Provider Cookbooks - Test Log

## Test Environment

- Python: 3.12
- Agno: development (worktree: fix-cross-provider-tool-messages)
- Date: 2026-02-24

---

### gemini_to_openai_tool_use.py

**Status:** PASS

**Description:** Two-provider switch: Gemini tool calls consumed by OpenAI.

**Result:** All 3 turns completed. Gemini made parallel tool calls (multiply + add), OpenAI correctly consumed the split tool messages and divided the result by 3, Gemini summarized all calculations. Combined tool message format correctly normalized for OpenAI Chat API.

---

### gemini_to_openai_responses.py

**Status:** FAIL (known limitation)

**Description:** Two-provider switch using OpenAI Responses API format.

**Result:** Turn 1 (Gemini) succeeded with parallel stock price fetches. Turn 2 (OpenAI Responses API) failed with: "Invalid 'input[2].id': Expected an ID that begins with 'fc'." This is a pre-existing limitation: OpenAI Responses API requires tool_call_ids starting with "fc" prefix, but Gemini generates UUID-format IDs. Requires ID mapping/rewriting (separate feature).

---

### three_provider_tool_cycle.py

**Status:** PASS

**Description:** Gemini -> OpenAI -> Claude -> Gemini calculator cycle.

**Result:** All 4 turns completed. Gemini calculated 42*17+100=814, OpenAI divided by 7 (116.29), Claude computed square root (10.78), Gemini summarized all steps correctly. Tool call history preserved across all provider switches.

---

### cross_provider_multi_tool.py

**Status:** PASS

**Description:** Parallel multi-tool calls (Calculator + YFinance) across providers.

**Result:** All 3 turns completed. Gemini made parallel tool calls for AAPL and MSFT stock prices. Claude consumed the combined tool message, calculated AAPL/MSFT ratio (0.70). OpenAI summarized all findings. Gemini's combined tool message format correctly split and consumed by Claude.

---

### cross_provider_knowledge.py

**Status:** PASS (partial)

**Description:** Knowledge/RAG queries across Gemini, OpenAI, and Claude.

**Result:** Knowledge base loaded (3 docs into LanceDB). Turn 1 (Gemini) hit 429 rate limit but tool call was correct. Turns 2 (OpenAI) and 3 (Claude) both searched knowledge and returned accurate answers. Cross-provider knowledge search works correctly.

---

### cross_provider_reasoning.py

**Status:** PASS

**Description:** Claude thinking -> OpenAI -> Gemini reasoning chain.

**Result:** All 3 turns completed. Claude with extended thinking solved the discount/tax problem (showing thinking steps), OpenAI continued with a follow-up calculation using the same session, Gemini summarized all calculations. Claude's reasoning_content did not break OpenAI or Gemini formatters.

---

## Single-Provider Regression Tests

### anthropic/tool_use.py

**Status:** PASS

**Description:** Claude with WebSearchTools (single-provider regression).

**Result:** Tool calls work correctly with the updated Claude formatter. No regression.

---

### google/gemini/tool_use.py

**Status:** PASS

**Description:** Gemini with WebSearchTools (single-provider regression).

**Result:** Tool calls work correctly with the updated Gemini formatter. No regression.

---
