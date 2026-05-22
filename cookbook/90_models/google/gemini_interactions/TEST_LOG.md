# TEST_LOG - Gemini Interactions API Cookbooks

## Test Environment

- Python: 3.12
- SDK: google-genai (latest)
- Model: gemini-3.5-flash
- Date: 2026-05-14

---

### basic.py

**Status:** PASS

**Description:** Tests all four invocation modes: sync, sync+streaming, async, async+streaming. All modes returned coherent text responses.

**Result:** All four modes produced valid 2-sentence horror stories. Async mode showed expected aiohttp fallback warning.

---

### tool_use.py

**Status:** PASS

**Description:** Tests function calling with WebSearchTools. Agent correctly invokes the web search tool and returns a synthesized answer.

**Result:** Sync, streaming, and async streaming all produced detailed current events responses about France.

---

### multi_turn.py

**Status:** PASS

**Description:** Tests multi-turn conversation with server-side history via previous_interaction_id. Agent maintains context across turns.

**Result:** Agent correctly referenced prior conversation context (hiking interest) in follow-up responses.

---

### thinking.py

**Status:** PASS

**Description:** Tests thinking/reasoning mode with thinking_budget configuration.

**Result:** Model produced detailed mathematical reasoning about triangle angles with multiple proof approaches.

---

### search.py

**Status:** PASS

**Description:** Tests built-in Google Search tool (search=True). Agent uses Google Search grounding for real-time information.

**Result:** Returned current news with citations including geopolitics, tech, sports, and entertainment.

---

### image_understanding.py

**Status:** PASS

**Description:** Tests image understanding from URL. Image is downloaded via httpx and sent as base64 data.

**Result:** Model correctly identified and described a black Labrador puppy on wooden floorboards with detailed analysis of composition, lighting, and mood.

---

### audio_understanding.py

**Status:** PASS

**Description:** Tests audio understanding from URL. Audio file is downloaded and sent as base64 data.

**Result:** Model identified and described the audio clip contents correctly.

---

### video_understanding.py

**Status:** PASS

**Description:** Tests video understanding from URL. Video file is downloaded and sent as base64 data.

**Result:** Model described the video scene in detail including setting, background elements, people, and atmosphere.

---

### document_processing.py

**Status:** PASS

**Description:** Tests PDF document processing from URL (arxiv "Attention Is All You Need" paper).

**Result:** Model produced a comprehensive summary of the Transformer paper including key innovations, performance results, and significance.

---

### structured_output.py

**Status:** PASS

**Description:** Tests structured output with Pydantic schema (MovieReview). Uses output_schema parameter with response_format using TextResponseFormatParam.

**Result:** Returned a properly typed MovieReview object with title="The Matrix", year=1999, genre="Sci-Fi", rating=8.7, and a coherent summary.

---

### image_generation.py

**Status:** FAIL (API limitation)

**Description:** Tests image generation using response_modalities=["text", "image"]. The Interactions API does not currently support image generation output with gemini-3.5-flash.

**Result:** Model returned text instead of generating an image. Image generation is not yet supported through the Interactions API. The cookbook is kept as a reference for when support is added.

---

## Sanity sweep for PR #8045 (2026-05-21)

Branch `fix/gemini-interactions-agent-tool-calls` at commit ab12588c2. SDK
upgraded to google-genai 2.5.0 in `.venvs/demo` to satisfy the public
`google.genai.interactions` import path the PR uses.

### basic.py

**Status:** PASS

**Description:** All four invocation modes (sync, sync+stream, async, async+stream) against `gemini-3.5-flash`.

**Result:** All modes produced coherent 2-sentence horror stories. No errors.

---

### multi_turn.py

**Status:** PASS

**Description:** Three sequential turns sharing context via `previous_interaction_id` (SqliteDb persistence).

**Result:** Each turn correctly built on the previous one (e.g. the third-turn hike recommendation reflected the user profile established earlier). No 400s, no stale-state issues.

---

### tool_use.py

**Status:** PASS

**Description:** Client-declared `WebSearchTools` exercised across sync, sync+stream, async+stream. Regression check for the Codex P1 fix (FunctionCallStep with no matching FunctionResultStep should fall through to client dispatch).

**Result:** WebSearch tool was correctly dispatched locally in all three modes and produced a synthesized France news answer. No "Function not found" errors.

---

### structured_output.py

**Status:** PASS

**Description:** Pydantic `MovieReview` output_schema via the Interactions API's TextResponseFormatParam.

**Result:** Returned a fully populated MovieReview (title="The Matrix", year=1999, genre="Sci-Fi", rating=8.7) parsed correctly.

---

### thinking.py

**Status:** PASS

**Description:** `thinking_level="high"` reasoning across sync and async+stream.

**Result:** Both modes returned coherent geometry explanations. `reasoning_content` flowed through the parser (verified via the `<reasoning>` debug block).

---

### search.py

**Status:** PASS

**Description:** Built-in `search=True` tool across sync and async+stream.

**Result:** Both modes returned current-news answers grounded in Google search; no parser errors.

---

### antigravity.py

**Status:** PASS

**Description:** Basic non-streaming agent path call ("What is the capital of France?").

**Result:** Returned "Paris" in 11.1s. No errors. Sandbox provisioned and tool calls completed server-side without leaking to local dispatch.

---

### antigravity_streaming.py

**Status:** PASS

**Description:** Agent path with `stream=True` — the primary case the PR fixes. Asks the model to fetch Hacker News + summarize 5 stories AND run an async stream finding three trending Python repos.

**Result:** Both runs completed without errors. 26 `Server-side tool call:` / `Server-side reasoning:` log lines emitted across the run. Final markdown summaries rendered cleanly. No "Function list_files not found" or `400 invalid_request` from the original bug.

---

### antigravity_multi_turn.py

**Status:** PASS

**Description:** Three chained Antigravity turns through `SqliteDb` (plot solar growth → embed in HTML deck → revise deck).

**Result:** All three turns completed without errors. Second and third turns sent `previous_interaction_id` (confirmed via 2 occurrences in the debug log) and the sandbox state carried forward. Each turn's `ToolExecution` records (list_files, code_execution, browser ops, etc.) populated `run_response.tools`.

---
