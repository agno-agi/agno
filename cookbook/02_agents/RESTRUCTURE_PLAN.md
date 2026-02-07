# Restructuring Plan: `cookbook/02_agents/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Subdirectories | 19 |
| Total `.py` files (non-`__init__`) | 164 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~68 (~41%) |
| Have section banners | ~4 (~2%, culture/ only, non-standard `# ---` format) |
| Have `if __name__` gate | ~52 (~32%) |
| Contain emoji | ~9 (human_in_the_loop, multimodal) |
| Subdirectories with README.md | 4 / 19 |
| Subdirectories with TEST_LOG.md | 0 / 19 |

### Key Problems

1. **Massive redundancy.** Sync/async/stream/stream_async variants are split into separate files with >95% code duplication. The worst offender is `human_in_the_loop/` (23 files for 3 concepts). `caching/` has 4 files for 1 concept.

2. **Near-zero style compliance.** No file follows the full STYLE_GUIDE.md pattern (module docstring + section banners + Create/Run flow + main gate + no emoji). The best-structured files (culture/) use non-standard `# ---` banners instead of the required `# ============================================================================` format.

3. **Catch-all directories.** `other/` (14 files) and `async/` (9 files) are dumping grounds. `async/` duplicates features covered in other directories. `other/` mixes metrics, debugging, cancellation, testing, and miscellany.

4. **Overlapping directories.** `agentic_search/` and `rag/` both cover RAG patterns. `session/` and `state/` have overlapping files (e.g., `last_n_session_messages.py` is about session history, not state).

5. **Missing documentation.** 15/19 subdirectories have no README.md. No subdirectory has a TEST_LOG.md.

6. **Coverage gaps.** Major agent features like learning, reasoning, serialization, and dynamic tools have no cookbook examples.

### Overall Assessment

The directory needs aggressive consolidation. The current 164 files can be reduced to ~77 without losing feature coverage, while adding ~6 new files for undocumented capabilities. Every surviving file needs style guide remediation.

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 164 | ~77 |
| Directories | 19 | 19 (3 removed, 3 added) |
| Style compliance | 0% | 100% |
| README coverage | 4/19 | 19/19 |
| TEST_LOG coverage | 0/19 | 19/19 |

---

## 2. Proposed Directory Structure

Remove `async/`, `other/`, and `agentic_search/`. Add `learning/`, `reasoning/`, and `run_control/`. Rename `custom_logging/` to `logging/`.

```
cookbook/02_agents/
├── caching/                    # Model response caching strategies
├── context_compression/        # Tool call result compression and token management
├── context_management/         # Agent instructions, context injection, few-shot learning
├── culture/                    # Cultural knowledge creation and management
├── dependencies/               # Runtime dependency injection and dynamic tools
├── events/                     # Agent event streaming and monitoring
├── guardrails/                 # Input/output safety: moderation, PII, prompt injection
├── hooks/                      # Pre-hook, post-hook, and stream-hook lifecycle callbacks
├── human_in_the_loop/          # Tool confirmation, user input requests, external execution
├── input_and_output/           # Input formats, structured output schemas, parser models
├── learning/                   # [NEW] Learning from outcomes via LearningMachine
├── logging/                    # [RENAMED] Custom logger configuration
├── multimodal/                 # Image, audio, and video input/output processing
├── rag/                        # Retrieval-augmented generation (absorbs agentic_search/)
├── reasoning/                  # [NEW] Extended step-by-step reasoning
├── run_control/                # [NEW] Cancellation, retries, debug, limits, serialization
├── session/                    # Session persistence, history, and summaries
├── skills/                     # Agent skills with reference documents and scripts
└── state/                      # Session state: read, write, agentic, multi-user
```

### Changes from Current

| Change | Details |
|--------|---------|
| **REMOVE** `async/` | Dissolved. Async is a cross-cutting pattern, not a feature. The one unique file (concurrent execution) moves to `run_control/`. |
| **REMOVE** `other/` | Dissolved. Files redistributed to `run_control/`, `events/`, or cut. |
| **REMOVE** `agentic_search/` | Merged into `rag/`. Both directories cover RAG patterns. |
| **RENAME** `custom_logging/` → `logging/` | Shorter, clearer name. |
| **ADD** `learning/` | Covers LearningMachine, a major agent feature with no cookbook example. |
| **ADD** `reasoning/` | Covers extended reasoning, a major agent feature with only a trivial 19-line example buried in `async/`. |
| **ADD** `run_control/` | Groups operational concerns: cancel, retry, debug, limits, metrics, serialization, concurrent execution. |

---

## 3. File Disposition Table

Dispositions: **KEEP** (good as-is, compliant), **KEEP + FIX** (good content, needs style fixes), **KEEP + RENAME** (rename for clarity), **MERGE INTO** (consolidate), **CUT** (remove), **REWRITE** (feature needs coverage but file is inadequate).

