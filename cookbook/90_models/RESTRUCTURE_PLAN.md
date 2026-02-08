# Restructuring Plan: `cookbook/90_models/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Provider directories | 44 (some with subdirectories, 63 total dirs) |
| Total `.py` files (non-`__init__`) | 643 |
| `__init__.py` files (to remove) | 56 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~274 (~43%) |
| Have section banners | 1 (~0%) |
| Have `if __name__` gate | ~19 (~3%) |
| Contain emoji | ~11 files |
| Directories with README.md | ~31 / 63 |
| Directories with TEST_LOG.md | 0 / 63 |

### Key Problems

1. **Massive sync/stream/async redundancy.** Nearly every provider has 4 near-identical files for basic usage alone: `basic.py`, `basic_stream.py`, `async_basic.py`, `async_basic_stream.py`. The only differences are `stream=True` and `asyncio.run(agent.aprint_response(...))`. Same pattern repeats for `tool_use` (4 files) and sometimes `structured_output` (2-3 files). This accounts for ~195 redundant files.

2. **Zero style compliance.** Only 1 file has section banners, ~3% have main gates, ~43% have docstrings.

3. **56 unnecessary `__init__.py` files.** Cookbook directories should not have `__init__.py`.

4. **Emoji in 11 files.** Scattered across google/gemini, xai, anthropic, openai, vllm, clients.

5. **No TEST_LOG.md anywhere.** Zero directories have test logs.

6. **Missing READMEs.** ~13 provider directories and many subdirectories lack README.md.

### Overall Assessment

The largest cookbook section at 643 files. Well-organized by provider — each provider gets its own directory. The massive redundancy comes from a single pattern: every feature (basic, tool_use, structured_output) is split into 2-4 files for sync/stream/async/async+stream variants, when these should be a single file with all variants shown.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files (non-`__init__`) | 643 | ~450 |
| `__init__.py` files | 56 | 0 |
| Style compliance | 0% | 100% |
| README coverage | ~31/63 | All directories |
| TEST_LOG coverage | 0/63 | All directories |

---

## 2. Proposed Directory Structure

Keep all 44 provider directories and their subdirectories. The providers with sub-APIs (openai/chat vs openai/responses, ollama/chat vs ollama/responses, etc.) use genuinely different model classes and should remain separate.

Remove all `__init__.py` files — cookbook directories don't use them.

```
cookbook/90_models/
├── aimlapi/                   # AIMLAPI provider
├── anthropic/                 # Anthropic Claude
│   └── skills/                # Claude skills (documents, Excel, PowerPoint)
├── aws/                       # AWS model providers
│   ├── bedrock/               # AWS Bedrock
│   └── claude/                # Claude on AWS
├── azure/                     # Azure model providers
│   ├── ai_foundry/            # Azure AI Foundry
│   └── openai/                # Azure OpenAI
├── cerebras/                  # Cerebras
├── cerebras_openai/           # Cerebras (OpenAI-compatible)
├── clients/                   # HTTP client utilities
├── cohere/                    # Cohere Command
├── cometapi/                  # CometAPI
├── dashscope/                 # DashScope (Alibaba)
├── deepinfra/                 # DeepInfra
├── deepseek/                  # DeepSeek
├── fireworks/                 # Fireworks AI
├── google/                    # Google
│   └── gemini/                # Gemini models
├── groq/                      # Groq
│   └── reasoning/             # Groq reasoning examples
├── huggingface/               # Hugging Face
├── ibm/                       # IBM
│   └── watsonx/               # WatsonX
├── internlm/                  # InternLM (minimal)
├── langdb/                    # LangDB
├── litellm/                   # LiteLLM
├── litellm_openai/            # LiteLLM (OpenAI-compatible)
├── llama_cpp/                 # llama.cpp (local)
├── lmstudio/                  # LM Studio (local)
├── meta/                      # Meta
│   ├── llama/                 # Llama API
│   └── llama_openai/          # Llama (OpenAI-compatible)
├── mistral/                   # Mistral AI
├── moonshot/                  # Moonshot
├── n1n/                       # N1N
├── nebius/                    # Nebius
├── neosantara/                # NeoSantara
├── nexus/                     # Nexus
├── nvidia/                    # NVIDIA
├── ollama/                    # Ollama (local)
│   ├── chat/                  # Ollama Chat API
│   └── responses/             # Ollama Responses API
├── openai/                    # OpenAI
│   ├── chat/                  # ChatCompletion API
│   └── responses/             # Responses API
├── openrouter/                # OpenRouter
│   ├── chat/                  # Chat API
│   └── responses/             # Responses API
├── perplexity/                # Perplexity
├── portkey/                   # Portkey
├── requesty/                  # Requesty
├── sambanova/                 # SambaNova
├── siliconflow/               # SiliconFlow
├── together/                  # Together AI
├── vercel/                    # Vercel AI
├── vertexai/                  # Vertex AI
│   └── claude/                # Claude on Vertex AI
├── vllm/                      # vLLM (local)
└── xai/                       # xAI (Grok)
```

