# Agents Cookbook Testing Log

Testing agent feature examples in `cookbook/03_agents/` to verify they work as expected.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Database: PostgreSQL with PgVector (for RAG examples)
- Date: 2026-01-14

---

## High Priority - Unique Features

### culture/

#### 01_create_cultural_knowledge.py

**Status:** NOT TESTED

**Description:** Create cultural knowledge using CultureManager.

**Dependencies:** ANTHROPIC_API_KEY, SQLite

---

#### 02_use_cultural_knowledge_in_agent.py

**Status:** NOT TESTED

**Description:** Use existing cultural knowledge in an agent.

**Dependencies:** ANTHROPIC_API_KEY, SQLite (run 01 first)

---

#### 03_automatic_cultural_management.py

**Status:** NOT TESTED

**Description:** Agent autonomously updates cultural knowledge.

**Dependencies:** ANTHROPIC_API_KEY, SQLite

---

### hooks/

#### output_stream_hook_send_notification.py

**Status:** NOT TESTED

**Description:** Post-hook to send notifications after agent responses.

**Dependencies:** OPENAI_API_KEY

---

### state/

#### session_state_basic.py

**Status:** NOT TESTED

**Description:** Basic session state management with shopping list.

**Dependencies:** OPENAI_API_KEY, SQLite

---

### other/

#### cancel_a_run.py

**Status:** NOT TESTED

**Description:** Cancel running agent execution from another thread.

**Dependencies:** OPENAI_API_KEY

---

## Medium Priority - Core Patterns

### agentic_search/

#### agentic_rag_with_reasoning.py

**Status:** NOT TESTED

**Description:** Agentic RAG with reasoning tools and Cohere reranker.

**Dependencies:** ANTHROPIC_API_KEY, CO_API_KEY, LanceDb

---

### human_in_the_loop/

#### confirmation_required.py

**Status:** NOT TESTED

**Description:** Tool execution confirmation pattern.

**Dependencies:** OPENAI_API_KEY

**Note:** Interactive - requires user input

---

#### user_input_required.py

**Status:** NOT TESTED

**Description:** Dynamic user input collection.

**Dependencies:** OPENAI_API_KEY

**Note:** Interactive - requires user input

---

### async/

#### basic.py

**Status:** NOT TESTED

**Description:** Basic async agent usage.

**Dependencies:** OPENAI_API_KEY

---

#### gather_agents.py

**Status:** NOT TESTED

**Description:** Concurrent agent execution with asyncio.gather.

**Dependencies:** OPENAI_API_KEY

---

### guardrails/

#### pii_detection.py

**Status:** NOT TESTED

**Description:** Detect and block PII in input.

**Dependencies:** OPENAI_API_KEY

---

#### prompt_injection.py

**Status:** NOT TESTED

**Description:** Detect and block prompt injection attempts.

**Dependencies:** OPENAI_API_KEY

---

## Lower Priority - Advanced Features

### multimodal/

#### image_to_text.py

**Status:** NOT TESTED

**Description:** Image analysis and description.

**Dependencies:** OPENAI_API_KEY, sample.jpg file

---

#### video_caption_agent.py

**Status:** NOT TESTED

**Description:** Video processing and caption generation.

**Dependencies:** OPENAI_API_KEY, ffmpeg, moviepy

---

### rag/

#### agentic_rag_pgvector.py

**Status:** NOT TESTED

**Description:** Agentic RAG with PgVector.

**Dependencies:** OPENAI_API_KEY, PgVector

---

### caching/

#### cache_model_response.py

**Status:** NOT TESTED

**Description:** Cache model responses for performance.

**Dependencies:** OPENAI_API_KEY

---

## TESTING SUMMARY

**Summary:**
- Total examples: 165+
- Tested: 0
- Passed: 0
- Skipped: 0

**Priority Queue:**
1. Culture system (unique feature - 6 files)
2. Hooks system (production patterns - 7 files)
3. State management (core feature - 13 files)
4. Human-in-the-loop basics (22 files, many interactive)
5. Agentic RAG (5 files)

**Notes:**
- This folder is feature documentation, not use-case examples
- Culture examples should be run in sequence (01, 02, 03, etc.)
- Human-in-the-loop examples are mostly interactive
- Multimodal examples need local media files