Style fixes needed on virtually all files: add section banners, add/improve module docstring, add `if __name__` gate, remove emoji.

---

### `agentic_search/` → merge into `rag/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `agentic_rag.py` | **CUT** | — | Duplicate of `rag/agentic_rag_lancedb.py` (both use LanceDB + Cohere for agentic RAG) |
| `agentic_rag_infinity_reranker.py` | **MERGE INTO** `rag/agentic_rag_with_reranking.py` | `rag/agentic_rag_with_reranking.py` | Infinity reranker is a reranking variant; merge with existing reranking example to show multiple reranker options |
| `agentic_rag_with_reasoning.py` | **KEEP + MOVE + FIX** | `rag/agentic_rag_with_reasoning.py` | Unique: combines RAG with extended reasoning. Add banners, docstring, main gate |
| `lightrag/agentic_rag_with_lightrag.py` | **KEEP + MOVE + FIX** | `rag/agentic_rag_lightrag.py` | Unique: LightRag vector DB backend. Add docstring, banners, main gate |

---

### `async/` → dissolve

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `basic.py` | **CUT** | — | Basic async run is trivial (32 lines) and shown in many other files |
| `concurrent_tool_calls.py` | **CUT** | — | Concurrent tool execution is adequately covered by `gather_agents.py` pattern |
| `data_analyst.py` | **CUT** | — | This is a DuckDB tools demo, not an async pattern. Tool-specific examples belong in `cookbook/90_tools/` |
| `delay.py` | **CUT** | — | Contrived staggered-start example with no practical pattern |
| `gather_agents.py` | **KEEP + MOVE + FIX** | `run_control/concurrent_execution.py` | Unique: `asyncio.gather` for concurrent agent execution. The only genuinely async-specific pattern |
| `reasoning.py` | **CUT** | — | 19 lines, trivial. Reasoning covered properly by new `reasoning/` directory |
| `streaming.py` | **CUT** | — | 31 lines. Streaming is a param (`stream=True`), not a standalone feature. Shown in many files |
| `structured_output.py` | **CUT** | — | 64 lines. Structured output fully covered in `input_and_output/` |
| `tool_use.py` | **CUT** | — | 13 lines. Trivial: just adds WebSearch tools to an async agent |

---

### `caching/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `cache_model_response.py` | **REWRITE** | `caching/cache_model_response.py` | Merge all 4 files into one. Show sync + async + streaming in sections within a single file |
| `async_cache_model_response.py` | **MERGE INTO** `caching/cache_model_response.py` | — | Async variant; only difference is `asyncio.run()` + `aprint_response` |
| `cache_model_response_stream.py` | **MERGE INTO** `caching/cache_model_response.py` | — | Streaming variant; only difference is `stream=True` |
| `async_cache_model_response_stream.py` | **MERGE INTO** `caching/cache_model_response.py` | — | Async streaming variant; trivially different from sync streaming |

**Result: 4 → 1 file**

---

### `context_compression/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `tool_call_compression.py` | **REWRITE** | `context_compression/tool_call_compression.py` | Merge sync + async into one file showing both. Add docstring, banners, main gate |
| `async_tool_call_compression.py` | **MERGE INTO** `context_compression/tool_call_compression.py` | — | Async variant; only adds `asyncio.run()` wrapper |
| `token_based_tool_call_compression.py` | **REWRITE** | `context_compression/advanced_compression.py` | Merge with manager-based compression. Both show advanced compression config |
| `tool_call_compression_with_manager.py` | **MERGE INTO** `context_compression/advanced_compression.py` | — | Manager variant of advanced compression. Also fix typo "alwayd" → "always" |
| `compression_events.py` | **KEEP + FIX** | `context_compression/compression_events.py` | Unique: monitoring compression via RunEvent. Add docstring, banners |

**Result: 5 → 3 files**

---

### `context_management/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `introduction.py` | **CUT** | — | 19 lines. Just sets `INTRODUCTION` string — trivial, not a distinct feature |
| `datetime_instructions.py` | **REWRITE** (merge) | `context_management/instructions.py` | Merge all 4 instruction-variant files into one showing: datetime, location, dynamic, and callable patterns |
| `location_instructions.py` | **MERGE INTO** `context_management/instructions.py` | — | 12 lines. Location in instructions — trivial variant |
| `dynamic_instructions.py` | **MERGE INTO** `context_management/instructions.py` | — | 15 lines. Dynamic instructions via RunContext — same concept |
| `instructions_via_function.py` | **MERGE INTO** `context_management/instructions.py` | — | 20 lines. Callable instructions — same concept |
| `instruction_tags.py` | **KEEP + FIX** | `context_management/instruction_tags.py` | Unique: XML tag formatting for structured instructions. Add banners, main gate |
| `few_shot_learning.py` | **KEEP + FIX** | `context_management/few_shot_learning.py` | Unique: `additional_input` for few-shot examples. Already has main gate; add banners |
| `filter_tool_calls_from_history.py` | **KEEP + FIX** | `context_management/filter_tool_calls_from_history.py` | Unique: post-hook to filter tool calls from history. Add banners, main gate |