### Changes from Current

| Change | Details |
|--------|---------|
| **MERGE** stream variants into base | `basic_stream.py` → `basic.py`, `tool_use_stream.py` → `tool_use.py`, etc. (~88 files deleted) |
| **MERGE** async variants into sync base | `async_basic.py` → `basic.py`, `async_tool_use.py` → `tool_use.py`, etc. (~131 files deleted) |
| **DELETE** all `__init__.py` | 56 files removed |
| **FIX** all remaining files | Add docstrings, banners, main gates. Remove emoji |

---

## 3. File Disposition Table

### Standard Merge Pattern

The majority of providers follow the same file pattern. The standard merges apply uniformly:

#### Merge Group A: Basic quadruplet → `basic.py`

| Files to merge | Into |
|---------------|------|
| `basic.py` (sync, no stream) | **base** |
| `basic_stream.py` (sync + stream) | **MERGE INTO** `basic.py` |
| `async_basic.py` (async, no stream) | **MERGE INTO** `basic.py` |
| `async_basic_stream.py` (async + stream) | **MERGE INTO** `basic.py` |
| `async_basic_streaming.py` (alternate name) | **MERGE INTO** `basic.py` |

#### Merge Group B: Tool-use quadruplet → `tool_use.py`

| Files to merge | Into |
|---------------|------|
| `tool_use.py` (sync, no stream) | **base** |
| `tool_use_stream.py` (sync + stream) | **MERGE INTO** `tool_use.py` |
| `async_tool_use.py` (async, no stream) | **MERGE INTO** `tool_use.py` |
| `async_tool_use_stream.py` (async + stream) | **MERGE INTO** `tool_use.py` |

#### Merge Group C: Structured output pair → `structured_output.py`

| Files to merge | Into |
|---------------|------|
| `structured_output.py` | **base** |
| `structured_output_stream.py` | **MERGE INTO** `structured_output.py` |
| `async_structured_output.py` | **MERGE INTO** `structured_output.py` |
| `async_structured_response_stream.py` | **MERGE INTO** `structured_output.py` |

#### Merge Group D: Thinking pair → `thinking.py`

| Files to merge | Into |
|---------------|------|
| `thinking.py` | **base** |
| `thinking_stream.py` | **MERGE INTO** `thinking.py` |

#### All other files → **KEEP + FIX**

Files that are NOT part of the standard quadruplets are unique and should be kept with style fixes only:
- `retry.py` — unique retry/error handling demo
- `db.py` — database setup per provider
- `knowledge.py` — knowledge/RAG per provider
- `memory.py` — memory setup per provider
- `image_agent.py`, `image_agent_bytes.py`, `image_agent_with_memory.py` — image input demos
- `pdf_input_*.py` — PDF input demos
- `audio_input_*.py` — audio input demos
- `video_input_*.py` — video input demos
- Provider-specific features (e.g., `grounding.py`, `prompt_caching.py`, `web_search.py`)

---

### Per-Provider Disposition

#### Providers with standard pattern only (no special files)

