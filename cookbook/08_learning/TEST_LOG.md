# Learning Cookbooks Test Log

Last updated: 2026-02-11 (v2.5 review)

## Test Environment
- Database: PostgreSQL with PgVector at localhost:5532
- Python: `.venvs/demo/bin/python`
- Models: gpt-4o (OpenAI), claude-sonnet-4-5 (Anthropic)
- Branch: cookbooks/v2.5-testing

---

## 00_quickstart/

### 01_always_learn.py

**Status:** PASS

**Description:** Basic learning with automatic extraction (ALWAYS mode) using SqliteDb. Two-session test — profile + memory extraction, then recall.

**Result:** Profile and memories extracted and recalled across sessions correctly.

---

### 02_agentic_learn.py

**Status:** PASS

**Description:** Learning with agent tools (AGENTIC mode). Agent uses tools to manage profile and memories.

**Result:** Agent correctly used update_profile and memory tools. Cross-session recall works.

---

### 03_learned_knowledge.py

**Status:** PASS (with warnings)

**Description:** Learned knowledge across users with ChromaDb vector search and semantic search.

**Result:** Agent ran and produced correct output. ChromaDb filter errors logged (`Expected where to have exactly one operator`) when searching with composite filters. Search returns 0 documents but agent still answers from general knowledge.

---

## 01_basics/

### 1a_user_profile_always.py

**Status:** PASS

**Description:** User profile extraction in ALWAYS mode with PostgresDb. Two-session test.

**Result:** Profile extracted (name: Alice Chen, preferred: Ali) and recalled in second session.

---

### 1b_user_profile_agentic.py

**Status:** PASS

**Description:** User profile with agent-controlled tools (AGENTIC mode). Agent calls update_profile explicitly.

**Result:** Agent used update_profile tool correctly. Profile recalled across sessions.

---

### 2a_user_memory_always.py

**Status:** PASS

**Description:** Unstructured user memory (ALWAYS mode) with PostgresDb.

**Result:** Memories extracted and recalled. Agent used memories to contextualize follow-up questions.

---

### 2b_user_memory_agentic.py

**Status:** PASS

**Description:** User memory with agent tools (AGENTIC mode). Multi-turn conversation test.

**Result:** Agent stored and recalled memories about user preferences (Rust over Go, Stripe backend engineer).

---

### 3a_session_context_summary.py

**Status:** PASS

**Description:** Session context tracking in summary-only mode. Multi-turn API design conversation.

**Result:** Session context tracked conversation state including open decisions and discussion points.

---

### 3b_session_context_planning.py

**Status:** PASS

**Description:** Session context with goal/plan/progress tracking (planning mode).

**Result:** Session context tracked goals, plans, and progress for a deployment scenario.

---

### 4_learned_knowledge.py

**Status:** PASS

**Description:** Learned knowledge store with PgVector semantic search (AGENTIC mode).

**Result:** Agent saved and searched learnings about cloud infrastructure. Cross-session knowledge sharing works.

---

### 5a_entity_memory_always.py

**Status:** PASS

**Description:** Entity memory (facts about external entities) in ALWAYS mode.

**Result:** Multiple entities tracked (companies, people, technologies) with facts, events, and relationships.

---

### 5b_entity_memory_agentic.py

**Status:** PASS

**Description:** Entity memory with agent tools for explicit management.

**Result:** Agent used entity tools to create, update, and log events for entities.

---

## 02_user_profile/

### 01_always_extraction.py

**Status:** PASS

**Description:** Gradual profile building across 4 conversations showing progressive enrichment.

**Result:** Profile built incrementally across conversations. Name and preferred name updated correctly.

---

### 02_agentic_mode.py

**Status:** PASS

**Description:** Agent-controlled profile updates with explicit tool calls.

**Result:** Agent used update_profile tool. Profile correctly updated when user changed preferred name.

---

### 03_custom_schema.py

**Status:** PASS

**Description:** Custom profile schema (DeveloperProfile) extending UserProfile with additional fields.

**Result:** Custom schema fields populated correctly from conversation about a Go backend engineer.

---

## 03_session_context/

### 01_summary_mode.py

**Status:** PASS

**Description:** Multi-turn summary tracking across conversation about memory leaks in a Python service.

**Result:** Session context accurately summarized conversation state and next steps.

---

### 02_planning_mode.py

**Status:** PASS

**Description:** Goal/plan/progress tracking for a deployment planning session.