**Also add** `input_and_output/instructions.py` → **MOVE** to `context_management/instructions_with_state.py` (demonstrates instructions built from RunContext and session state — belongs here, not in I/O).

**Result: 8 → 4 files (+ 1 moved in = 5 files)**

---

### `culture/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_create_cultural_knowledge.py` | **KEEP + FIX** | `culture/01_create_cultural_knowledge.py` | Best-structured file in entire cookbook. Fix: replace `# ---` banners with standard `# ====` format, add main gate |
| `02_use_cultural_knowledge_in_agent.py` | **KEEP + FIX** | `culture/02_use_cultural_knowledge_in_agent.py` | Well structured. Fix: standard banners, main gate |
| `03_automatic_cultural_management.py` | **KEEP + FIX** | `culture/03_automatic_cultural_management.py` | Unique: autonomous culture discovery. Fix: standard banners, main gate |
| `04_manually_add_culture.py` | **KEEP + FIX** | `culture/04_manually_add_culture.py` | Unique: explicit manual culture entry. Fix: standard banners, main gate |
| `05_test_agent_with_culture.py` | **CUT** | — | 28 lines. Self-describes as "sample file." Not a proper cookbook entry — more like a scratch test |

**Result: 5 → 4 files**

---

### `custom_logging/` → rename to `logging/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `custom_logging.py` | **REWRITE** | `logging/custom_logging.py` | Merge all 3 files into one: basic logger + advanced handlers + file output. All demonstrate the same feature (configure_agno_logging) |
| `custom_logging_advanced.py` | **MERGE INTO** `logging/custom_logging.py` | — | Advanced handlers — same feature, slightly more config |
| `log_to_file.py` | **MERGE INTO** `logging/custom_logging.py` | — | FileHandler — same feature, different handler type |

**Result: 3 → 1 file**

---

### `dependencies/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `access_dependencies_in_tool.py` | **REWRITE** | `dependencies/dependencies_in_tools.py` | Merge with `add_dependencies_on_run.py`. Show: (1) declaring deps on agent, (2) passing deps at run time, (3) accessing deps in tools via RunContext |
| `add_dependencies_on_run.py` | **MERGE INTO** `dependencies/dependencies_in_tools.py` | — | Runtime dep injection — same concept as access_dependencies |
| `add_dependencies_to_context.py` | **REWRITE** | `dependencies/dependencies_in_context.py` | Merge with `reference_dependencies.py` and `dependencies_functions.py`. Show: deps available in instructions, referenced in callables, and dynamic dep functions |
| `reference_dependencies.py` | **MERGE INTO** `dependencies/dependencies_in_context.py` | — | Referencing deps in instruction functions — same concept |
| `dependencies_functions.py` | **MERGE INTO** `dependencies/dependencies_in_context.py` | — | Dynamic dep functions — same concept |

**Result: 5 → 2 files**

---

### `events/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `basic_agent_events.py` | **KEEP + FIX** | `events/basic_agent_events.py` | Core: monitoring RunEvent types. Add docstring, banners, main gate |
| `reasoning_agent_events.py` | **KEEP + FIX** | `events/reasoning_agent_events.py` | Unique: reasoning-specific events. Add docstring, banners, main gate |

**Result: 2 → 2 files (no change)**

---

### `guardrails/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `openai_moderation.py` | **KEEP + FIX** | `guardrails/openai_moderation.py` | Unique: OpenAI text + image moderation. Add banners, main gate |
| `pii_detection.py` | **KEEP + FIX** | `guardrails/pii_detection.py` | Unique: PII detection + anonymization. Add docstring, banners, main gate |
| `prompt_injection.py` | **KEEP + FIX** | `guardrails/prompt_injection.py` | Unique: prompt injection blocking. Add docstring, banners, main gate |

**Result: 3 → 3 files (no change, all unique guardrail types)**

---