These providers have ONLY the standard quadruplet files plus retry/structured_output. Apply standard merges uniformly.

| Provider | Current Files | After Merge | Notes |
|----------|:---:|:---:|-------|
| `fireworks/` | 8 | 4 | basic, tool_use, retry, structured_output |
| `deepinfra/` | 8 | 5 | + json_output.py |
| `sambanova/` | 5 | 3 | basic + async_basic only |
| `moonshot/` | 3 | 3 | No async/stream variants |
| `n1n/` | 3 | 3 | No async/stream variants |
| `internlm/` | 1 | 1 | Only retry.py |
| `neosantara/` | 7 | 4 | basic, tool_use, structured_output |

#### Providers with standard pattern + infrastructure files (db, knowledge, memory)

| Provider | Current Files | After Merge | Special Files to Keep |
|----------|:---:|:---:|-------|
| `cerebras/` | 13 | 7 | db, knowledge, oss_gpt, retry, structured_output |
| `cerebras_openai/` | 12 | 7 | db, knowledge, oss_gpt, structured_output |
| `nebius/` | 12 | 7 | db, knowledge, retry, structured_output |
| `nexus/` | 9 | 5 | retry, structured_output |
| `siliconflow/` | 6 | 5 | retry, structured_output |
| `perplexity/` | 9 | 6 | citations, reasoning_agent, retry, structured_output |
| `nvidia/` | 8 | 5 | retry, structured_output |
| `huggingface/` | 8 | 5 | llama_essay_writer, retry |
| `portkey/` | 10 | 5 | retry, structured_output |
| `requesty/` | 8 | 5 | retry, structured_output |
| `vercel/` | 9 | 5 | retry, structured_output |
| `together/` | 13 | 7 | db, image_agent, knowledge, retry, structured_output |
| `lmstudio/` | 10 | 7 | db, image_agent, knowledge, memory, retry, structured_output |
| `llama_cpp/` | 6 | 4 | retry, structured_output |
| `vllm/` | 12 | 8 | db, image_agent, knowledge, memory, metrics, retry, structured_output |
| `langdb/` | 9 | 7 | agent/agent_stream→agent, data_analyst, finance_agent, retry, structured_output, web_search |

#### Providers with image/media files

| Provider | Current Files | After Merge | Special Files to Keep |
|----------|:---:|:---:|-------|
| `cohere/` | 16 | 9 | db, image_agent, image_agent_bytes, image_agent_local_file, knowledge, memory, retry, structured_output |
| `aimlapi/` | 11 | 6 | image_agent, image_agent_bytes, image_agent_with_memory, retry, structured_output |
| `cometapi/` | 13 | 7 | image_agent, image_agent_with_memory, multi_model, retry, structured_output |
| `xai/` | 16 | 11 | citations, db, finance_agent, image_agent, image_input_bytes, knowledge, live_search_agent+stream, memory, retry, structured_output |

#### `anthropic/` (40 files → ~28)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- tool_use + tool_use_stream → tool_use.py (saves 1)
- structured_output + structured_output_stream → structured_output.py (saves 1)
- thinking + thinking_stream → thinking.py (saves 1)

Keep unique (22 files):
- `basic_with_timeout.py`, `betas.py`, `code_execution.py`, `context_management.py`, `csv_input.py`
- `db.py`, `financial_analyst_thinking.py`
- `image_input_bytes.py`, `image_input_file_upload.py`, `image_input_local_file.py`, `image_input_url.py`
- `knowledge.py`, `mcp_connector.py`, `memory.py`
- `pdf_input_bytes.py`, `pdf_input_file_upload.py`, `pdf_input_local.py`, `pdf_input_url.py`
- `prompt_caching.py`, `prompt_caching_extended.py`
- `retry.py`, `structured_output_strict_tools.py`
- `web_fetch.py`, `web_search.py`

Keep `skills/` subdirectory (4 files):
- `agent_with_documents.py`, `agent_with_excel.py`, `agent_with_powerpoint.py`, `multi_skill_agent.py`
- Delete `skills/__init__.py`, `skills/file_download_helper.py` — helper, not standalone example

