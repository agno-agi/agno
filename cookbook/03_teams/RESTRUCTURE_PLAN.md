# Restructuring Plan: `cookbook/03_teams/`

## 1. Executive Summary

### Current State

| Metric | Value |
|--------|-------|
| Subdirectories | 20 |
| Total `.py` files (non-`__init__`) | 101 |
| Fully style-compliant | 0 (~0%) |
| Have module docstring | ~80 (~79%) |
| Have section banners | 0 (0%) |
| Have `if __name__` gate | ~65 (~64%) |
| Contain emoji | ~4 (~4%) |
| Subdirectories with README.md | 17 / 20 |
| Subdirectories with TEST_LOG.md | 1 / 20 |

### Key Problems

1. **Sync/async duplication.** Eight confirmed duplication pairs across `async_flows/` ↔ `basic_flows/`, `streaming/`, `structured_input_output/`, `reasoning/`, and `context_compression/`. These should be consolidated into single files showing both patterns.

2. **Zero section banner compliance.** No file uses the `# ============================================================================` format required by STYLE_GUIDE.md. Docstring and main gate coverage are much better than `02_agents/` but still incomplete.

3. **Catch-all directory.** `other/` (10 files) mixes input formats, CLI apps, cancellation, retries, model inheritance, and few-shot learning — unrelated concerns that belong in their respective feature directories.

4. **Session parameter explosion.** `session/` has 12 files, many showing single-parameter toggles (cache, rename, in-memory, disable options). Similar to the pattern seen in `02_agents/session/`.

5. **Duplicate numbering.** `session/09_history_num_messages.py` and `session/09_share_session_with_agent.py` share the "09" prefix.

6. **Missing TEST_LOGs.** Only `human_in_the_loop/` has a TEST_LOG.md. 19/20 subdirectories are missing this required file.

### Overall Assessment

`03_teams/` is significantly better organized than `02_agents/`: higher docstring coverage (79% vs 41%), better main gate coverage (64% vs 32%), more README coverage (17/20 vs 4/19), and less extreme redundancy. The main issues are sync/async duplication, the `other/` catch-all, session bloat, and universal lack of section banners. Consolidation is less aggressive here — the target is ~74 files from 101 (~27% reduction).

### Proposed Target

| Metric | Current | Target |
|--------|---------|--------|
| Files | 101 | ~74 |
| Directories | 20 | 18 (remove async_flows, other; add run_control) |
| Style compliance | 0% | 100% |
| README coverage | 17/20 | 18/18 |
| TEST_LOG coverage | 1/20 | 18/18 |

---

## 2. Proposed Directory Structure

Remove `async_flows/` (merge into `basic_flows/`) and `other/` (dissolve and redistribute). Add `run_control/`.

```
cookbook/03_teams/
├── basic_flows/                # Core team coordination: modes, history, caching (absorbs async_flows/)
├── context_compression/        # Tool call result compression and token management
├── context_management/         # Instructions, context filtering, few-shot learning
├── dependencies/               # Runtime dependency injection for teams and members
├── distributed_rag/            # Distributed RAG with multiple retrieval agents
├── guardrails/                 # Safety: moderation, PII, prompt injection
├── hooks/                      # Pre/post-execution and stream hooks
├── human_in_the_loop/          # Confirmation, user input, external tool execution
├── knowledge/                  # Shared knowledge bases and retrieval strategies
├── memory/                     # Persistent memory and agentic memory
├── metrics/                    # Team performance monitoring
├── multimodal/                 # Image, audio, video processing with teams
├── reasoning/                  # Multi-agent reasoning and intelligent delegation
├── run_control/                # [NEW] Cancellation, retries, model config (from other/)
├── search_coordination/        # Coordinated search and RAG across agents
├── session/                    # Session persistence, history, and summaries
├── state/                      # Shared state management across team members
├── streaming/                  # Real-time response streaming and event monitoring
├── structured_input_output/    # Pydantic schemas, JSON output, parsing (absorbs input formats)
└── tools/                      # Custom tools, tool hooks, permission control
```

### Changes from Current