### `hooks/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `input_validation_pre_hook.py` | **REWRITE** | `hooks/pre_hook_input.py` | Merge with `input_transformation_pre_hook.py`. Show both validation (reject bad input) and transformation (modify input) in one file |
| `input_transformation_pre_hook.py` | **MERGE INTO** `hooks/pre_hook_input.py` | — | Input transformation — closely related to input validation |
| `output_validation_post_hook.py` | **REWRITE** | `hooks/post_hook_output.py` | Merge with `output_transformation_post_hook.py`. Show both validation and transformation of output |
| `output_transformation_post_hook.py` | **MERGE INTO** `hooks/post_hook_output.py` | — | Output transformation — closely related to output validation |
| `output_stream_hook_send_notification.py` | **KEEP + RENAME + FIX** | `hooks/stream_hook.py` | Unique: stream-phase hooks for notifications. Rename for clarity. Add docstring, banners, main gate |
| `session_state_pre_hook.py` | **REWRITE** | `hooks/session_state_hooks.py` | Merge pre + post session state hooks into one file showing both lifecycle phases |
| `session_state_post_hook.py` | **MERGE INTO** `hooks/session_state_hooks.py` | — | Post-hook for session state — same feature as pre-hook |

**Result: 7 → 4 files**

---

### `human_in_the_loop/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `confirmation_required.py` | **REWRITE** | `human_in_the_loop/confirmation_required.py` | Merge 4 sync/async/stream variants into one file with sections for each pattern. Remove emoji from docstring |
| `confirmation_required_async.py` | **MERGE INTO** `confirmation_required.py` | — | Async variant; only adds `asyncio.run()` + `arun()`. 95%+ code overlap |
| `confirmation_required_stream.py` | **MERGE INTO** `confirmation_required.py` | — | Streaming variant; only adds `stream=True` loop. 95%+ overlap |
| `confirmation_required_stream_async.py` | **MERGE INTO** `confirmation_required.py` | — | Async streaming; trivially different from sync streaming |
| `confirmation_required_with_run_id.py` | **MERGE INTO** `confirmation_advanced.py` | — | Run ID tracking — a parameter variation, not a standalone feature |
| `confirmation_required_with_history.py` | **MERGE INTO** `confirmation_advanced.py` | — | Session history context — a parameter variation |
| `confirmation_required_multiple_tools.py` | **REWRITE** | `human_in_the_loop/confirmation_advanced.py` | Merge run_id, history, multiple_tools, and mixed_tools into one file showing advanced confirmation patterns |
| `confirmation_required_mixed_tools.py` | **MERGE INTO** `confirmation_advanced.py` | — | Mix of confirmed/unconfirmed tools — closely related to multiple_tools |
| `confirmation_required_toolkit.py` | **REWRITE** | `human_in_the_loop/confirmation_toolkit.py` | Merge toolkit + MCP toolkit into one file showing both approaches |
| `confirmation_required_mcp_toolkit.py` | **MERGE INTO** `confirmation_toolkit.py` | — | MCP toolkit variant — same concept as toolkit-based confirmation |
| `user_input_required.py` | **REWRITE** | `human_in_the_loop/user_input_required.py` | Merge all 5 user input variants (sync, async, stream, stream_async, all_fields) into one file. Remove emoji |
| `user_input_required_async.py` | **MERGE INTO** `user_input_required.py` | — | Async variant; trivially different |
| `user_input_required_stream.py` | **MERGE INTO** `user_input_required.py` | — | Streaming variant; trivially different |
| `user_input_required_stream_async.py` | **MERGE INTO** `user_input_required.py` | — | Async streaming; trivially different |
| `user_input_required_all_fields.py` | **MERGE INTO** `user_input_required.py` | — | Complex input schema — a section within the main user input file |
| `agentic_user_input.py` | **KEEP + FIX** | `human_in_the_loop/agentic_user_input.py` | Unique: agent autonomously decides when to request user input (vs. declarative `requires_user_input`). Add banners, main gate |
| `external_tool_execution.py` | **REWRITE** | `human_in_the_loop/external_tool_execution.py` | Merge all 7 external execution variants into one file. Show sync + async, and note silent/toolkit options. Remove emoji |
| `external_tool_execution_async.py` | **MERGE INTO** `external_tool_execution.py` | — | Async variant; trivially different |
| `external_tool_execution_stream.py` | **MERGE INTO** `external_tool_execution.py` | — | Streaming variant; trivially different |
| `external_tool_execution_stream_async.py` | **MERGE INTO** `external_tool_execution.py` | — | Async streaming; trivially different |
| `external_tool_execution_async_responses.py` | **MERGE INTO** `external_tool_execution.py` | — | Async response handling — minor variant |
| `external_tool_execution_silent.py` | **MERGE INTO** `external_tool_execution.py` | — | Silent mode — one parameter difference |
| `external_tool_execution_toolkit.py` | **MERGE INTO** `external_tool_execution.py` | — | Toolkit approach — a section in the merged file |

**Result: 23 → 6 files**

---

