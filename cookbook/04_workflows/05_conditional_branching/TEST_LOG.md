# TEST_LOG for cookbook/04_workflows/05_conditional_branching

Generated: 2026-02-11

### string_selector.py

**Status:** PASS

**Description:** Router with string-based selector returning step names. Sync-stream only.

**Result:** Completed in 27.0s.

---

### step_choices_parameter.py

**Status:** PASS

**Description:** Router with `step_choices` parameter for dynamic step selection. Sync-stream only.

**Result:** Completed in 7.1s.

---

### nested_choices.py

**Status:** PASS

**Description:** Router with nested list choices `[step_a, [step_b, step_c]]`. Sync-stream only.

**Result:** Completed in 5.5s.

---

### loop_in_choices.py

**Status:** PASS

**Description:** Router where one choice is a Loop with max_iterations=2. Uses `step_choices` param. Sync-stream only.

**Result:** Completed in 58.2s.

---

### selector_types.py

**Status:** PASS

**Description:** Comprehensive demo of 3 router selector patterns (string, step_choices, nested choices). 3 sync-stream examples.

**Result:** Completed in 4.5s (all 3 examples).

---

### router_basic.py

**Status:** PASS (partial)

**Description:** Topic-based Router with callable selector. Tests all 4 variants (sync, sync-stream, async, async-stream). Uses HackerNewsTools and WebSearchTools.

**Result:**
- Sync: PASS (33.4s)
- Sync streaming: PASS (31.6s)
- Async: PASS (22.7s)
- Async streaming: TIMEOUT (120s total limit reached after 87.7s for first 3 variants)

---

### router_with_loop.py

**Status:** PASS

**Description:** Router selecting between web research and iterative Loop-based deep tech research with `end_condition`. Tests sync and async non-streaming.

**Result:**
- Sync: PASS (37.5s)
- Async: PASS (31.8s)

---

### selector_media_pipeline.py

**Status:** PASS (partial)

**Description:** Routes between image and video generation pipelines. Uses `OpenAITools(image_model="gpt-image-1")` and `GeminiTools(vertexai=True)`. Tests sync + async non-streaming.

**Result:**
- Sync: PASS (48.3s, with image processing error logged but workflow completed)
- Async: FAIL (UTF-8 decode error processing raw PNG image bytes — timed out or hung)

**Notes:**
- `ERROR: Failed to process image content: 'utf-8' codec can't decode byte 0x89 in position 0` — [A] FRAMEWORK issue: image content pipeline doesn't handle binary image data properly in async path
- This is an expensive cookbook (image generation API calls)

---