#### `google/gemini/` (56 files → ~40)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- tool_use + tool_use_stream → tool_use.py (saves 1)
- structured_output + structured_output_stream → structured_output.py (saves 1)
- thinking_agent + thinking_agent_stream → thinking_agent.py (saves 1)
- image_generation + image_generation_stream + async_image_generation + async_image_generation_stream → image_generation.py (saves 3)
- image_editing + async_image_editing → image_editing.py (saves 1)
- search + search_stream → search.py (saves 1)
- url_context + url_context_stream → url_context.py (saves 1)

Keep unique (~40 files):
- All `*_input_*.py` files (audio, video, pdf, image)
- `agent_with_thinking_budget.py`, `db.py`, `external_url_input.py`
- `file_search_*.py` (3 files), `file_upload_with_cache.py`
- `gcs_file_input.py`, `gemini_2_to_3.py`, `gemini_3_pro.py`, `gemini_3_pro_thinking_level.py`
- `grounding.py`, `imagen_tool.py`, `imagen_tool_advanced.py`
- `knowledge.py`, `retry.py`, `s3_url_file_input.py`
- `storage_and_memory.py`, `text_to_speech.py`
- `url_context_with_search.py`, `vertex_ai_search.py`, `vertexai.py`, `vertexai_with_credentials.py`

#### `openai/chat/` (35 files → ~26)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- tool_use + tool_use_stream → tool_use.py (saves 1)
- structured_output + structured_output_stream + async_structured_response_stream → structured_output.py (saves 2)

Keep unique (~26 files):
- `access_memories_in_memory_completed_event.py`, `agent_flex_tier.py`
- `audio_input_agent.py`, `audio_input_and_output_multi_turn.py`, `audio_input_local_file_upload.py`
- `audio_output_agent.py`, `audio_output_stream.py`
- `basic_stream_metrics.py`, `custom_role_map.py`, `db.py`
- `generate_images.py`, `image_agent.py`, `image_agent_bytes.py`, `image_agent_with_memory.py`
- `knowledge.py`, `memory.py`, `metrics.py`
- `pdf_input_file_upload.py`, `pdf_input_local.py`, `pdf_input_url.py`
- `reasoning_o3_mini.py`, `retry.py`
- `text_to_speech_agent.py`, `verbosity_control.py`, `with_retries.py`

#### `openai/responses/` (26 files → ~22)

Standard merges:
- basic quadruplet → basic.py (saves 3)

Keep unique (~22 files):
- `agent_flex_tier.py`, `db.py`, `deep_research_agent.py`
- `image_agent.py`, `image_agent_bytes.py`, `image_agent_with_memory.py`, `image_generation_agent.py`
- `knowledge.py`, `memory.py`
- `pdf_input_local.py`, `pdf_input_url.py`
- `reasoning_o3_mini.py`, `structured_output.py`, `structured_output_with_tools.py`
- `tool_use.py`, `tool_use_gpt_5.py`, `tool_use_o3.py`, `tool_use_stream.py`
- `verbosity_control.py`, `websearch_builtin_tool.py`, `zdr_reasoning_agent.py`

Note: `openai/responses/` has fewer standard pairs — many tool_use variants use different models (gpt_5, o3). Keep these separate.

#### `ollama/chat/` (20 files → ~17)

Standard merges:
- basic + basic_stream + async_basic + async_basic_stream → basic.py (saves 3)

Keep unique (~17 files):
- `db.py`, `demo_deepseek_r1.py`, `demo_gemma.py`, `demo_phi4.py`, `demo_qwen.py`
- `image_agent.py`, `knowledge.py`, `memory.py`, `ollama_cloud.py`
- `reasoning_agent.py`, `retry.py`, `set_client.py`, `set_temperature.py`
- `structured_output.py`, `tool_use.py`, `tool_use_stream.py`

#### `ollama/responses/` (6 files → ~4)

Standard merges:
- basic + basic_stream + async_basic → basic.py (saves 2)