### `input_and_output/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `input_as_dict.py` | **REWRITE** | `input_and_output/input_formats.py` | Merge all 4 input format files into one showing dict, list, Message, and messages list |
| `input_as_list.py` | **MERGE INTO** `input_formats.py` | — | 16 lines. List input — trivial variant of dict input |
| `input_as_message.py` | **MERGE INTO** `input_formats.py` | — | 19 lines. Message input — trivial variant |
| `input_as_messages_list.py` | **MERGE INTO** `input_formats.py` | — | 25 lines. Messages list — trivial variant |
| `input_schema_on_agent.py` | **REWRITE** | `input_and_output/input_schema.py` | Merge Pydantic + TypedDict + structured_input into one file showing input validation approaches |
| `input_schema_on_agent_as_typed_dict.py` | **MERGE INTO** `input_schema.py` | — | TypedDict variant of input schema |
| `structured_input.py` | **MERGE INTO** `input_schema.py` | — | Structured input from Pydantic model — same concept |
| `instructions.py` | **MOVE** | `context_management/instructions_with_state.py` | Demonstrates instructions built from RunContext and session state — belongs in context_management, not I/O |
| `output_model.py` | **REWRITE** | `input_and_output/output_schema.py` | Merge output_model + output_schema_override + json_schema_output into one file showing all output structuring approaches |
| `output_schema_override.py` | **MERGE INTO** `output_schema.py` | — | Schema override — variant of output schema |
| `json_schema_output.py` | **MERGE INTO** `output_schema.py` | — | JSON schema format — variant of output schema |
| `parser_model.py` | **REWRITE** | `input_and_output/parser_model.py` | Merge parser_model + parser_model_stream into one file. Show sync and streaming parser usage |
| `parser_model_ollama.py` | **CUT** | — | Ollama-specific variant of parser_model. Provider choice is not a distinct pattern |
| `parser_model_stream.py` | **MERGE INTO** `parser_model.py` | — | Streaming parser model — same concept, add as a section |
| `structured_input_output_with_parser_model.py` | **CUT** | — | Combines input schema + parser model — redundant with the two individual files |
| `response_as_variable.py` | **KEEP + FIX** | `input_and_output/response_as_variable.py` | Unique: capturing RunOutput as a variable. Add docstring, banners, main gate |

**Result: 16 → 5 files (+ 1 moved to context_management)**

---

### `multimodal/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_media_input_for_tool.py` | **KEEP + RENAME + FIX** | `multimodal/media_input_for_tool.py` | Unique: tools accessing uploaded media files. Drop number prefix, add banners |
| `02_media_input_to_agent_and_tool.py` | **CUT** | — | Overlaps with `01_media_input_for_tool.py`. Both show media passed to tools; this one adds multi-image which is a minor variant |
| `image_to_text.py` | **KEEP + FIX** | `multimodal/image_to_text.py` | Core: vision model analyzing images. Add docstring, banners, main gate |
| `image_input_high_fidelity.py` | **CUT** | — | 19 lines. Just adds `detail="high"` parameter. Not a distinct feature |
| `image_input_multi-turn.py` | **CUT** | — | 21 lines. Just calls `agent.run()` twice with images. Multi-turn is shown elsewhere |
| `image_to_structured_output.py` | **KEEP + FIX** | `multimodal/image_to_structured_output.py` | Unique: vision + Pydantic output schema. Add docstring, banners, main gate |
| `image_to_image_agent.py` | **KEEP + RENAME + FIX** | `multimodal/image_to_image.py` | Unique: FAL AI image transformation. Drop `_agent` suffix, add docstring, banners, main gate |
| `image_to_audio.py` | **KEEP + FIX** | `multimodal/image_to_audio.py` | Unique: cross-modal (image → story → speech). Fix: remove emoji, add docstring, banners, main gate |
| `agent_same_run_image_analysis.py` | **CUT** | — | 19 lines. Trivial DALL-E + analysis — not a distinct multimodal feature |
| `agent_using_multimodal_tool_response_in_runs.py` | **CUT** | — | 21 lines. Overlaps with `agent_same_run_image_analysis.py` |
| `audio_input_output.py` | **KEEP + FIX** | `multimodal/audio_input_output.py` | Core: audio I/O with speech model. Add docstring, banners, main gate |
| `audio_multi_turn.py` | **CUT** | — | 32 lines. Near-duplicate of `audio_input_output.py` with a second turn added |
| `audio_sentiment_analysis.py` | **KEEP + FIX** | `multimodal/audio_sentiment_analysis.py` | Unique: sentiment analysis from audio. Add docstring, banners, main gate |
| `audio_streaming.py` | **KEEP + FIX** | `multimodal/audio_streaming.py` | Unique: real-time PCM16 audio streaming. Add docstring, banners, main gate |
| `audio_to_text.py` | **KEEP + FIX** | `multimodal/audio_to_text.py` | Unique: audio transcription with Gemini. Add docstring, banners, main gate |
| `generate_image_with_intermediate_steps.py` | **CUT** | — | 29 lines. Intermediate steps is a run_control concern, not multimodal-specific |
| `generate_video_using_models_lab.py` | **CUT** | — | 19 lines. Provider-specific video generation. Redundant with Replicate variant |
| `generate_video_using_replicate.py` | **CUT** | — | 25 lines. Provider-specific video generation. Neither teaches a general pattern |
| `video_caption_agent.py` | **KEEP + RENAME + FIX** | `multimodal/video_caption.py` | Unique: video processing with MoviePy. Drop `_agent` suffix, add docstring, banners, main gate |
| `video_to_shorts.py` | **CUT** | — | 136 lines. Full application (not a minimal feature demo). Violates cookbook purpose |

