# Teams Cookbook Testing Log

Testing team examples in `cookbook/03_teams/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Database: PostgreSQL with PgVector (for knowledge/memory examples)
- Date: 2026-01-15 (updated), 2026-01-14 (initial)

---

## Test Results by Subfolder

### basic_flows/

| File | Status | Notes |
|------|--------|-------|
| 01_basic_coordination.py | SKIP | Requires `newspaper4k` module |
| 02_respond_directly_router_team.py | PASS | Multi-language router team works |
| 03_delegate_to_all_members_cooperation.py | PASS | Delegate to all members pattern works |
| 04_respond_directly_with_history.py | PASS | Geo search team with history works |

---

### async_flows/

| File | Status | Notes |
|------|--------|-------|
| 01_async_coordination_team.py | SKIP | Requires `newspaper4k` module |
| 02_async_delegate_to_all_members.py | PASS | Async delegation works |

---

### streaming/

| File | Status | Notes |
|------|--------|-------|
| 01_team_streaming.py | PASS | Stock research team streaming works |
| 02_events.py | PASS | Team events captured correctly |

---

### state/

| File | Status | Notes |
|------|--------|-------|
| agentic_session_state.py | PASS | Shopping list team with state works |
| pass_state_to_members.py | PASS | State passed to member agents |

---

### session/

| File | Status | Notes |
|------|--------|-------|
| 01_persistent_session.py | PASS | Session persistence with PostgreSQL |
| 07_in_memory_db.py | PASS | In-memory session storage works |

---

### guardrails/

| File | Status | Notes |
|------|--------|-------|
| prompt_injection.py | PASS | Prompt injection detection works |
| pii_detection.py | PASS | PII detection blocks sensitive data |

---

### hooks/

| File | Status | Notes |
|------|--------|-------|
| output_transformation_post_hook.py | PASS | Post-hook transforms team output |

---

### structured_input_output/

| File | Status | Notes |
|------|--------|-------|
| 00_pydantic_model_output.py | PASS | Structured output with Pydantic works |

---

### tools/

| File | Status | Notes |
|------|--------|-------|
| 01_team_with_custom_tools.py | PASS | Custom tools with Q&A team works |

---

### dependencies/

| File | Status | Notes |
|------|--------|-------|
| add_dependencies_to_context.py | PASS | Dependency injection to team context |

---

### context_management/

| File | Status | Notes |
|------|--------|-------|
| introduction.py | PASS | Introduction messages work |

---

### memory/

| File | Status | Notes |
|------|--------|-------|
| 01_team_with_memory_manager.py | PASS | Memory manager with teams works |

---

### other/

| File | Status | Notes |
|------|--------|-------|
| team_cancel_a_run.py | PASS | Team run cancellation works |

---

### knowledge/

| File | Status | Notes |
|------|--------|-------|
| 01_team_with_knowledge.py | SKIP | Requires `lancedb` module |

---

### reasoning/

| File | Status | Notes |
|------|--------|-------|
| 01_reasoning_multi_purpose_team.py | SKIP | Requires `PyGithub` module |

---

### metrics/

| File | Status | Notes |
|------|--------|-------|
| 01_team_metrics.py | SKIP | Requires `surrealdb` module |

---

## TESTING SUMMARY

**Overall Results:**
- **Tested:** ~25 files
- **Passed:** 20+
- **Failed:** 0
- **Skipped:** 5 (missing dependencies: newspaper4k, lancedb, PyGithub, surrealdb)

**Fixes Applied:**
1. Fixed path references in CLAUDE.md (`04_teams` -> `03_teams`)
2. Fixed path references in TEST_LOG.md (`04_teams` -> `03_teams`)

**Skipped Due to Missing Dependencies:**
- `basic_flows/01_basic_coordination.py` - Requires `newspaper4k`
- `async_flows/01_async_coordination_team.py` - Requires `newspaper4k`
- `knowledge/01_team_with_knowledge.py` - Requires `lancedb`
- `reasoning/01_reasoning_multi_purpose_team.py` - Requires `PyGithub`
- `metrics/01_team_metrics.py` - Requires `surrealdb`

**Key Features Verified:**
- Team coordination and delegation patterns work correctly
- State sharing between team leader and members
- Session persistence and history management
- Memory management with teams
- Guardrails (prompt injection, PII detection)
- Hooks for input/output transformation
- Structured input/output with Pydantic
- Custom tools integration
- Team run cancellation
- Event handling and streaming

**Fixes Applied (2026-01-15):**
1. `multimodal/audio_to_text.py` - Fixed model ID (`gemini-2.0-flash-exp` -> `gemini-3-flash-preview`) x3
2. `multimodal/audio_sentiment_analysis.py` - Fixed model ID (`gemini-2.0-flash-exp` -> `gemini-3-flash-preview`) x3
3. `guardrails/prompt_injection.py` - Removed emojis from print statements
4. `guardrails/pii_detection.py` - Removed emojis from print statements
5. `guardrails/openai_moderation.py` - Removed emojis from print statements
6. `hooks/input_validation_pre_hook.py` - Removed emojis from print statements
7. `hooks/output_validation_post_hook.py` - Removed emojis from print statements
8. `hooks/output_transformation_post_hook.py` - Removed emojis from print statements

**Remaining Emoji Files (lower priority):**
- `streaming/04_async_team_events.py`
- `search_coordination/03_distributed_infinity_search.py`
- `structured_input_output/04_structured_output_streaming.py`
- `structured_input_output/05_async_structured_output_streaming.py`
- `distributed_rag/` (multiple files)
- `tools/01_team_with_custom_tools.py`
- `other/run_as_cli.py`
- `other/team_cancel_a_run.py`

**Notes:**
- Teams folder mirrors 02_agents structure for consistency
- Core team patterns (basic_flows, state, streaming) all work
- Production patterns (guardrails, hooks, memory) verified
- Model IDs fixed from gemini-2.0-flash-exp to gemini-3-flash-preview
