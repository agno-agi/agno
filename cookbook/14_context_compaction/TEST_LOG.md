# Test Log - Context Compaction

## Overview

Cookbook examples demonstrating context compaction for long-running conversations.

## Tests

### 01_quickstart.py

**Status:** PASS

**Description:** Basic multi-turn context compaction demo (5 turns: Python, JavaScript, TypeScript comparisons) with `compact_context_message_limit=6`, `keep_recent=2`.

**Result:** 3 compactions triggered, 2053 tokens saved net across 5 turns. Compaction fired automatically once the message limit was crossed (turns 3-5), and the conversation stayed coherent throughout (each summary built on the previous one).

---

### 02_custom_model.py

**Status:** PASS

**Description:** Verifies a cheaper model (gpt-4.1-mini) can be configured for compaction summaries while a stronger model (gpt-4.1) handles the main responses. Single-turn script with no session/db.

**Result:** Configuration printed correctly (main=gpt-4.1, compactor=gpt-4.1-mini, message_limit=6, keep_recent=2). No compaction occurred — expected, since this file only demonstrates configuration wiring (single turn, no persisted history) rather than triggering compaction. Minor content-quality note: the model answered about generic "data compression" (arithmetic coding, PAQ) rather than "context compaction for agents," since the prompt is ambiguous without a clarifying system message — not a functional bug.

---

### 03_with_tools.py

**Status:** PASS

**Description:** Tests compaction in a tool-heavy workflow using `DuckDuckGoTools` (now a thin wrapper around `WebSearchTools`/`ddgs`) across 3 research turns.

**Result:** 2 compactions triggered, 1065 tokens saved. `search_news` calls failed both times with `ddgs.exceptions.DDGSException: No results found` — an external DuckDuckGo news-backend issue, unrelated to agno. Agno's tool-error-relay handled this gracefully (error text returned to the model, which then answered from its own knowledge), and compaction itself worked correctly even with tool-error messages present in context.

---

### 04_with_session.py

**Status:** PASS

**Description:** Tests that compaction state persists via `SqliteDb` session storage, and that a user preference (favorite color) stated in turn 1 survives 3 compactions (`message_limit=4`).

**Result:** 3 compactions triggered; "favorite color: blue" correctly recalled in turn 4 despite compaction. Notable: compactions #1 and #2 showed **negative** tokens saved (-94, -6) — confirmed via source (`libs/agno/agno/compression/_context.py:206`, `tokens_saved = tokens_before - tokens_after`) that this happens when the LLM-generated summary is larger than the small early message set it replaces. Compaction #3 saved 165, netting a positive cumulative total (65 tokens saved overall). Not a bug — see cross-cutting observations below.

---

### 05_force_compaction.py

**Status:** PASS

**Description:** Forces frequent compaction via a low `message_limit=4` across 6 turns, testing whether user identity (name + profession) survives 5 rounds of compaction.

**Result:** 5 compactions triggered reliably (13 messages compacted total), 2118 tokens saved net. Final turn correctly recalled "Alice, software engineer specializing in distributed systems" after 5 compactions — strong evidence compaction preserves user identity through repeated summarization cycles.

---

### 06_preference_survival.py

**Status:** PASS

**Description:** Tests survival of 5 distinct stated preferences (name, pytest over unittest, structlog over print, dataclasses, type hints) through 3 rounds of aggressive compaction (`message_limit=4`).

**Result:** 5/5 preferences preserved (previous logged run scored 4/5 — this run scored perfectly, consistent with expected LLM response non-determinism). All checks passed: name "Marcus" remembered, pytest used, structlog used, dataclass used, type hints present in generated code.

---

### 07_comprehensive_test.py

**Status:** PASS

**Description:** Full test suite covering basic compaction, preference survival, multi-run persistence, and async compaction (4 sub-tests). Run with `timeout 180` as specified.

**Result:** 4/4 sub-tests passed, exit code 0. Same negative-tokens-saved pattern observed on early small compactions in sub-tests 2-4, consistent with 04/05/06 findings — confirms this is systematic behavior of the compaction algorithm, not incidental.