**Result: 20 → 10 files**

---

### `other/` → dissolve into `run_control/` (new) and `events/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `agent_metrics.py` | **REWRITE** | `run_control/metrics.py` | Merge with `agent_extra_metrics.py` and `agent_run_metadata.py` into one file showing all metrics: message metrics, token metrics, custom run metadata |
| `agent_extra_metrics.py` | **MERGE INTO** `run_control/metrics.py` | — | Extra token/cache metrics — same feature as basic metrics |
| `agent_run_metadata.py` | **MERGE INTO** `run_control/metrics.py` | — | Custom run metadata — closely related to metrics |
| `agent_model_string.py` | **CUT** | — | 11 lines. Using `model="provider:id"` string format. Trivial, belongs in README not a cookbook |
| `agent_retries.py` | **KEEP + MOVE + FIX** | `run_control/retries.py` | Unique: retry config with exponential backoff. Add docstring, banners, main gate |
| `cancel_a_run.py` | **KEEP + MOVE + FIX** | `run_control/cancel_run.py` | Unique: run cancellation from separate thread. Add banners |
| `cancel_a_run_with_redis.py` | **CUT** | — | Redis variant of cancellation. The in-memory version demonstrates the pattern adequately |
| `cancel_a_run_async_with_redis.py` | **CUT** | — | Async Redis variant. Same pattern, different transport |
| `debug.py` | **REWRITE** | `run_control/debug.py` | Merge with `debug_level.py`. Show: enabling debug, debug levels 1 vs 2 |
| `debug_level.py` | **MERGE INTO** `run_control/debug.py` | — | Debug level configuration — same feature as basic debug |
| `intermediate_steps.py` | **CUT** | — | 20 lines. Overlaps with `events/basic_agent_events.py` which covers event streaming more thoroughly |
| `run_response_events.py` | **CUT** | — | 36 lines. Overlaps with `events/basic_agent_events.py` |
| `scenario_testing.py` | **CUT** | — | Testing utility, not a feature demo. Doesn't teach an agent capability |
| `tool_call_limit.py` | **KEEP + MOVE + FIX** | `run_control/tool_call_limit.py` | Unique: `tool_call_limit` parameter. Add docstring, banners, main gate |

**Result: 14 → 5 files in `run_control/` (+ 1 from `async/` = 6 total)**

---

### `rag/` (absorbs `agentic_search/` files)

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `traditional_rag_lancedb.py` | **KEEP + RENAME + FIX** | `rag/traditional_rag.py` | Core: traditional RAG with knowledge in context. Rename to drop backend suffix; note pgvector alternative in comments. Add docstring, banners, main gate |
| `traditional_rag_pgvector.py` | **CUT** | — | Near-identical to LanceDB version. Only differs in vector DB initialization. Note pgvector option in the kept file |
| `agentic_rag_lancedb.py` | **KEEP + RENAME + FIX** | `rag/agentic_rag.py` | Core: agentic RAG with knowledge as tool. Rename to drop backend suffix. Add docstring, banners, main gate |
| `agentic_rag_pgvector.py` | **CUT** | — | Near-identical to LanceDB version. Only differs in vector DB init |
| `agentic_rag_with_reranking.py` | **REWRITE** | `rag/agentic_rag_with_reranking.py` | Merge with `agentic_search/agentic_rag_infinity_reranker.py`. Show Cohere reranker + note Infinity reranker alternative |
| `rag_sentence_transformer.py` | **KEEP + RENAME + FIX** | `rag/rag_custom_embeddings.py` | Unique: custom embeddings with SentenceTransformer. Rename for clarity. Add docstring, banners, main gate |
| `rag_with_lance_db_and_sqlite.py` | **CUT** | — | Hybrid LanceDB + SQLite storage. Not a distinct enough RAG pattern to justify a separate file |
| `local_rag_langchain_qdrant.py` | **KEEP + RENAME + FIX** | `rag/rag_langchain_qdrant.py` | Unique: third-party LangChain + Qdrant integration. Drop "local_" prefix. Add docstring, banners, main gate |