Keep unique (~4 files): `basic.py`, `structured_output.py`, `tool_use.py`, `tool_use_stream.py`

#### `openrouter/chat/` (9 files → ~5)

Standard merges:
- basic quadruplet → basic.py (saves 3)

Keep unique: `dynamic_model_router.py`, `retry.py`, `structured_output.py`, `tool_use.py`

#### `openrouter/responses/` (6 files → ~4)

Standard merges:
- async_basic → basic.py (saves 1)

Keep unique: `basic.py`, `fallback.py`, `stream.py`, `structured_output.py`, `tool_use.py`

Note: `stream.py` is not a standard `basic_stream.py` — check if it's a specialized streaming demo.

#### `meta/llama/` (16 files → ~10)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- tool_use + tool_use_stream + async_tool_use + async_tool_use_stream → tool_use.py (saves 3)
- async_knowledge → knowledge.py (saves 1, if near-identical)

Keep unique: `db.py`, `image_input_bytes.py`, `image_input_file.py`, `knowledge.py`, `memory.py`, `metrics.py`, `structured_output.py`

#### `meta/llama_openai/` (15 files → ~9)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- tool_use + tool_use_stream + async_tool_use + async_tool_use_stream → tool_use.py (saves 3)

Keep unique: `image_input_bytes.py`, `image_input_file.py`, `knowledge.py`, `memory.py`, `metrics.py`, `storage.py`, `structured_output.py`

#### `aws/bedrock/` (10 files → ~7)

Standard merges:
- basic + basic_stream + async_basic + async_basic_stream → basic.py (saves 3)
- async_tool_use_stream → tool_use_stream.py (saves 1, verify overlap)

Keep unique: `image_agent_bytes.py`, `pdf_agent_bytes.py`, `structured_output.py`, `tool_use.py`, `tool_use_stream.py`

#### `aws/claude/` (11 files → ~7)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- async_tool_use → tool_use.py (saves 1)

Keep unique: `db.py`, `image_agent.py`, `knowledge.py`, `structured_output.py`, `tool_use.py`, `tool_use_stream.py`

#### `azure/ai_foundry/` (14 files → ~10)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- async_tool_use → tool_use.py (saves 1)

Keep unique: `db.py`, `demo_cohere.py`, `demo_mistral.py`, `image_agent.py`, `image_agent_bytes.py`, `knowledge.py`, `structured_output.py`, `tool_use.py`

#### `azure/openai/` (8 files → ~6)

Standard merges:
- basic + basic_stream + async_basic + async_basic_stream → basic.py (saves 2-3)

Keep unique: `db.py`, `knowledge.py`, `structured_output.py`, `tool_use.py`

#### `vertexai/claude/` (21 files → ~16)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- tool_use + tool_use_stream → tool_use.py (saves 1)
- structured_output + structured_output_stream → structured_output.py (saves 1)
- thinking + thinking_stream → thinking.py (saves 1)
- async_tool_use → tool_use.py (already counted)

Keep unique: `basic_with_timeout.py`, `betas.py`, `db.py`, `image_input_bytes.py`, `image_input_url.py`, `knowledge.py`, `memory.py`, `pdf_input_bytes.py`, `pdf_input_local.py`, `prompt_caching.py`

#### `groq/` (20 files in main + 5 in reasoning/)

Main directory (20 → ~16):
- basic quadruplet → basic.py (saves 3)
- async_tool_use → tool_use.py (saves 1)

Keep unique: `agent_team.py`, `browser_search.py`, `db.py`, `deep_knowledge.py`, `image_agent.py`, `knowledge.py`, `metrics.py`, `reasoning_agent.py`, `research_agent_exa.py`, `research_agent_seltz.py`, `retry.py`, `structured_output.py`, `tool_use.py`, `transcription_agent.py`, `translation_agent.py`

`reasoning/` subdirectory (5 files → 5, no merges): all unique demos

#### `deepseek/` (10 files → ~7)