| Change | Details |
|--------|---------|
| **REMOVE** `async_flows/` | Dissolved. 3 files merge into their sync counterparts in `basic_flows/`. 1 unique file (concurrent members) moves to `basic_flows/`. |
| **REMOVE** `other/` | Dissolved. Files redistributed: few_shot→context_management, input formats→structured_input_output, cancel/retries→run_control, model_inheritance→run_control. CLI app and model_string cut. |
| **ADD** `run_control/` | Groups operational concerns from `other/`: cancellation, retries, model configuration. |

---

## 3. File Disposition Table

Dispositions: **KEEP** (good as-is), **KEEP + FIX** (needs style fixes), **MERGE INTO** (consolidate), **CUT** (remove), **REWRITE** (needs redo).

Style fixes needed on all files: add section banners. Many also need docstring and/or main gate additions.

---

### `async_flows/` → dissolve into `basic_flows/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_async_coordination_team.py` | **MERGE INTO** `basic_flows/01_basic_coordination.py` | — | Async variant of basic coordination. Merge sync+async into one file |
| `02_async_delegate_to_all_members.py` | **MERGE INTO** `basic_flows/03_delegate_to_all_members_cooperation.py` | — | Async variant of delegate-to-all. Merge into sync counterpart |
| `03_async_respond_directly.py` | **MERGE INTO** `basic_flows/02_respond_directly_router_team.py` | — | Async variant of router team. Merge into sync counterpart |
| `04_concurrent_member_agents.py` | **KEEP + MOVE + FIX** | `basic_flows/08_concurrent_member_agents.py` | Unique: concurrent member execution with event streaming and timing. No sync counterpart |

---

### `basic_flows/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_basic_coordination.py` | **REWRITE** | `basic_flows/01_basic_coordination.py` | Absorb async variant from `async_flows/01`. Add section banners, main gate |
| `02_respond_directly_router_team.py` | **REWRITE** | `basic_flows/02_respond_directly_router_team.py` | Absorb async variant from `async_flows/03`. Add banners, main gate |
| `03_delegate_to_all_members_cooperation.py` | **REWRITE** | `basic_flows/03_delegate_to_all_members.py` | Absorb async variant from `async_flows/02`. Shorten name. Add banners, main gate |
| `04_respond_directly_with_history.py` | **KEEP + FIX** | `basic_flows/04_respond_directly_with_history.py` | Unique: respond_directly + team history. Add docstring, banners, main gate |
| `05_team_history.py` | **KEEP + FIX** | `basic_flows/05_team_history.py` | Team-level shared history. Add docstring, banners, main gate |
| `06_history_of_members.py` | **KEEP + FIX** | `basic_flows/06_history_of_members.py` | Unique: member-specific history. Add docstring, banners, main gate |
| `07_share_member_interactions.py` | **KEEP + FIX** | `basic_flows/07_share_member_interactions.py` | Unique: share_member_interactions flag. Add docstring, banners, main gate |
| `caching/cache_team_response.py` | **KEEP + FIX** | `basic_flows/caching/cache_team_response.py` | Unique: two-layer caching. Add banners, main gate |

**Result: 8 basic_flows + 4 async_flows = 12 total → 9 files**

---

### `context_compression/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `tool_call_compression.py` | **REWRITE** | `context_compression/tool_call_compression.py` | Merge sync + async into one file showing both patterns. Add docstring, banners |
| `async_tool_call_compression.py` | **MERGE INTO** `tool_call_compression.py` | — | Async variant; only adds `asyncio.run()` wrapper |
| `tool_call_compression_with_manager.py` | **KEEP + FIX** | `context_compression/tool_call_compression_with_manager.py` | Unique: CompressionManager for custom compression. Add banners |

**Result: 3 → 2 files**

---

### `context_management/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `filter_tool_calls_from_history.py` | **KEEP + FIX** | `context_management/filter_tool_calls_from_history.py` | Unique: max_tool_calls_from_history. Add banners |
| `introduction.py` | **KEEP + FIX** | `context_management/introduction.py` | Unique: team introduction parameter. Add banners, main gate |

