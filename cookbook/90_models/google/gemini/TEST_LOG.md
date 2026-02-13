# TEST_LOG

## v2.5 Testing — 2026-02-11

### agent_with_thinking_budget.py
**Status:** PASS
**Description:** Gemini with thinking budget configuration. Demonstrates thinking token allocation.

---

### audio_input_bytes_content.py
**Status:** PASS
**Description:** Audio input as bytes content. Loads audio file and passes raw bytes to agent.

---

### audio_input_file_upload.py
**Status:** FAIL
**Description:** Audio file upload to Gemini Files API. Upload returns None content, causing pydantic validation error on `Audio(content=audio_file)`.
**Result:** `ValidationError: One of 'url', 'filepath', or 'content' must be provided`

---

### audio_input_local_file_upload.py
**Status:** PASS
**Description:** Audio input from local file upload. Successfully uploads and processes audio.

---

### basic.py
**Status:** PASS
**Description:** Basic Gemini agent with sync and async variants.

---

### db.py
**Status:** PASS
**Description:** Agent with PostgresDb for session history using Gemini.

---

### external_url_input.py
**Status:** PASS
**Description:** External URL as input to Gemini agent.

---

### file_search_advanced.py
**Status:** FAIL
**Description:** Advanced file search with multiple stores. Missing local document files.
**Result:** `FileNotFoundError: File not found: .../documents/technical_manual.txt`

---

### file_search_basic.py
**Status:** FAIL
**Description:** Basic file search store demo. Missing local document file.
**Result:** `FileNotFoundError: File not found: .../documents/sample.txt`

---

### file_search_rag_pipeline.py
**Status:** PASS
**Description:** File search RAG pipeline with Gemini. End-to-end retrieval-augmented generation.

---

### file_upload_with_cache.py
**Status:** PASS
**Description:** File upload with caching configuration for Gemini.

---

### gcs_file_input.py
**Status:** PASS
**Description:** Google Cloud Storage file input. Processes files from GCS URLs.

---

### gemini_2_to_3.py
**Status:** PASS
**Description:** Migration demo from Gemini 2 to Gemini 3 API patterns.

---

### gemini_3_pro.py
**Status:** PASS
**Description:** Gemini 3 Pro model basic usage.

---

### gemini_3_pro_thinking_level.py
**Status:** PASS
**Description:** Gemini 3 Pro with configurable thinking level.

---

### grounding.py
**Status:** PASS
**Description:** Grounding with Google Search. Demonstrates search-grounded responses.

---

### image_editing.py
**Status:** PASS
**Description:** Image editing capabilities with Gemini. Generates edited images.

---

### image_generation.py
**Status:** PASS
**Description:** Image generation with Gemini native image output.

---

### image_input.py
**Status:** PASS
**Description:** Image input from URL. Gemini analyzes provided image.

---

### image_input_file_upload.py
**Status:** FAIL
**Description:** Image upload using old `google.generativeai` SDK which is no longer installed. Should use `google.genai` instead.
**Result:** `ModuleNotFoundError: No module named 'google.generativeai'`

---

### imagen_tool.py
**Status:** FAIL
**Description:** Imagen tool for image generation. Two issues: (1) `imagen-3.0-generate-002` model returns 404 NOT_FOUND, (2) uses `agent.run_response` attribute which was removed in v2.5.
**Result:** `AttributeError: 'Agent' object has no attribute 'run_response'`

---

### imagen_tool_advanced.py
**Status:** FAIL
**Description:** Advanced Imagen tool with Vertex AI. Same `agent.run_response` AttributeError as `imagen_tool.py`. Also requires Vertex AI reauthentication.
**Result:** `AttributeError: 'Agent' object has no attribute 'run_response'`

---

### knowledge.py
**Status:** PASS
**Description:** Knowledge base with Gemini embedder and PgVector. PDF embedding pipeline.

---

### pdf_input_file_upload.py
**Status:** FAIL
**Description:** PDF upload to Gemini Files API. Missing local ThaiRecipes.pdf file.
**Result:** `FileNotFoundError: ThaiRecipes.pdf is not a valid file path.`

---

### pdf_input_local.py
**Status:** PASS
**Description:** PDF input from local file. Downloads PDF and passes via filepath.

---

### pdf_input_url.py
**Status:** PASS
**Description:** PDF input from URL. Summarizes Thai recipes PDF.

---

### retry.py
**Status:** PASS
**Description:** Retry behavior demo with wrong model ID. Shows retries with exponential backoff.

---

### s3_url_file_input.py
**Status:** PASS
**Description:** S3 URL file input. Processes files from S3 presigned URLs.

---

### search.py
**Status:** PASS
**Description:** Google Search integration with Gemini agent.

---

### storage_and_memory.py
**Status:** FAIL
**Description:** Storage and memory demo. Uses `PDFUrlKnowledgeBase` which was removed in v2.5.
**Result:** `ImportError: cannot import name 'PDFUrlKnowledgeBase' from 'agno.knowledge'`

---

### structured_output.py
**Status:** PASS
**Description:** Pydantic structured output with Gemini. Schema-enforced responses.

---

### text_to_speech.py
**Status:** PASS
**Description:** Text-to-speech with Gemini. Generates audio output.

---

### thinking_agent.py
**Status:** PASS
**Description:** Gemini agent with thinking/reasoning capabilities.

---

### tool_use.py
**Status:** PASS
**Description:** Tool use with Gemini. Web search and function calling.

---

### url_context.py
**Status:** PASS
**Description:** URL context tool for reading web pages with Gemini.

---

### url_context_with_search.py
**Status:** PASS
**Description:** URL context combined with search capabilities.

---

### vertex_ai_search.py
**Status:** PASS
**Description:** Vertex AI Search integration with Gemini.

---

### vertexai.py
**Status:** PASS
**Description:** Vertex AI backend for Gemini model access.

---

### vertexai_with_credentials.py
**Status:** PASS
**Description:** Vertex AI with explicit credentials configuration.

---

### video_input_bytes_content.py
**Status:** PASS
**Description:** Video input as bytes content. Loads video and passes raw bytes.

---

### video_input_file_upload.py
**Status:** FAIL
**Description:** Video file upload to Gemini Files API. Upload returns None content, causing pydantic validation error on `Video(content=video_file)`.
**Result:** `ValidationError: One of 'url', 'filepath', or 'content' must be provided`

---

### video_input_local_file_upload.py
**Status:** PASS
**Description:** Video input from local file upload. Successfully processes video.

---

### video_input_youtube.py
**Status:** PASS
**Description:** YouTube video input. Processes YouTube video URL.

---

## Summary
- **PASS:** 34/43 (79%)
- **FAIL:** 9/43 (21%)
- **Failures:**
  - audio_input_file_upload.py: File upload returns None content
  - file_search_advanced.py: Missing documents/technical_manual.txt
  - file_search_basic.py: Missing documents/sample.txt
  - image_input_file_upload.py: Uses old google.generativeai SDK
  - imagen_tool.py: agent.run_response removed + model 404
  - imagen_tool_advanced.py: agent.run_response removed + vertex auth
  - pdf_input_file_upload.py: Missing ThaiRecipes.pdf
  - storage_and_memory.py: PDFUrlKnowledgeBase removed in v2.5
  - video_input_file_upload.py: File upload returns None content