**Plus from `agentic_search/`:**

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `agentic_rag_with_reasoning.py` | **KEEP + MOVE + FIX** | `rag/agentic_rag_with_reasoning.py` | (Listed in agentic_search section above) |
| `agentic_rag_with_lightrag.py` | **KEEP + MOVE + FIX** | `rag/agentic_rag_lightrag.py` | (Listed in agentic_search section above) |

**Result: 8 rag/ + 4 agentic_search/ = 12 total → 7 files**

---

### `session/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_persistent_session.py` | **REWRITE** | `session/persistent_session.py` | Merge with `02_persistent_session_history.py`. Show: basic persistence + enabling history. Drop number prefix |
| `02_persistent_session_history.py` | **MERGE INTO** `session/persistent_session.py` | — | Adding `add_history_to_messages=True` is one parameter — not a separate cookbook |
| `03_session_summary.py` | **REWRITE** | `session/session_summary.py` | Merge with 04 (references), 11 (custom instructions), 12 (async). Show all summary features in sections |
| `04_session_summary_references.py` | **MERGE INTO** `session/session_summary.py` | — | Adding references is one parameter variation |
| `05_chat_history.py` | **REWRITE** | `session/chat_history.py` | Merge with 13 (num_messages). Show: reading history + limiting message count |
| `06_rename_session.py` | **MERGE INTO** `session/session_options.py` | — | 26 lines. Session renaming — a minor API call |
| `07_in_memory_db.py` | **MERGE INTO** `session/session_options.py` | — | 38 lines. Alternative DB backend — a config option |
| `08_cache_session.py` | **MERGE INTO** `session/session_options.py` | — | 25 lines. `cache_session=True` — one parameter toggle |
| `09_disable_storing_history_messages.py` | **REWRITE** | `session/session_options.py` | Merge 06, 07, 08, 09, 10 into one file showing session configuration options |
| `10_disable_storing_tool_messages.py` | **MERGE INTO** `session/session_options.py` | — | Disabling tool message storage — one parameter |
| `11_custom_session_summary_instructions.py` | **MERGE INTO** `session/session_summary.py` | — | Custom summary instructions — a section in the summary file |
| `12_async_session_summary.py` | **MERGE INTO** `session/session_summary.py` | — | Async summary — a section in the summary file |
| `13_chat_history_num_messages.py` | **MERGE INTO** `session/chat_history.py` | — | Limiting history messages — same feature as reading history |

**Result: 13 → 4 files**

---

### `skills/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `basic_skills.py` | **KEEP + FIX** | `skills/basic_skills.py` | Core: skill definitions. Add docstring, banners, main gate |
| `sample_skills/code-review/scripts/check_style.py` | **KEEP** | (unchanged) | Support file for skills demo |
| `sample_skills/git-workflow/scripts/commit_message.py` | **KEEP** | (unchanged) | Support file for skills demo |

**Result: 3 → 3 files (no change)**

---

### `state/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `session_state_basic.py` | **REWRITE** | `state/session_state_basic.py` | Merge with `session_state_in_instructions.py`, `session_state_in_context.py`, and `change_state_on_run.py`. Show: basic state dict, state in instructions, state in context, state changes across runs |
| `session_state_in_instructions.py` | **MERGE INTO** `state/session_state_basic.py` | — | 14 lines. State variable in instructions — trivial variant of basic state |
| `session_state_in_context.py` | **MERGE INTO** `state/session_state_basic.py` | — | 37 lines. State interpolated in instructions — same concept |
| `change_state_on_run.py` | **MERGE INTO** `state/session_state_basic.py` | — | 33 lines. State changes between runs — natural extension of basic state |
| `agentic_session_state.py` | **KEEP + FIX** | `state/agentic_session_state.py` | Unique: LLM autonomously modifies state. Add docstring, banners, main gate |
| `session_state_advanced.py` | **KEEP + FIX** | `state/session_state_advanced.py` | Unique: shopping list with add/remove/list tools. Good real-world example. Add docstring, banners, main gate |
| `dynamic_session_state.py` | **KEEP + FIX** | `state/dynamic_session_state.py` | Unique: tool-hook-driven customer profile state. Add docstring, banners |
| `session_state_multiple_users.py` | **KEEP + FIX** | `state/session_state_multiple_users.py` | Unique: multi-user state with `current_user_id`/`current_session_id`. Add docstring, banners |
| `session_state_in_event.py` | **KEEP + RENAME + FIX** | `state/session_state_events.py` | Unique: accessing state from RunCompletedEvent. Rename for clarity. Add docstring, banners, main gate |
| `manual_session_state_update.py` | **REWRITE** | `state/session_state_manual_update.py` | Merge with `overwrite_stored_session_state.py`. Show: manual updates between runs + overwriting stored state |
| `overwrite_stored_session_state.py` | **MERGE INTO** `state/session_state_manual_update.py` | — | Overwriting state — closely related to manual updates |
| `last_n_session_messages.py` | **MOVE + FIX** | `session/last_n_session_messages.py` | This searches session history by user — it's a session feature, not state management. Move to `session/` |