**Also add** `other/few_shot_learning.py` → **MOVE** to `context_management/few_shot_learning.py` (few-shot learning via additional_input belongs here)

**Result: 2 → 3 files (+ 1 moved in)**

---

### `dependencies/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `access_dependencies_in_tool.py` | **REWRITE** | `dependencies/dependencies_in_tools.py` | Merge with `add_dependencies_on_run.py`. Show: declaring deps, passing at runtime, accessing in tools |
| `add_dependencies_on_run.py` | **MERGE INTO** `dependencies/dependencies_in_tools.py` | — | Runtime dep injection — same concept as tool access |
| `add_dependencies_to_context.py` | **REWRITE** | `dependencies/dependencies_in_context.py` | Merge with `reference_dependencies.py`. Show: deps in team context + referencing in instructions. Fix emoji |
| `add_dependencies_to_member_context.py` | **KEEP + FIX** | `dependencies/dependencies_to_members.py` | Unique team feature: passing deps to member agents. Rename for clarity. Add banners, main gate |
| `reference_dependencies.py` | **MERGE INTO** `dependencies/dependencies_in_context.py` | — | Referencing deps in instructions — same concept as context deps |

**Result: 5 → 3 files**

---

### `distributed_rag/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_distributed_rag_pgvector.py` | **KEEP + FIX** | `distributed_rag/01_distributed_rag_pgvector.py` | Core: multi-agent RAG with pgvector. Add banners |
| `02_distributed_rag_lancedb.py` | **KEEP + FIX** | `distributed_rag/02_distributed_rag_lancedb.py` | Unique: LanceDB variant with different agent roles. Fix emoji. Add banners |
| `03_distributed_rag_with_reranking.py` | **KEEP + FIX** | `distributed_rag/03_distributed_rag_with_reranking.py` | Unique: Cohere reranking across distributed agents. Add banners |

**Result: 3 → 3 files (no change, all unique RAG architectures)**

---

### `guardrails/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `openai_moderation.py` | **KEEP + FIX** | `guardrails/openai_moderation.py` | Unique: OpenAI moderation on teams. Add banners |
| `pii_detection.py` | **KEEP + FIX** | `guardrails/pii_detection.py` | Unique: PII detection on teams. Add banners |
| `prompt_injection.py` | **KEEP + FIX** | `guardrails/prompt_injection.py` | Unique: prompt injection guard on teams. Add banners |

**Result: 3 → 3 files (no change)**

---

### `hooks/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `input_validation_pre_hook.py` | **REWRITE** | `hooks/pre_hook_input.py` | Merge with `input_transformation_pre_hook.py`. Show both validation (reject) and transformation (modify) |
| `input_transformation_pre_hook.py` | **MERGE INTO** `hooks/pre_hook_input.py` | — | Input transformation — closely related to validation |
| `output_validation_post_hook.py` | **REWRITE** | `hooks/post_hook_output.py` | Merge with `output_transformation_post_hook.py`. Show both validation and transformation |
| `output_transformation_post_hook.py` | **MERGE INTO** `hooks/post_hook_output.py` | — | Output transformation — closely related to validation |
| `output_stream_hook_send_notification.py` | **KEEP + RENAME + FIX** | `hooks/stream_hook.py` | Unique: stream-phase hooks. Rename for clarity. Add banners |

**Result: 5 → 3 files**

---

### `human_in_the_loop/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `confirmation_required.py` | **KEEP + FIX** | `human_in_the_loop/confirmation_required.py` | Unique: tool confirmation for teams. Add banners |
| `external_tool_execution.py` | **KEEP + FIX** | `human_in_the_loop/external_tool_execution.py` | Unique: external tool execution for teams. Add banners |
| `user_input_required.py` | **KEEP + FIX** | `human_in_the_loop/user_input_required.py` | Unique: user input collection for teams. Add banners |

**Result: 3 → 3 files (no change, already lean — good example for 02_agents to follow)**

---

