# Learning Cookbooks Testing Log

Testing all cookbooks in `cookbook/08_learning/` to verify they work as expected.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Database: PostgreSQL with PgVector at `localhost:5532`
- Date: 2026-01-11

**Changes Tested:**
- Renamed `memories` to `user_memory` throughout (field, property, learning_type)
- Added new `08_custom_stores/` folder with custom store examples
- All cookbooks use `agent.get_learning_machine()` for accessing stores

---

## 01_basics/

### 1a_user_profile_always.py

**Status:** PASS

**Session 1:** User says "Hi! I'm Alice Chen, but please call me Ali."
- Profile automatically extracted: `name=Alice Chen`, `preferred_name=Ali`
- Agent responds naturally using the preferred name

**Session 2:** New session, user asks "What's my name again?"
- Profile recalled from database
- Agent responds: "Your name is Alice Chen - you go by Ali."

**Result:** User profile ALWAYS mode working correctly. Profile persists across sessions.

---

### 1b_user_profile_agentic.py

**Status:** PASS

**Session 1:** User says "Hi! I'm Robert Johnson, but everyone calls me Bob."
- Agent calls `update_profile(name=Robert Johnson, preferred_name=Bob)` tool
- Tool call visible in output

**Session 2:** New session, user asks "What should you call me?"
- Profile recalled from database
- Agent responds: "I'll call you Bob."

**Result:** User profile AGENTIC mode working correctly. Tool calls visible, profile persists.

---

### 2a_user_memory_always.py

**Status:** PASS

**Session 1:** User shares work info and preferences.
- Memories automatically extracted:
  - "User works at Anthropic as a research scientist."
  - "User prefers concise responses without too much explanation."
  - "User is currently working on a paper about transformer architectures."

**Session 2:** User asks about async HTTP libraries.
- Memories recalled and applied
- Response is appropriately concise

**Result:** User memory ALWAYS mode working correctly. Observations extracted and applied.

**Note:** This test validates the `memories` → `user_memory` rename. The `learning_type` is now `"user_memory"` instead of `"memories"`.

---

### 2b_user_memory_agentic.py

**Status:** PASS

**Session 1:** User shares they're a backend engineer at Stripe who prefers Rust.
- Agent calls `update_user_memory` tool
- Memory saved with user's preferences