**Result: 12 → 7 files in `state/` (+ 1 moved to `session/`, making session 5 files)**

---

## 4. New Files Needed

These agent features lack cookbook coverage:

| Suggested File | Directory | Feature | Description |
|----------------|-----------|---------|-------------|
| `learning_machine.py` | `learning/` | LearningMachine | Demonstrate the unified learning system: agent learns from outcomes, retrieves learnings in context, continuous improvement |
| `basic_reasoning.py` | `reasoning/` | Extended Reasoning | Demonstrate step-by-step reasoning with configurable min/max steps, show_full_reasoning, and reasoning model selection |
| `agent_serialization.py` | `run_control/` | Agent save/load | Demonstrate `to_dict()`, `from_dict()`, `save()`, `load()` for agent persistence and configuration sharing |
| `concurrent_execution.py` | `run_control/` | asyncio.gather | (Moved from `async/gather_agents.py`) Concurrent agent execution with timing |
| `dynamic_tools.py` | `dependencies/` | Dynamic tool factories | Demonstrate callable factory functions that generate tools at runtime based on context |
| `tool_choice.py` | `run_control/` | Tool choice control | Demonstrate `tool_choice` parameter: "none", "auto", and specific tool enforcement |

---

## 5. Missing READMEs and TEST_LOGs

| Subdirectory | README.md | TEST_LOG.md |
|--------------|-----------|-------------|
| `02_agents/` (root) | EXISTS | **MISSING** |
| `agentic_search/` | MISSING | MISSING |
| `async/` | MISSING | MISSING |
| `caching/` | MISSING | MISSING |
| `context_compression/` | MISSING | MISSING |
| `context_management/` | MISSING | MISSING |
| `culture/` | EXISTS | **MISSING** |
| `custom_logging/` | MISSING | MISSING |
| `dependencies/` | EXISTS | **MISSING** |
| `events/` | MISSING | MISSING |
| `guardrails/` | MISSING | MISSING |
| `hooks/` | MISSING | MISSING |
| `human_in_the_loop/` | MISSING | MISSING |
| `input_and_output/` | MISSING | MISSING |
| `multimodal/` | MISSING | MISSING |
| `other/` | MISSING | MISSING |
| `rag/` | EXISTS | **MISSING** |
| `session/` | MISSING | MISSING |
| `skills/` | EXISTS | **MISSING** |
| `state/` | MISSING | MISSING |

**Summary:** 4/19 directories have README.md. 0/19 have TEST_LOG.md. Root has README.md but no TEST_LOG.md.

After restructuring, every surviving directory needs both files created.

---

## 6. Recommended Cookbook Template

Based on `cookbook/STYLE_GUIDE.md` and the best examples found during review.

### Template

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno's <specific API/feature>.

Key concepts:
- <concept 1>
- <concept 2>
"""

# ============================================================================
# Setup
# ============================================================================

from agno.agent import Agent
from agno.models.openai import OpenAIChat

# ============================================================================
# Agent Instructions
# ============================================================================

instructions = [
    "You are a helpful assistant.",
    "Respond concisely and accurately.",
]

# ============================================================================
# Create Agent
# ============================================================================

agent = Agent(
    name="Example Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=instructions,
)

# ============================================================================
# Run Agent
# ============================================================================

if __name__ == "__main__":
    # Sync usage
    agent.print_response("What is the capital of France?", stream=True)

    # Async usage (when demonstrating both patterns)
    # import asyncio
    # asyncio.run(agent.aprint_response("What is the capital of France?", stream=True))
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates and key concepts
2. **Section banners** — `# ============================================================================` with section name on next line
3. **Section flow** — Setup → Instructions (if applicable) → Create → Run
4. **Main gate** — All runnable code inside `if __name__ == "__main__":`
5. **No emoji** — No emoji characters anywhere in the file
6. **One feature** — Each file demonstrates exactly one capability
7. **Sync + async together** — Show both patterns in the same file when relevant, using sections
8. **Self-contained** — Each file must be independently runnable via `.venvs/demo/bin/python <path>`

### Best Current Examples (reference)

1. **`culture/01_create_cultural_knowledge.py`** — Best overall structure: clear docstring, step-by-step sections, well-commented, self-contained. Needs: standard banner format, main gate.
2. **`context_management/few_shot_learning.py`** — Clear docstring, proper main gate, focused on one feature (`additional_input`). Needs: section banners.
3. **`hooks/input_validation_pre_hook.py`** — Good docstring, substantial content showing real validation logic. Needs: section banners, main gate.
