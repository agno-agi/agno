# LearningMachine TODO

A checklist for reviewing, implementing, and testing the LearningMachine.

---

## Phase 1: Configs and Schemas

Review the files in order:

- [ ] Review `agno/learn/config.py` - Enums and configuration classes
- [ ] Review `agno/learn/schemas.py` - Schemas for each learning type


## Phase 2: Review and Test Stores

Review and test the stores in order:

- [ ] Review `agno/learn/stores/base.py` — Base store interface
- [ ] Review `agno/learn/stores/user_profile.py` — User memory storage and extraction (ported from MemoryManager)
- [ ] Run `cookbook/15_learning/stores/01_user_profile_store.py` to test the user profile store

... do the same for otehr stores
- [ ] Review `agno/learn/stores/session_context.py` — Session state storage and extraction (ported from SessionSummaryManager)
- [ ] Review `agno/learn/stores/knowledge.py` — Knowledge base wrapper for semantic search
- [ ] Review `agno/learn/machine.py` — Main `LearningMachine` class that orchestrates everything
- [ ] Review `agno/learn/__init__.py` — Public API exports

## Phase 3: Database Integration

- Review [filename]

## Phase 4: Test Cookbooks

- [ ] Review `agno/cookbook/learning/01_learning_machine.py` — Demo of 3 DX levels
- [ ] Review `agno/cookbook/learning/02_self_learning_research.py` — Research agent example

---

## Phase 2: Database Integration

### 2.1 Schema Updates (`agno/db/postgres/schemas.py`)

- [ ] Add `LEARNING_TABLE_SCHEMA` after `CULTURAL_KNOWLEDGE_TABLE_SCHEMA`
- [ ] Add `"learnings": LEARNING_TABLE_SCHEMA` to `get_table_schema_definition()` schemas dict

### 2.2 PostgresDb Class (`agno/db/postgres/postgres.py`)

#### Constructor Updates

- [ ] Add `learning_table: Optional[str] = None` parameter to `__init__`
- [ ] Add `self.learning_table_name = learning_table or "agno_learnings"` in `__init__` body

#### Table Method Updates

- [ ] Add `"learnings"` case to `_get_table()` method

#### Add Learning Methods

- [ ] Add `get_learning()` method
- [ ] Add `get_learnings()` method
- [ ] Add `upsert_learning()` method
- [ ] Add `delete_learning()` method
- [ ] Add `delete_learnings()` method
- [ ] Add `clear_learnings()` method

### 2.3 Database Test

- [ ] Run `python tests/test_05_database.py`
- [ ] Verify table creation works
- [ ] Verify upsert/get/delete operations work

---

## Phase 3: Agent Integration

### 3.1 Imports (`agno/agent/agent.py`)

- [ ] Add `TYPE_CHECKING` import block with `LearningMachine`

### 3.2 Class Attributes

- [ ] Add `learning: Optional[Union[bool, "LearningMachine"]] = None` attribute

### 3.3 Constructor (`__init__`)

- [ ] Add `learning` parameter to `__init__` signature
- [ ] Add learning initialization logic in `__init__` body

### 3.4 Tool Integration

- [ ] Add learning tools to `get_tools()` or `_determine_tools_for_model()`

### 3.5 System Prompt Integration

- [ ] Add `recall()` call in `get_system_message()`
- [ ] Add `format_recall_for_context()` output to system message
- [ ] Add `get_system_prompt_injection()` output to system message

### 3.6 Sync Run Integration (`_run`)

- [ ] Add `_start_learning_future()` helper method
- [ ] Start learning future after step 4 (memory_future)
- [ ] Wait for learning future in step 11

### 3.7 Async Run Integration (`_arun`)

- [ ] Add `_astart_learning_task()` helper method
- [ ] Start learning task after memory_task
- [ ] Wait for learning task before completion
- [ ] Cancel learning task in finally block

### 3.8 Agent Integration Test

- [ ] Run `python tests/test_06_integration.py`
- [ ] Verify agent creates with `learning=True`
- [ ] Verify agent creates with `LearningMachine` instance

---

## Phase 4: Testing

### 4.1 Unit Tests (Run in Order)