### `knowledge/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_team_with_knowledge.py` | **KEEP + FIX** | `knowledge/01_team_with_knowledge.py` | Core: team with knowledge base. Add banners |
| `02_team_with_knowledge_filters.py` | **KEEP + FIX** | `knowledge/02_team_with_knowledge_filters.py` | Unique: static knowledge filters. Add banners |
| `03_team_with_agentic_knowledge_filters.py` | **KEEP + FIX** | `knowledge/03_team_with_agentic_knowledge_filters.py` | Unique: AI-determined dynamic filters. Add banners |
| `04_team_with_custom_retriever_dependencies.py` | **KEEP + FIX** | `knowledge/04_team_with_custom_retriever.py` | Unique: custom retriever with runtime deps. Shorten name. Add banners |

**Result: 4 → 4 files (no change)**

---

### `memory/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_team_with_memory_manager.py` | **KEEP + FIX** | `memory/01_team_with_memory_manager.py` | Core: MemoryManager for teams. Add banners |
| `02_team_with_agentic_memory.py` | **KEEP + FIX** | `memory/02_team_with_agentic_memory.py` | Unique: AI-driven memory. Add banners |

**Result: 2 → 2 files (no change)**

---

### `metrics/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_team_metrics.py` | **KEEP + FIX** | `metrics/01_team_metrics.py` | Unique: comprehensive team metrics. Add banners |

**Result: 1 → 1 file (no change)**

---

### `multimodal/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `audio_sentiment_analysis.py` | **KEEP + FIX** | `multimodal/audio_sentiment_analysis.py` | Unique: team-based audio sentiment. Add banners |
| `audio_to_text.py` | **KEEP + FIX** | `multimodal/audio_to_text.py` | Unique: team audio transcription. Add banners |
| `generate_image_with_team.py` | **KEEP + FIX** | `multimodal/generate_image_with_team.py` | Unique: team DALL-E generation. Add banners |
| `image_to_image_transformation.py` | **KEEP + FIX** | `multimodal/image_to_image_transformation.py` | Unique: team image transformation. Add banners |
| `image_to_structured_output.py` | **KEEP + FIX** | `multimodal/image_to_structured_output.py` | Unique: team vision + structured output. Add banners |
| `image_to_text.py` | **KEEP + FIX** | `multimodal/image_to_text.py` | Core: team image analysis. Add banners, main gate |
| `media_input_for_tool.py` | **KEEP + FIX** | `multimodal/media_input_for_tool.py` | Unique: tools accessing uploaded media. Add banners |
| `video_caption_generation.py` | **KEEP + FIX** | `multimodal/video_caption_generation.py` | Unique: team video captioning. Add banners |

**Result: 8 → 8 files (no change, all distinct multimodal patterns)**

---

### `other/` → dissolve

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `few_shot_learning.py` | **MOVE + FIX** | `context_management/few_shot_learning.py` | Few-shot learning via additional_input belongs in context_management. Fix emoji. Add banners |
| `input_as_dict.py` | **REWRITE** | `structured_input_output/input_formats.py` | Merge all 3 input format files into one. Show dict, list, and messages_list |
| `input_as_list.py` | **MERGE INTO** `structured_input_output/input_formats.py` | — | List input — trivial variant of dict input |
| `input_as_messages_list.py` | **MERGE INTO** `structured_input_output/input_formats.py` | — | Messages list — trivial variant |
| `response_as_variable.py` | **MOVE + FIX** | `structured_input_output/response_as_variable.py` | Structured response capture belongs in structured_input_output. Add banners |
| `run_as_cli.py` | **CUT** | — | Full interactive CLI app. Not a minimal feature demo — it's a showcase. Contains emoji |
| `team_cancel_a_run.py` | **MOVE + FIX** | `run_control/cancel_run.py` | Run cancellation belongs with operational concerns. Add banners |
| `team_model_inheritance.py` | **MOVE + FIX** | `run_control/model_inheritance.py` | Model inheritance is a configuration concern. Add banners |
| `team_model_string.py` | **CUT** | — | 31 lines. Using `model="provider:id"` string format is trivial, documented in README |
| `team_retries.py` | **MOVE + FIX** | `run_control/retries.py` | Retry configuration belongs with operational concerns. Add banners |