---

### 08_streaming_test.py

**Status:** PASS

**Description:** Tests that compaction works correctly with both sync (`agent.run(stream=True)`) and async (`agent.arun(stream=True)`) streaming, verifying user name/context recall via `get_last_run_output()`.

**Result:** 2/2 passed — sync and async streaming both preserved user name and work context correctly after compaction (1 compaction triggered in each). One intermittent, non-reproducible `RuntimeError: generator didn't stop after athrow()` traceback appeared from httpcore2's async connection pool during async-generator cleanup, right at the compaction trigger point in the async test; it did not affect the final response or test outcome, and did not reproduce on an isolated re-run of the identical scenario. Flagged as a flaky async-cleanup warning (Python 3.12 / httpcore2 interaction), not a compaction defect.

---

### 09_multi_model_test.py

**Status:** PASS

**Description:** Tests 4 agent/compactor model combinations: OpenAI/OpenAI (default), OpenAI agent + Claude compactor, Claude agent + GPT compactor, Gemini agent + OpenAI compactor. 3 turns each.

**Result:** 4/4 combinations passed — name ("MultiModelUser") and research-area context ("quantum computing") correctly preserved in all cases, no exceptions across providers. Two things worth flagging:
1. **Timeout**: An initial run with `timeout 180` and buffered stdout (piped to a file) reported exit code 124 (timeout) after only reaching test 3/4 — this was a false alarm caused by Python fully buffering stdout when not attached to a TTY, not a real hang (confirmed by testing Gemini in isolation, which responded in 0.7s). Re-running with `python -u` (unbuffered) and `timeout 300` completed cleanly with exit code 0. **Recommend `timeout 300` for this file**, not the standard 120s, since it sequentially exercises 3 providers x 4 configs x 3 turns.
2. **Model-dependent summary size**: Compaction summary length varies significantly by compactor model — Claude Sonnet 4.5 produced summaries in the 215-336 token range vs GPT-4.1-mini's typical 150-207 tokens for the same content, and in one run hit as high as 2035 tokens (against the `DEFAULT_COMPACTION_PROMPT`'s stated "maximum 2000 tokens" ceiling), producing the largest negative tokens-saved value observed across all 9 files (-1952 in that run). Verified via `libs/agno/agno/compression/_context.py:23-55` — the prompt gives a flat 2000-token ceiling with no dynamic/proportional sizing based on how much is actually being summarized. This is a real, model-dependent cost characteristic worth knowing about, not a bug.

---

## Cross-Cutting Observations

- **Compaction triggers correctly** in every file that exercises multiple turns (01, 03, 04, 05, 06, 07, 08, 09) — message-limit-based triggering fires reliably and message/token counts in the `[COMPACTION]` log line always reconcile with `response.compaction_state`.
- **User preferences and identity reliably survive compaction** across all preference-survival-focused tests (04, 05, 06, 07, 08, 09), including through 5 consecutive compactions (05) and across sync/async/streaming/multi-provider variants.
- **Streaming variants work** (08) for both sync and async, with one flaky (non-reproducible) async-generator cleanup warning that did not affect correctness.
- **Multi-model combinations work** (09) across OpenAI, Anthropic, and Google as both agent model and compactor model, in all 4 tested pairings.
- **Negative "tokens saved" on small/early compactions is expected, systematic behavior**, not a bug — confirmed at the source level (`_context.py:206`). It occurs when `old_messages` being replaced are smaller than the LLM-generated summary that replaces them. It appeared in 04, 06, 07, 08, and 09, and is most pronounced with more verbose compactor models (Claude > GPT-4.1-mini). Since `total_tokens_saved` accumulates per-compaction deltas across a session, early negative compactions are typically offset by later ones once there's more substantial content to compact — but the metric can mislead if read at a single point mid-conversation. Worth considering whether the default compaction prompt should scale its "maximum tokens" ceiling proportionally to the size of what's being compacted, rather than a flat 2000-token cap, to avoid this pattern on small/early compactions.
