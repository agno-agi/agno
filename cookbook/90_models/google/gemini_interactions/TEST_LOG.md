# TEST_LOG - Gemini Interactions API Cookbooks

## Test Environment

- Python: 3.12
- SDK: google-genai (latest)
- Model: gemini-3-flash-preview
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

**Description:** Tests image generation using response_modalities=["text", "image"]. The Interactions API does not currently support image generation output with gemini-3-flash-preview.

**Result:** Model returned text instead of generating an image. Image generation is not yet supported through the Interactions API. The cookbook is kept as a reference for when support is added.

---