**Result: 10 → 0 files (dissolved); creates `run_control/` with 3 files, adds to context_management and structured_input_output**

---

### `reasoning/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_reasoning_multi_purpose_team.py` | **REWRITE** | `reasoning/reasoning_multi_purpose_team.py` | Merge sync + async into one file. Drop number prefix. Add banners |
| `02_async_multi_purpose_reasoning_team.py` | **MERGE INTO** `reasoning/reasoning_multi_purpose_team.py` | — | Async variant of the same multi-purpose reasoning team |

**Result: 2 → 1 file**

---

### `search_coordination/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_coordinated_agentic_rag.py` | **KEEP + FIX** | `search_coordination/01_coordinated_agentic_rag.py` | Core: coordinated RAG search. Add banners |
| `02_coordinated_reasoning_rag.py` | **KEEP + FIX** | `search_coordination/02_coordinated_reasoning_rag.py` | Unique: reasoning + RAG coordination. Add banners |
| `03_distributed_infinity_search.py` | **KEEP + FIX** | `search_coordination/03_distributed_infinity_search.py` | Unique: Infinity reranker in distributed search. Add banners |

**Result: 3 → 3 files (no change)**

---

### `session/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_persistent_session.py` | **REWRITE** | `session/persistent_session.py` | Merge with 02. Show: basic persistence + history. Drop number prefix. Add docstring, banners, main gate |
| `02_persistent_session_history.py` | **MERGE INTO** `session/persistent_session.py` | — | Adding `add_history_to_context` is one parameter |
| `03_session_summary.py` | **REWRITE** | `session/session_summary.py` | Merge with 04 (references), 10 (async), 11 (search). Show all summary features. Drop prefix |
| `04_session_summary_references.py` | **MERGE INTO** `session/session_summary.py` | — | Adding references is one parameter variation |
| `05_chat_history.py` | **REWRITE** | `session/chat_history.py` | Merge with 09_history_num_messages. Show: reading history + limiting. Drop prefix. Add docstring, banners, main gate |
| `06_rename_session.py` | **REWRITE** | `session/session_options.py` | Merge with 07, 08. Show: rename, in-memory DB, cache. Drop prefix |
| `07_in_memory_db.py` | **MERGE INTO** `session/session_options.py` | — | In-memory DB is a configuration option |
| `08_cache_session.py` | **MERGE INTO** `session/session_options.py` | — | Cache toggle is a configuration option |
| `09_history_num_messages.py` | **MERGE INTO** `session/chat_history.py` | — | Limiting messages is part of chat history management |
| `09_share_session_with_agent.py` | **KEEP + RENAME + FIX** | `session/share_session_with_agent.py` | Unique team feature: sharing sessions between Agent and Team. Drop duplicate "09" prefix. Add banners |
| `10_async_session_summary.py` | **MERGE INTO** `session/session_summary.py` | — | Async summary — same feature, different execution mode |
| `11_search_session_history.py` | **KEEP + RENAME + FIX** | `session/search_session_history.py` | Unique: full-text session search. Drop prefix. Add docstring, banners |

**Result: 12 → 6 files**

---

### `state/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `agentic_session_state.py` | **KEEP + FIX** | `state/agentic_session_state.py` | Unique: LLM-managed state for teams. Add docstring, banners, main gate |
| `change_state_on_run.py` | **KEEP + FIX** | `state/change_state_on_run.py` | Unique: per-run state modification. Add docstring, banners, main gate |
| `overwrite_stored_session_state.py` | **KEEP + FIX** | `state/overwrite_stored_session_state.py` | Unique: state replacement strategy. Add banners, main gate |
| `pass_state_to_members.py` | **REWRITE** | `state/state_sharing.py` | Merge with `share_member_interactions.py`. Both demonstrate state/context sharing across members |
| `share_member_interactions.py` | **MERGE INTO** `state/state_sharing.py` | — | Sharing member interactions — closely related to passing state to members |
| `team_with_nested_shared_state.py` | **KEEP + FIX** | `state/nested_shared_state.py` | Unique: complex nested team hierarchy with shared state. Rename for clarity. Add banners, main gate |

**Result: 6 → 5 files**