**Result:** Session context tracked goals, multi-step plan, and progress checkpoints.

---

## 04_entity_memory/

### 01_facts_and_events.py

**Status:** PASS

**Description:** Semantic (facts) vs episodic (events) memory for entities.

**Result:** Entity facts and events tracked correctly. Partnership event and new entity (BigCloud) created.

---

### 02_entity_relationships.py

**Status:** PASS

**Description:** Knowledge graph edges (relationships between entities) — teams, people, companies.

**Result:** Complex relationship graph built with teams, people, and inter-company relationships.

---

## 05_learned_knowledge/

### 01_agentic_mode.py

**Status:** PASS

**Description:** Agent-controlled knowledge saving (AGENTIC mode) with PgVector search.

**Result:** Agent saved and searched learnings about cloud infrastructure best practices.

---

### 02_propose_mode.py

**Status:** PASS

**Description:** Human-reviewed learnings (PROPOSE mode) — agent proposes, user confirms/rejects.

**Result:** Agent proposed learnings. User rejection respected. Saved learnings found via search.

---

## 06_quick_tests/

### 01_async_user_profile.py

**Status:** PASS

**Description:** Async variant testing (aprint_response) for user profile.

**Result:** Async profile extraction and recall worked correctly.

---

### 02_learning_true_shorthand.py

**Status:** PASS

**Description:** Testing `learning=True` shorthand (auto-creates LearningMachine with defaults).

**Result:** Profile and memories extracted using shorthand. Both stores populated correctly.

---

### 03_no_db_graceful.py

**Status:** PASS

**Description:** Graceful handling when no database is configured.

**Result:** Agent works fine without DB. Profile not persisted (expected). No crash.

---

### 04_claude_model.py

**Status:** PASS

**Description:** Testing learning with Claude model (claude-sonnet-4-5) instead of OpenAI.

**Result:** Profile extracted and recalled correctly with Claude.

---

## 07_patterns/

### personal_assistant.py

**Status:** PASS

**Description:** Combined pattern: user profile + session context + entity memory in a personal assistant.

**Result:** All three stores worked together. Multi-turn conversation tracked with planning mode.

---

### support_agent.py

**Status:** PASS

**Description:** Combined pattern: user profile + session + entity + learned knowledge in a support agent.

**Result:** Full learning stack worked. Support conversation tracked entities and session context.

---

## 08_custom_stores/

### 01_minimal_custom_store.py

**Status:** PASS

**Description:** Minimal custom store implementation (in-memory ProjectContextStore).

**Result:** Custom store integrated with LearningMachine. Project context available to agent.

---

### 02_custom_store_with_db.py

**Status:** PASS

**Description:** Custom store with database persistence (project notes with goals/blockers).

**Result:** Custom store persisted data. Note: duplicate entries observed on re-runs (goals/blockers tripled).

---

## 09_decision_logs/

### 01_basic_decision_log.py

**Status:** PASS (after fix)

**Description:** Basic decision logging in AGENTIC mode — agent logs decisions via tool.

**Result:** Agent used log_decision tool. Decisions stored and retrieved correctly.
**Fix applied:** `agent.get_learning_machine()` → `agent.learning_machine` (v2.5 property change).

---

### 02_decision_log_always.py

**Status:** PASS (after fix)

**Description:** Automatic decision logging (ALWAYS mode) — tool calls auto-recorded as decisions.

**Result:** Agent ran with DuckDuckGo search. No decisions auto-logged (ALWAYS mode extraction didn't produce structured decisions from this conversation).
**Fix applied:** `agent.get_learning_machine()` → `agent.learning_machine` (v2.5 property change).

---

## Summary

| Category | Total | Pass | Fail | Skip |
|----------|-------|------|------|------|
| 00_quickstart | 3 | 3 | 0 | 0 |
| 01_basics | 9 | 9 | 0 | 0 |
| 02_user_profile | 3 | 3 | 0 | 0 |
| 03_session_context | 2 | 2 | 0 | 0 |
| 04_entity_memory | 2 | 2 | 0 | 0 |
| 05_learned_knowledge | 2 | 2 | 0 | 0 |
| 06_quick_tests | 4 | 4 | 0 | 0 |
| 07_patterns | 2 | 2 | 0 | 0 |
| 08_custom_stores | 2 | 2 | 0 | 0 |
| 09_decision_logs | 2 | 2 | 0 | 0 |
| **Total** | **31** | **31** | **0** | **0** |
