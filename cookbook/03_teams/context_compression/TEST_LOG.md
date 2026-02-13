# Test Log: context_compression

> Updated: 2026-02-12

### tool_call_compression.py

**Status:** PASS

**Description:** Demonstrates team-level tool result compression with `compress_tool_results=True` in both sync (AwsBedrock) and async (OpenAIChat) workflows. Uses WebSearchTools for live web queries.

**Result:** Both sync and async runs completed successfully. Sync used AwsBedrock Claude Sonnet 4, async used OpenAI GPT-5.2. Tool call results were compressed before being sent to the model.

---

### tool_call_compression_with_manager.py

**Status:** PASS

**Description:** Demonstrates custom tool result compression using `CompressionManager` with a custom prompt that extracts competitive intelligence bullet points. Uses `compress_tool_results_limit=2` to keep only last 2 tool call results uncompressed.

**Result:** Ran successfully with AwsBedrock Claude Sonnet 4 and custom compression via GPT-4o. Custom compression prompt was applied to tool results.

---