---

### `streaming/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_team_streaming.py` | **REWRITE** | `streaming/team_streaming.py` | Merge with async variant (03). Show sync + async streaming. Drop prefix. Add banners, main gate |
| `02_events.py` | **REWRITE** | `streaming/team_events.py` | Merge with async variant (04). Show sync + async event monitoring. Rename for clarity. Add docstring, banners |
| `03_async_team_streaming.py` | **MERGE INTO** `streaming/team_streaming.py` | — | Async variant of basic streaming |
| `04_async_team_events.py` | **MERGE INTO** `streaming/team_events.py` | — | Async variant of event monitoring |

**Result: 4 → 2 files**

---

### `structured_input_output/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `00_pydantic_model_output.py` | **KEEP + RENAME + FIX** | `structured_input_output/pydantic_output.py` | Core: Pydantic output schema. Drop prefix. Add docstring, banners, main gate |
| `01_pydantic_model_as_input.py` | **KEEP + RENAME + FIX** | `structured_input_output/pydantic_input.py` | Unique: Pydantic model as input. Drop prefix. Add banners, main gate |
| `02_team_with_parser_model.py` | **KEEP + RENAME + FIX** | `structured_input_output/parser_model.py` | Unique: parser model for teams. Drop prefix. Add docstring, banners, main gate |
| `03_team_with_output_model.py` | **KEEP + RENAME + FIX** | `structured_input_output/output_model.py` | Unique: output_model parameter. Drop prefix. Add banners, main gate |
| `04_structured_output_streaming.py` | **REWRITE** | `structured_input_output/structured_output_streaming.py` | Merge with async variant (05). Show sync + async. Drop prefix. Add docstring, banners |
| `05_async_structured_output_streaming.py` | **MERGE INTO** `structured_output_streaming.py` | — | Async variant of structured streaming |
| `06_input_schema_on_team.py` | **KEEP + RENAME + FIX** | `structured_input_output/input_schema.py` | Unique: team-level input validation. Drop prefix. Add banners, main gate |
| `07_output_schema_override.py` | **KEEP + RENAME + FIX** | `structured_input_output/output_schema_override.py` | Unique: dynamic schema override. Drop prefix. Add banners |
| `08_json_schema_output.py` | **KEEP + RENAME + FIX** | `structured_input_output/json_schema_output.py` | Unique: JSON schema (non-Pydantic). Drop prefix. Add docstring, banners, main gate |

**Plus from `other/`:**

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `input_as_dict.py` + `input_as_list.py` + `input_as_messages_list.py` | **REWRITE** | `structured_input_output/input_formats.py` | Merge 3 input format files from other/ |
| `response_as_variable.py` | **MOVE + FIX** | `structured_input_output/response_as_variable.py` | From other/. Add banners |

**Result: 9 structured + 4 from other = 13 total → 10 files**

---

### `tools/`

| File | Disposition | New Name/Location | Rationale |
|------|------------|-------------------|-----------|
| `01_team_with_custom_tools.py` | **KEEP + RENAME + FIX** | `tools/custom_tools.py` | Core: custom tool definitions. Drop prefix. Add banners, main gate |
| `02_team_with_tool_hooks.py` | **KEEP + RENAME + FIX** | `tools/tool_hooks.py` | Unique: tool execution hooks. Drop prefix. Add banners |
| `03_async_team_with_tools.py` | **KEEP + RENAME + FIX** | `tools/async_tools.py` | Unique: async tool execution with multiple tool types. Drop prefix. Add banners |
| `04_tool_hooks_for_members.py` | **KEEP + RENAME + FIX** | `tools/member_tool_hooks.py` | Unique: permission-based tool access per member. Drop prefix. Add banners |

**Result: 4 → 4 files (no change, just rename)**

---

## 4. New Files Needed

Based on the team capabilities analysis, these features lack cookbook examples:

| Suggested File | Directory | Feature | Description |
|----------------|-----------|---------|-------------|
| `task_mode.py` | `basic_flows/` | `mode=TeamMode.tasks` | Demonstrate autonomous task-based execution where team decomposes goals into a shared task list with dependencies |
| `broadcast_mode.py` | `basic_flows/` | `mode=TeamMode.broadcast` | Demonstrate broadcast mode where the same task is delegated to all members simultaneously |
| `learning_machine.py` | `memory/` | Learning | Demonstrate team-level learning from outcomes via LearningMachine |
| `remote_team.py` | `run_control/` | RemoteTeam | Demonstrate executing teams remotely via AgentOS or A2A protocol |
| `nested_teams.py` | `basic_flows/` | Teams of teams | Demonstrate team hierarchy: teams containing other teams as members |

---

## 5. Missing READMEs and TEST_LOGs

| Subdirectory | README.md | TEST_LOG.md |
|--------------|-----------|-------------|
| `03_teams/` (root) | EXISTS | **MISSING** |
| `async_flows/` | EXISTS | **MISSING** |
| `basic_flows/` | EXISTS | **MISSING** |
| `context_compression/` | **MISSING** | **MISSING** |
| `context_management/` | **MISSING** | **MISSING** |
| `dependencies/` | EXISTS | **MISSING** |
| `distributed_rag/` | EXISTS | **MISSING** |
| `guardrails/` | **MISSING** | **MISSING** |
| `hooks/` | **MISSING** | **MISSING** |
| `human_in_the_loop/` | EXISTS | EXISTS |
| `knowledge/` | EXISTS | **MISSING** |
| `memory/` | EXISTS | **MISSING** |
| `metrics/` | EXISTS | **MISSING** |
| `multimodal/` | EXISTS | **MISSING** |
| `other/` | EXISTS | **MISSING** |
| `reasoning/` | EXISTS | **MISSING** |
| `search_coordination/` | EXISTS | **MISSING** |
| `session/` | EXISTS | **MISSING** |
| `state/` | EXISTS | **MISSING** |
| `streaming/` | EXISTS | **MISSING** |
| `structured_input_output/` | EXISTS | **MISSING** |
| `tools/` | EXISTS | **MISSING** |

**Summary:** 17/20 directories have README.md. 1/20 has TEST_LOG.md. After restructuring, every surviving directory needs both files created.

---

## 6. Recommended Cookbook Template

Same template as `02_agents/RESTRUCTURE_PLAN.md` — teams follow the same STYLE_GUIDE.md.

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno Teams.

Key concepts:
- <concept 1>
- <concept 2>
"""

# ============================================================================
# Setup
# ============================================================================

from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat

# ============================================================================
# Create Members
# ============================================================================

researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o"),
    role="Research and gather information",
)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o"),
    role="Write clear summaries",
)

# ============================================================================
# Create Team
# ============================================================================

team = Team(
    name="Research Team",
    members=[researcher, writer],
    model=OpenAIChat(id="gpt-4o"),
)

# ============================================================================
# Run Team
# ============================================================================

if __name__ == "__main__":
    # Sync usage
    team.print_response("What are the latest trends in AI?", stream=True)

    # Async usage (when demonstrating both patterns)
    # import asyncio
    # asyncio.run(team.aprint_response("What are the latest trends in AI?", stream=True))
```

### Template Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates and key concepts
2. **Section banners** — `# ============================================================================` with section name on next line
3. **Section flow** — Setup → Create Members → Create Team → Run Team
4. **Main gate** — All runnable code inside `if __name__ == "__main__":`
5. **No emoji** — No emoji characters anywhere
6. **One feature** — Each file demonstrates exactly one team capability
7. **Sync + async together** — Show both patterns in sections when relevant
8. **Self-contained** — Each file independently runnable via `.venvs/demo/bin/python <path>`

### Best Current Examples (reference)

1. **`human_in_the_loop/confirmation_required.py`** — Clean, focused, has docstring and main gate. The only directory with both README.md and TEST_LOG.md. Needs: section banners.
2. **`knowledge/01_team_with_knowledge.py`** — Good docstring, focused on one feature, has main gate. Needs: section banners.
3. **`metrics/01_team_metrics.py`** — Comprehensive yet focused. Good docstring explaining what metrics are tracked. Needs: section banners.