- [ ] `python tests/test_01_imports.py` — Verify all imports work
- [ ] `python tests/test_02_configs.py` — Verify config classes work
- [ ] `python tests/test_03_schemas.py` — Verify schemas work
- [ ] `python tests/test_04_machine.py` — Verify LearningMachine creation

### 4.2 Integration Tests

- [ ] `python tests/test_05_database.py` — Database methods work
- [ ] `python tests/test_06_integration.py` — Agent + LearningMachine work together

### 4.3 End-to-End Test

- [ ] `python tests/test_07_full_workflow.py` — Full multi-turn conversation test

### 4.4 Manual Testing

- [ ] Test Level 1 DX: `Agent(model=model, db=db, learning=True)`
- [ ] Test Level 2 DX: `Agent(model=model, db=db, learning=LearningMachine(...))`
- [ ] Test Level 3 DX: Full config with custom `UserProfileConfig`, `SessionContextConfig`, `KnowledgeConfig`
- [ ] Test user profile extraction across sessions
- [ ] Test session context extraction within session
- [ ] Test `save_user_memory` tool works
- [ ] Test recall injects context into system prompt

---

## Phase 5: Documentation

- [ ] Add docstrings to any missing methods
- [ ] Update agent documentation with `learning` parameter
- [ ] Add LearningMachine to main README or docs
- [ ] Document the three DX levels with examples

---

## Phase 6: Future Work (Phase 2+)

### Learned Knowledge with PROPOSE Mode

- [ ] Test PROPOSE mode workflow (agent proposes → user confirms → save)
- [ ] Test semantic search recall from knowledge base
- [ ] Verify `save_learning` tool works correctly

### Decision Logs (Phase 2)

- [ ] Implement `DecisionLogStore`
- [ ] Add `log_decision` tool
- [ ] Wire into LearningMachine

### Behavioral Feedback (Phase 2)

- [ ] Implement `FeedbackStore`
- [ ] Add feedback capture from UI signals
- [ ] Wire into LearningMachine

### Self-Improvement (Phase 4)

- [ ] Implement instruction update proposals
- [ ] Add HITL approval workflow
- [ ] Wire into LearningMachine

---

## Quick Reference

### File Locations

```
agno/learn/
├── __init__.py          # Public API
├── config.py            # Enums and configs
├── schemas.py           # Default schemas
├── machine.py           # LearningMachine class
├── db_additions.py      # DB reference (copy to postgres.py)
└── stores/
    ├── __init__.py      # Base interface
    ├── user_profile.py  # User memory store
    ├── session_context.py # Session state store
    └── knowledge.py     # Knowledge base store

agno/cookbook/learning/
├── 01_learning_machine.py      # DX demo
└── 02_self_learning_research.py # Research agent
```

### DX Levels

```python
# Level 1: Dead Simple
agent = Agent(model=model, db=db, learning=True)

# Level 2: Pick What You Want
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        knowledge=kb,
        user_profile=True,
        session_context=True,
        learned_knowledge=True,
    ),
)

# Level 3: Full Control
agent = Agent(
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        knowledge=kb,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            background=BackgroundConfig(timing=ExecutionTiming.PARALLEL),
            enable_tool=True,
        ),
        session_context=SessionContextConfig(enable_planning=True),
        learned_knowledge=KnowledgeConfig(mode=LearningMode.PROPOSE),
    ),
)
```

### Learning Types Summary

| Type | Scope | Mode | Tool | Description |
|------|-------|------|------|-------------|
| User Profile | USER | BACKGROUND | `save_user_memory` | Long-term user memories |
| Session Context | SESSION | BACKGROUND | None | Session state & summary |
| Learned Knowledge | KNOWLEDGE | PROPOSE | `save_learning` | Reusable insights (semantic search) |
| Decision Logs | AGENT | BACKGROUND | `log_decision` | Why decisions were made (Phase 2) |
| Behavioral Feedback | AGENT | BACKGROUND | None | What worked/didn't (Phase 2) |
| Self-Improvement | AGENT | HITL | None | Evolved instructions (Phase 4) |

---

## Notes

_Add implementation notes, gotchas, and decisions here as you work through the checklist._

-
-
-