Standard merges:
- basic quadruplet → basic.py (saves 2-3)
- async_tool_use → tool_use.py (saves 1)

Keep unique: `reasoning_agent.py`, `retry.py`, `structured_output.py`, `thinking_tool_calls.py`, `tool_use.py`

#### `mistral/` (17 files → ~10)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- tool_use quadruplet → tool_use.py (saves 3)

Keep unique: ~10 files including image_agent variants, db, knowledge, retry, structured_output

#### `litellm/` (21 files → ~16)

Standard merges:
- basic quadruplet → basic.py (saves 3)
- async_tool_use → tool_use.py (saves 1)

Keep unique: `audio_input_agent.py`, `basic_gpt.py`, `db.py`, `image_agent.py`, `image_agent_bytes.py`, `knowledge.py`, `memory.py`, `metrics.py`, `pdf_input_bytes.py`, `pdf_input_local.py`, `pdf_input_url.py`, `reasoning_agent.py`, `retry.py`, `structured_output.py`, `tool_use.py`, `tool_use_stream.py`

#### `litellm_openai/` (4 files → 4, no merges)

All files are unique: `audio_input_agent.py`, `basic.py`, `basic_stream.py`, `tool_use.py`

#### `dashscope/` (13 files → ~9)

Standard merges:
- basic + basic_stream + async_basic_stream → basic.py (saves 2)
- async_tool_use → tool_use.py (saves 1)
- async_image_agent → image_agent.py (saves 1)

Keep unique: `image_agent.py`, `image_agent_bytes.py`, `knowledge_tools.py`, `retry.py`, `structured_output.py`, `thinking_agent.py`, `tool_use.py`

#### `clients/` (1 file → 1, no merges)

Keep `http_client_caching.py` with style fixes. Remove emoji.

---

### `__init__.py` Files — DELETE ALL

All 56 `__init__.py` files should be deleted. Cookbook directories do not use them.

---

### Emoji Removal

| File | Emoji Found |
|------|-------------|
| `clients/http_client_caching.py` | gear |
| `google/gemini/imagen_tool.py` | wrench |
| `google/gemini/imagen_tool_advanced.py` | wrench |
| `google/gemini/file_search_rag_pipeline.py` | cross marks |
| `xai/finance_agent.py` | newspaper, chart icons |
| `anthropic/context_management.py` | checkmark |
| `anthropic/structured_output_strict_tools.py` | (verify) |
| `anthropic/skills/agent_with_powerpoint.py` | (verify) |
| `openai/chat/text_to_speech_agent.py` | speaker |
| `openai/responses/image_generation_agent.py` | wrench |
| `vllm/memory.py` | (verify) |

---

## 4. New Files Needed

No new files needed. The 44 providers already have comprehensive coverage.

---

## 5. Missing READMEs and TEST_LOGs

### Provider directories missing README.md

