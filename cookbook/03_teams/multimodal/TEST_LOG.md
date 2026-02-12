# Test Log: multimodal

> Updated: 2026-02-11

### audio_to_text.py

**Status:** PASS

**Description:** Team-based audio transcription using Gemini `gemini-3-flash-preview`. Downloads MP3 from S3, sends as `Audio(content=...)` to team with transcription specialist + content analyzer.

**Result:** Ran successfully. Full speaker-identified transcript produced (Speaker A / Speaker B). Conversation about family details transcribed accurately with proper turn-taking structure.

---

### audio_sentiment_analysis.py

**Status:** PASS

**Description:** Two-turn audio sentiment analysis with SQLite session persistence. Downloads WAV from S3, runs sentiment analysis, then asks follow-up question using conversation history (`add_history_to_context=True`).

**Result:** Ran successfully. First turn produced detailed sentiment analysis with speaker identification. Second turn leveraged session history to provide deeper psychological analysis (passive-aggressive dynamics, power dynamics, learned withdrawal patterns).

---

### generate_image_with_team.py

**Status:** PASS

**Description:** Collaborative image generation using GPT-4o team with DalleTools. Prompt Engineer enhances prompt, Image Creator generates via DALL-E. Uses `stream=True, stream_events=True` with `RunOutputEvent` iteration.

**Result:** Ran successfully (~40s). Prompt engineer enhanced "yellow siamese cat" prompt, image creator generated via DALL-E. Streaming events showed full team coordination flow with metrics (2230 input, 345 output tokens).

---

### image_to_structured_output.py

**Status:** PASS

**Description:** Visual analysis with structured output schema (`MovieScript` Pydantic model). Image Analyst + Script Writer team analyzes Wikimedia Golden Gate Bridge image and produces structured movie concept. Uses `output_schema=MovieScript`.

**Result:** Ran successfully. Produced valid MovieScript with name="Mist Over the Bay", 3 characters, San Francisco setting, and 3-sentence storyline. Streaming output showed token-by-token structured generation followed by parsed Pydantic object.

---

### image_to_text.py

**Status:** FAIL

**Description:** Local image analysis with creative writing. Uses `Image(filepath=Path(__file__).parent / "sample.jpg")` — requires a local sample image.

**Result:** Failed — `sample.jpg` not found in the multimodal directory. Framework logged `ERROR Failed to process image due to invalid input: Image file not found`. Team delegated to Image Analyst but no image data was available, so model asked for a description instead.

---

### media_input_for_tool.py

**Status:** PASS

**Description:** Custom `Toolkit` subclass (`DocumentProcessingTools`) that receives `File` objects directly. Uses Gemini `gemini-2.5-pro` with `store_media=True` and `send_media_to_model=False`. Team processes synthetic PDF content via tool rather than model vision.

**Result:** Ran successfully. Synthetic PDF bytes passed as `File(content=...)`, team used `extract_text_from_pdf` tool which received the file objects correctly. Extracted simulated quarterly revenue data and provided financial analysis noting the stated 20% growth rate was inconsistent (Q2→Q3 was ~16.7%).

---

### image_to_image_transformation.py

**Status:** SKIP

**Description:** Image-to-image transformation using FalTools. Requires `fal_client` package.

**Result:** Skipped — `fal_client` not installed in demo venv. Module-level import in `agno/tools/fal.py` raises ImportError.

---

### video_caption_generation.py

**Status:** SKIP

**Description:** Video caption generation pipeline using MoviePyVideoTools + OpenAITools. Requires `moviepy` package.

**Result:** Skipped — `moviepy` not installed in demo venv. Module-level import in `agno/tools/moviepy_video.py` raises ImportError.

---
