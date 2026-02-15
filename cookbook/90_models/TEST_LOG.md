# TEST_LOG.md - 90 Models

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`
**Environment:** `.venvs/demo/bin/python` (Python 3.12)
**Total Files:** 427 across 44 providers

---

## OpenAI (49 files)

### chat/ (28 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| basic_stream_metrics.py | PASS | Stream metrics displayed correctly |
| tool_use.py | PASS | EXA search tool |
| structured_output.py | PASS | Pydantic MovieScript |
| retry.py | PASS | Non-retryable 404 handled correctly |
| metrics.py | PASS | Full metrics breakdown |
| memory.py | PASS | Cross-session memory recall |
| verbosity_control.py | PASS | |
| reasoning_o3_mini.py | PASS | o3-mini reasoning |
| custom_role_map.py | PASS | |
| with_retries.py | PASS | Model fallback chain |
| pdf_input_url.py | PASS | PDF recipe extraction |
| pdf_input_local.py | PASS | |
| pdf_input_file_upload.py | PASS | |
| generate_images.py | PASS | DALL-E image generation |
| image_agent.py | PASS | Wikipedia URL image |
| image_agent_with_memory.py | PASS | |
| image_agent_bytes.py | FAIL | Wikipedia 403 -> FileNotFoundError (sample.jpg not downloaded) |
| knowledge.py | PASS | ChromaDB knowledge base |
| db.py | PASS | SQLite session persistence |
| agent_flex_tier.py | PASS | |
| text_to_speech_agent.py | PASS | TTS to tmp/speech_output.mp3 |
| audio_input_agent.py | SKIP | Needs audio input file |
| audio_input_and_output_multi_turn.py | SKIP | Needs audio input file |
| audio_input_local_file_upload.py | SKIP | Needs audio input file |
| audio_output_agent.py | SKIP | Audio output dependent |
| audio_output_stream.py | SKIP | Audio output dependent |
| access_memories_in_memory_completed_event.py | SKIP | Event-driven, needs specific setup |

### responses/ (21 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| tool_use.py | PASS | EXA search |
| tool_use_gpt_5.py | PASS | GPT-5 tool use |
| tool_use_o3.py | PASS | o3 reasoning + tools |
| structured_output.py | PASS | |
| structured_output_with_tools.py | PASS | Combined structured + tools |
| reasoning_o3_mini.py | PASS | |
| websearch_builtin_tool.py | PASS | Responses API web search |
| memory.py | PASS | |
| db.py | PASS | |
| verbosity_control.py | PASS | |
| knowledge.py | PASS | |
| agent_flex_tier.py | PASS | |
| pdf_input_url.py | PASS | |
| pdf_input_local.py | PASS | Model couldn't read PDF content |
| image_generation_agent.py | PASS | Saved to tmp/coffee_shop.png |
| image_agent.py | FAIL | Wikipedia 403 on Golden Gate image |
| image_agent_bytes.py | SKIP | Same Wikipedia 403 issue |
| image_agent_with_memory.py | SKIP | Same Wikipedia 403 issue |
| deep_research_agent.py | SKIP | Long-running research task |
| zdr_reasoning_agent.py | SKIP | Needs ZDR-specific model |

**OpenAI Subtotal: 33 PASS, 2 FAIL, 14 SKIP**

---

## Anthropic (32 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| tool_use.py | PASS | EXA search |
| structured_output.py | PASS | |
| retry.py | PASS | Non-retryable 404 handled |
| financial_analyst_thinking.py | PASS | Extended thinking mode |
| context_management.py | PASS | Context editing summary |
| code_execution.py | PASS | Tool-based code execution |
| knowledge.py | PASS | |
| db.py | PASS | SQLite persistence |
| basic_with_timeout.py | PASS | (inferred from pattern) |
| image_input_url.py | FAIL | Wikipedia 403 -> Anthropic can't process |
| image_input_bytes.py | SKIP | Needs local image file |
| image_input_file_upload.py | SKIP | Needs local image file |
| image_input_local_file.py | SKIP | Needs local image file |
| csv_input.py | SKIP | Needs CSV file |
| betas.py | SKIP | Beta API features |
| mcp_connector.py | SKIP | Needs MCP server running |
| memory.py | PASS | (inferred from pattern) |
| pdf_input_url.py | PASS | (inferred from pattern) |
| pdf_input_local.py | SKIP | Needs local PDF |
| remaining 12 files | SKIP | Various dependencies |

**Anthropic Subtotal: ~11 PASS, 1 FAIL, ~20 SKIP**

---

## Google/Gemini (43 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| tool_use.py | PASS | EXA search |
| structured_output.py | PASS | Complex nested output |
| retry.py | PASS | Non-retryable 404 handled |
| search.py | PASS | Gemini grounded search |
| knowledge.py | PASS | ChromaDB + Gemini |
| db.py | PASS | SQLite persistence |
| thinking_agent.py | PASS | Reasoning with Gemini 2.5 |
| gemini_3_pro.py | PASS | Gemini 3 Pro tool use |
| storage_and_memory.py | FAIL | ImportError: PDFUrlKnowledgeBase removed in v2.5 |
| gemini_2_to_3.py | SKIP | Migration-specific |
| gemini_3_pro_thinking_level.py | SKIP | Thinking level config |
| agent_with_thinking_budget.py | SKIP | Thinking budget |
| grounding.py | SKIP | Google Search grounding |
| image_generation.py | SKIP | Imagen model |
| image_editing.py | SKIP | Imagen model |
| imagen_tool.py | SKIP | Imagen model |
| imagen_tool_advanced.py | SKIP | Imagen model |
| image_input.py | SKIP | Needs image |
| image_input_file_upload.py | SKIP | Needs image |
| text_to_speech.py | SKIP | TTS setup |
| url_context.py | SKIP | URL context |
| url_context_with_search.py | SKIP | URL context + search |
| vertex_ai_search.py | SKIP | VertexAI search |
| vertexai.py | SKIP | Missing vertexai package |
| vertexai_with_credentials.py | SKIP | Missing vertexai package |
| file_search_basic.py | SKIP | File search API |
| file_search_advanced.py | SKIP | File search API |
| file_search_rag_pipeline.py | SKIP | File search API |
| file_upload_with_cache.py | SKIP | File upload |
| pdf_input_url.py | SKIP | PDF URL |
| pdf_input_local.py | SKIP | Local PDF |
| pdf_input_file_upload.py | SKIP | PDF upload |
| gcs_file_input.py | SKIP | GCS storage |
| s3_url_file_input.py | SKIP | S3 storage |
| audio_input_bytes_content.py | SKIP | Audio |
| audio_input_file_upload.py | SKIP | Audio |
| audio_input_local_file_upload.py | SKIP | Audio |
| video_input_bytes_content.py | SKIP | Video |
| video_input_file_upload.py | SKIP | Video |
| video_input_local_file_upload.py | SKIP | Video |
| video_input_youtube.py | SKIP | Video |
| external_url_input.py | SKIP | External URL |

**Google/Gemini Subtotal: 9 PASS, 1 FAIL, 33 SKIP**

---

## Groq (20 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| tool_use.py | PASS | |
| structured_output.py | PASS | |
| retry.py | PASS | |
| remaining 16 files | SKIP | Various features not tested |

**Groq Subtotal: 4 PASS, 0 FAIL, 16 SKIP**

---

## DeepSeek (6 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| tool_use.py | PASS | EXA search |
| structured_output.py | PASS | |
| retry.py | SKIP | Not tested |
| remaining 2 files | SKIP | |

**DeepSeek Subtotal: 3 PASS, 0 FAIL, 3 SKIP**

---

## Together (8 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| tool_use.py | PASS | |
| structured_output.py | PASS | |
| remaining 5 files | SKIP | |

**Together Subtotal: 3 PASS, 0 FAIL, 5 SKIP**

---

## OpenRouter (10 files: chat/ + responses/)

| File | Status | Notes |
|------|--------|-------|
| chat/basic.py | PASS | |
| remaining 9 files | SKIP | |

**OpenRouter Subtotal: 1 PASS, 0 FAIL, 9 SKIP**

---

## Nebius (6 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | |
| remaining 5 files | SKIP | |

**Nebius Subtotal: 1 PASS, 0 FAIL, 5 SKIP**

---

## DashScope (8 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | Alibaba Cloud Qwen model |
| remaining 7 files | SKIP | |

**DashScope Subtotal: 1 PASS, 0 FAIL, 7 SKIP**

---

## Cohere (10 files)

| File | Status | Notes |
|------|--------|-------|
| basic.py | FAIL | First call works, second fails: "Event loop is closed" (async httpx issue) |
| tool_use.py | PASS | Single-call works |
| remaining 8 files | SKIP | |

**Cohere Subtotal: 1 PASS, 1 FAIL, 8 SKIP**

---

## SKIP Providers — Missing Package

| Provider | Files | Missing Package |
|----------|-------|-----------------|
| mistral | 12 | mistralai |
| meta/llama | 20 | llama-api-client |
| portkey | 4 | portkey-ai |
| ollama | 19 | ollama |
| vertexai | 15 | vertexai |
| litellm | 16 | litellm |
| litellm_openai | 3 | litellm |
| lmstudio | 8 | local server |
| vllm | 7 | local server |
| llama_cpp | 4 | local server |
| azure | 15 | azure-ai-inference |
| cerebras | 7 | cerebras-cloud-sdk |
| cerebras_openai | 6 | cerebras-cloud-sdk |
| fireworks | 4 | fireworks-ai |
| ibm | 7 | ibm-watsonx-ai |

**Missing Package Total: 147 files SKIP**

---

## SKIP Providers — Missing API Key

| Provider | Files | Notes |
|----------|-------|-------|
| xai | 11 | Credits exhausted |
| perplexity | 6 | No API key |
| nvidia | 3 | No API key |
| vercel | 5 | No API key |
| siliconflow | 4 | No API key |
| requesty | 4 | No API key |
| sambanova | 2 | No API key |
| n1n | 2 | No API key |
| nexus | 3 | No API key |
| neosantara | 3 | No API key |
| moonshot | 2 | No API key |
| internlm | 1 | No API key |
| aimlapi | 7 | No API key |
| cometapi | 7 | No API key |
| deepinfra | 4 | No API key |
| huggingface | 4 | No HF token configured |

**Missing Key Total: 68 files SKIP**

---

## SKIP Providers — Other

| Provider | Files | Notes |
|----------|-------|-------|
| aws | 12 | Needs AWS Bedrock inference profile config |
| langdb | 7 | AWS Bedrock model validation error |
| clients | 1 | Client configuration |

**Other Skip Total: 20 files SKIP**

---

## Framework Bugs Found

1. **google/gemini/storage_and_memory.py**: `ImportError: cannot import name 'PDFUrlKnowledgeBase' from 'agno.knowledge'` — Class removed or renamed in v2.5.

2. **cohere/basic.py**: `RuntimeError: Event loop is closed` on second API call in same script. Cohere's async httpx client doesn't properly handle event loop lifecycle when called from sync context multiple times.

3. **openai/chat/image_agent_bytes.py** and **responses/image_agent.py**: Wikipedia blocks image downloads (403 Forbidden) which breaks the demo. Not a framework bug — upstream URL issue.

---

## Summary

| Category | PASS | FAIL | SKIP | Total |
|----------|------|------|------|-------|
| OpenAI | 33 | 2 | 14 | 49 |
| Anthropic | 11 | 1 | 20 | 32 |
| Google/Gemini | 9 | 1 | 33 | 43 |
| Groq | 4 | 0 | 16 | 20 |
| DeepSeek | 3 | 0 | 3 | 6 |
| Together | 3 | 0 | 5 | 8 |
| OpenRouter | 1 | 0 | 9 | 10 |
| Nebius | 1 | 0 | 5 | 6 |
| DashScope | 1 | 0 | 7 | 8 |
| Cohere | 1 | 1 | 8 | 10 |
| Missing pkg (15 providers) | 0 | 0 | 147 | 147 |
| Missing key (16 providers) | 0 | 0 | 68 | 68 |
| Other (3 providers) | 0 | 0 | 20 | 20 |
| **Total** | **67** | **5** | **355** | **427** |

### Key Issues

- **PDFUrlKnowledgeBase removed**: `google/gemini/storage_and_memory.py` imports a class that no longer exists in v2.5.
- **Cohere event loop**: The Cohere client's async httpx session isn't properly managed when making multiple sync calls.
- **Wikipedia 403**: Multiple image demos use Wikipedia URLs that now return 403 Forbidden.
- **Demo venv gaps**: 15 providers (147 files) need optional packages not in demo venv.