| Directory | README.md | TEST_LOG.md |
|-----------|-----------|-------------|
| `90_models/` (root) | EXISTS | **MISSING** |
| `aimlapi/` | EXISTS | **MISSING** |
| `anthropic/` | EXISTS | **MISSING** |
| `anthropic/skills/` | EXISTS | **MISSING** |
| `aws/` | **MISSING** | **MISSING** |
| `aws/bedrock/` | EXISTS | **MISSING** |
| `aws/claude/` | EXISTS | **MISSING** |
| `azure/` | **MISSING** | **MISSING** |
| `azure/ai_foundry/` | EXISTS | **MISSING** |
| `azure/openai/` | EXISTS | **MISSING** |
| `cerebras/` | **MISSING** | **MISSING** |
| `cerebras_openai/` | **MISSING** | **MISSING** |
| `clients/` | **MISSING** | **MISSING** |
| `cohere/` | EXISTS | **MISSING** |
| `cometapi/` | EXISTS | **MISSING** |
| `dashscope/` | EXISTS | **MISSING** |
| `deepinfra/` | EXISTS | **MISSING** |
| `deepseek/` | EXISTS | **MISSING** |
| `fireworks/` | EXISTS | **MISSING** |
| `google/` | **MISSING** | **MISSING** |
| `google/gemini/` | EXISTS | **MISSING** |
| `groq/` | EXISTS | **MISSING** |
| `groq/reasoning/` | **MISSING** | **MISSING** |
| `huggingface/` | EXISTS | **MISSING** |
| `ibm/` | **MISSING** | **MISSING** |
| `ibm/watsonx/` | EXISTS | **MISSING** |
| `internlm/` | **MISSING** | **MISSING** |
| `langdb/` | EXISTS | **MISSING** |
| `litellm/` | EXISTS | **MISSING** |
| `litellm_openai/` | EXISTS | **MISSING** |
| `llama_cpp/` | EXISTS | **MISSING** |
| `lmstudio/` | EXISTS | **MISSING** |
| `meta/` | EXISTS | **MISSING** |
| `meta/llama/` | **MISSING** | **MISSING** |
| `meta/llama_openai/` | **MISSING** | **MISSING** |
| `mistral/` | EXISTS | **MISSING** |
| `moonshot/` | **MISSING** | **MISSING** |
| `n1n/` | **MISSING** | **MISSING** |
| `nebius/` | **MISSING** | **MISSING** |
| `neosantara/` | EXISTS | **MISSING** |
| `nexus/` | EXISTS | **MISSING** |
| `nvidia/` | EXISTS | **MISSING** |
| `ollama/` | EXISTS | **MISSING** |
| `ollama/chat/` | **MISSING** | **MISSING** |
| `ollama/responses/` | **MISSING** | **MISSING** |
| `openai/` | **MISSING** | **MISSING** |
| `openai/chat/` | EXISTS | **MISSING** |
| `openai/responses/` | **MISSING** | **MISSING** |
| `openrouter/` | EXISTS | **MISSING** |
| `openrouter/chat/` | **MISSING** | **MISSING** |
| `openrouter/responses/` | **MISSING** | **MISSING** |
| `perplexity/` | EXISTS | **MISSING** |
| `portkey/` | EXISTS | **MISSING** |
| `requesty/` | EXISTS | **MISSING** |
| `sambanova/` | EXISTS | **MISSING** |
| `siliconflow/` | EXISTS | **MISSING** |
| `together/` | EXISTS | **MISSING** |
| `vercel/` | EXISTS | **MISSING** |
| `vertexai/` | **MISSING** | **MISSING** |
| `vertexai/claude/` | EXISTS | **MISSING** |
| `vllm/` | EXISTS | **MISSING** |
| `xai/` | EXISTS | **MISSING** |

---

## 6. Recommended Cookbook Template

```python
"""
<Provider> Basic Usage
=============================

Demonstrates basic agent usage with <Provider>.
"""

from agno.agent import Agent
from agno.models.<provider> import <ProviderClass>

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=<ProviderClass>(id="<model-id>"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Share a 2 sentence horror story")

    # --- Sync + Streaming ---
    agent.print_response("Share a 2 sentence horror story", stream=True)

    # --- Async ---
    import asyncio

    asyncio.run(agent.aprint_response("Share a 2 sentence horror story"))

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("Share a 2 sentence horror story", stream=True)
    )
```

### Template for tool_use.py

```python
"""
<Provider> Tool Use
=============================

Demonstrates tool calling with <Provider>.
"""

from agno.agent import Agent
from agno.models.<provider> import <ProviderClass>
from agno.tools.websearch import WebSearchTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=<ProviderClass>(id="<model-id>"),
    tools=[WebSearchTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("Whats happening in France?")

    # --- Sync + Streaming ---
    agent.print_response("Whats happening in France?", stream=True)

    # --- Async ---
    import asyncio

    asyncio.run(agent.aprint_response("Whats happening in France?"))
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Create Agent → Run Agent (simpler than other sections — most model examples don't need Setup)
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **All variants in one file** — Sync, stream, async, async+stream shown as labeled sections in the main gate
8. **Preserve model IDs** — Do NOT change model provider imports or model IDs
9. **Self-contained** — Each file must be independently runnable