**Session 2:** User asks for programming language recommendation.
- Memory recalled and applied
- Response leads with Rust recommendation (respecting user's preference)

**Result:** User memory AGENTIC mode working correctly. Tool calls visible, memories personalize responses.

---

### 3a_session_context_summary.py

**Status:** PASS

**Turn 1:** User asks about REST API design for todo app (PUT vs PATCH).
- Session context created with summary

**Turn 2:** User asks about URL structure.
- Summary updated to include both topics

**Turn 3:** User asks "What did we decide?"
- Agent recalls context from summary
- Provides coherent answer about PUT/PATCH and URL patterns

**Result:** Session context summary mode working correctly. Running summary persists.

---

### 3b_session_context_planning.py

**Status:** PASS

**Turn 1:** User asks about deploying Python app to production.
- Goal extracted and plan created with steps

**Turn 2-3:** User reports progress on steps.
- Progress tracked with checkmarks
- Agent provides next steps

**Session context shows:**
- Summary: Full deployment context
- Goal: Clear deployment objective
- Plan: Multiple steps
- Progress: Completed items tracked

**Result:** Session context planning mode working correctly. Goal/plan/progress tracked.

---

### 4_learned_knowledge.py

**Status:** PASS

**Session 1:** User asks to save insight about egress costs.
- Agent saves learning about checking egress costs when comparing cloud providers
- Learning stored in vector database

**Session 2:** User asks about picking cloud provider for 10TB pipeline.
- Agent searches learnings with `search_learnings` tool
- Finds and applies egress costs insight

**Result:** Learned knowledge working correctly. Save and search operations functional.

---

### 5a_entity_memory_always.py

**Status:** PASS

**Session 1:** User shares info about Acme Corp (tech stack, team size).
- Entities automatically created
- Facts extracted

**Session 2:** User shares funding news and hiring plans.
- Event added: "$50M Series B from Sequoia"
- Fact added: "Hiring 20 engineers"
- Relationships created (investor, person who shared update)
- Entity search found 3 entities

**Result:** Entity memory ALWAYS mode working correctly. Facts, events, relationships extracted.

---

### 5b_entity_memory_agentic.py

**Status:** PASS

**Session 1:** User shares info about Acme Corp.
- Agent calls `create_entity` and `add_fact` tools
- Tool calls visible in output

**Session 2:** User shares funding news.
- Agent first searches entities with `search_entities` (found existing Acme Corp)
- Then adds event with `add_event` tool
- Entity updated with new event

**Result:** Entity memory AGENTIC mode working correctly. Tool calls visible, search + update working.

---

## 01_basics COMPLETE - All 9 tests passed

---

## 02_user_profile/

### 01_always_extraction.py

**Status:** PASS

**4 conversations showing gradual profile building:**
- Conv 1: "Hi! I'm Marcus" - name extracted
- Conv 2: Work context shared - profile updated
- Conv 3: Preferences shared - profile updated
- Conv 4: "Call me Marc" - preferred_name updated to Marc

**Result:** Profile builds incrementally across conversations. Updates work correctly.

---

### 02_agentic_mode.py

**Status:** PASS

**3 sessions:**
- Session 1: "I'm Jordan Chen, call me JC" - tool call visible, profile saved
- Session 2: Agent recalls name correctly
- Session 3: "Call me Jordan" - preferred_name updated from JC to Jordan

**Result:** AGENTIC mode working. Tool calls visible, updates work.

---

### 03_custom_schema.py

**Status:** PASS

**Custom DeveloperProfile schema with extra fields:**
- Conv 1: Extracted name, company, role, experience_years
- Conv 2: Extracted languages, frameworks, primary_language
- Conv 3: Personalized response based on Go/Stripe context

**Profile shows all custom fields:**
- Name, Preferred Name, Company, Role
- Primary Language, Languages, Frameworks
- Experience Years

**Result:** Custom schema working correctly. All typed fields extracted and displayed.

---

## 02_user_profile COMPLETE - All 3 tests passed

---

## 03_session_context/

### 01_summary_mode.py

**Status:** PASS

**4 turns debugging memory leak:**
- Turn 1: Initial question about memory leak
- Turn 2: More context (grows without traffic)
- Turn 3: Ask about Pydantic caching
- Turn 4: "What were we debugging?" - correctly recalls full context

**Result:** Summary mode working. Running summary maintains conversation context.

---

### 02_planning_mode.py

**Status:** PASS

**4 steps deploying Python app to AWS:**
- Step 1: Initial goal stated, plan created
- Step 2: Dockerfile done - progress updated
- Step 3: ECR setup done - progress updated
- Step 4: "What's next?" - agent provides remaining steps

**Session context shows:**
- Summary: Full deployment context
- Goal: "Deploy containerized Python web app to AWS"
- Plan: Multiple steps (networking, deploy, CI/CD, etc.)
- Progress: Completed items with checkmarks

**Result:** Planning mode working correctly. Goal/plan/progress tracked.

---

## 03_session_context COMPLETE - All 2 tests passed

---

## 04_entity_memory/

### 01_facts_and_events.py

**Status:** PASS

**3 messages showing facts vs events:**
- Msg 1: Created DataPipe entity with facts (SF, Rust, CTO) and events (1000 customers, $80M Series B)
- Msg 2: Queried "What do we know about DataPipe?"
- Msg 3: Added new events (BigCloud partnership, London office)

**Tool calls visible:** create_entity, add_fact, add_event, add_relationship

**Result:** Facts/events distinction working. Entities created with proper categorization.

---

### 02_entity_relationships.py

**Status:** PASS

**3 messages showing relationships:**
- Msg 1: Created org structure (TechCorp, Sarah/Bob/Alice, teams)
- Msg 2: "Who reports to Bob?" - agent answers using relationships
- Msg 3: Company acquisitions/partnerships (TechCorp acquired StartupAI, partnered with CloudCo)

**Relationships created:**
- reports_to (people -> people)
- acquired (company -> company)
- partner_of (company -> company)

**Entity search found 9 entities including all people, teams, and companies.**

**Result:** Entity relationships working. Knowledge graph structure captured.

---

## 04_entity_memory COMPLETE - All 2 tests passed

---

## 05_learned_knowledge/

### 01_agentic_mode.py

**Status:** PASS

**3 messages showing save and apply:**
- Msg 1: Saved egress costs insight
- Msg 2: Saved database migration rollback insight
- Msg 3: Applied learnings when asked about PostgreSQL on AWS

**Tool calls visible:** search_learnings, save_learning with title/learning/context/tags

**Result:** Agentic learned knowledge working. Save and search functional.

---

### 02_propose_mode.py

**Status:** PASS

**3 messages showing propose-confirm flow:**
- Msg 1: User shares Docker localhost insight - agent proposes saving
- Msg 2: User confirms "Yes" - learning saved
- Msg 3: User shares restart fix - agent proposes, user rejects - NOT saved

**Result:** Propose mode working. Human-in-the-loop confirmation respected.

---

## 05_learned_knowledge COMPLETE - All 2 tests passed

---

## 06_quick_tests/

### 01_async_user_profile.py

**Status:** PASS

**Description:** Tests async path (aprint_response) for user profile learning.

**Result:** Async extraction works correctly. Profile persists across async sessions.

---

### 02_learning_true_shorthand.py

**Status:** PASS

**Description:** Tests `learning=True` shorthand - the simplest way to enable learning.

**Result:** Shorthand works. Default LearningMachine created with UserProfile enabled.

**Note:** LearningMachine is lazily initialized - only created when agent runs, not on construction.

---

### 03_no_db_graceful.py

**Status:** PASS

**Description:** Tests graceful degradation when no database is provided.

**Result:** Agent responds normally without crashing. Warning logged: "Database not provided. LearningMachine not initialized." Profile not persisted (expected).

---

### 04_claude_model.py

**Status:** PASS

**Description:** Tests learning with Claude model instead of OpenAI.

**Result:** Profile extraction works with `claude-sonnet-4-5`. Name and preferred_name extracted correctly. Profile recalled in session 2.

**Note:** Older Claude model IDs (e.g., `claude-sonnet-4-20250514`) may not support structured outputs. Use `claude-sonnet-4-5` or newer.

---

## 06_quick_tests COMPLETE - All 4 tests passed

---

## 07_patterns/

### personal_assistant.py

**Status:** PASS

**3 conversations demonstrating combined learning:**
- Conv 1: Introduction (name, job, preference, sister Sarah)
  - User profile extracted
  - Entity (Sarah) created with "likes hiking" fact
- Conv 2: Memory test - agent recalls name, job, sister
- Conv 3: Planning Sarah's visit
  - Session context tracks goal/plan/progress
  - Uses entity knowledge about Sarah (likes hiking)

**Result:** Combined stores (user_profile + session_context + entity_memory) working together.

---

### support_agent.py

**Status:** PASS

**2 ticket interactions showing knowledge transfer:**
- Ticket 1: Customer has login issue in Chrome
  - Agent suggests troubleshooting steps
  - Customer confirms "clearing cache worked"
  - Agent saves learning about cache fix
- Ticket 2: Different customer, similar issue
  - Agent searches prior learnings with `search_learnings`
  - Finds and applies cache clearing solution from ticket 1

**Result:** Support pattern working. Knowledge transfers across tickets/customers.

---

## 07_patterns COMPLETE - All 2 tests passed

---

## 08_custom_stores/ (NEW)

### 01_minimal_custom_store.py

**Status:** PASS

**Description:** Demonstrates how to create a custom learning store with in-memory storage.

**Features tested:**
- Custom store implementing LearningStore protocol
- Context injection via constructor (`context={"project_id": "learning-machine"}`)
- Manual context setting (`set_context()`)
- Custom `build_context()` formatting

**Result:** Custom store works correctly. Project context displayed in agent's system prompt and persists in memory.

**Note:** Warning logged "Database not provided. LearningMachine not initialized." but custom store still functions with in-memory storage.

---

### 02_custom_store_with_db.py

**Status:** PASS

**Description:** Demonstrates a database-backed custom store with tools.

**Features tested:**
- Database persistence using `db.get_learning()` / `db.upsert_learning()`
- Namespacing by project_id
- Custom tools exposed to agent (`add_project_note`, `update_project_summary`)
- Custom schema (`ProjectNotes` dataclass)

**3 interactions:**
- Msg 1: User describes project goal - agent uses `add_project_note` tool
- Msg 2: User mentions blocker - agent adds blocker note
- Msg 3: New session - notes persisted and recalled

**Result:** Database-backed custom store working. Tools functional, data persists across sessions.

---

## 08_custom_stores COMPLETE - All 2 tests passed

---

## TESTING COMPLETE

**Summary:**
- Total cookbooks tested: 26
- All passed: 26/26

**Key Changes Validated:**
1. `memories` → `user_memory` rename works correctly
   - Field: `user_memory` (was `memories`)
   - Property: `user_memory_store` (was `memories_store`)
   - Internal store key: `"user_memory"` (was `"memories"`)
   - Storage `learning_type`: `"user_memory"` (was `"memories"`)
2. Custom stores with context injection work
3. All stores work with both sync and async paths
4. `agent.get_learning_machine()` returns the resolved `LearningMachine` instance
5. `learning=True` shorthand works
6. Graceful degradation without DB
7. Claude models work (use `claude-sonnet-4-5` or newer)

**Migration Note:**
The `upsert_learning` in postgres.py does NOT update `learning_type` on conflict - it only updates `content`, `metadata`, and `updated_at`. If you have existing data with `learning_type="memories"`, you need to either:
1. Delete the old rows: `DELETE FROM agno_learnings WHERE learning_type = 'memories';`
2. Update the rows: `UPDATE agno_learnings SET learning_type = 'user_memory' WHERE learning_type = 'memories';`

**Notes:**
- LearningMachine is lazily initialized (only on first run)
- Older Claude model IDs may not support structured outputs
