# Learning Cookbooks Test Log

Last updated: 2026-01-27

## Test Environment
- Database: PostgreSQL with PgVector at localhost:5532
- Python: `.venvs/demo/bin/python`
- Model: gpt-5.2 (OpenAI)

---

## Priority 1: Directly Affected by Recent Changes

### 05_learned_knowledge/01_agentic_mode.py

**Status:** PASS

**Description:** Tests AGENTIC mode for LearnedKnowledgeStore with the restructured prompt (Rules 1-4 consolidated in CRITICAL RULES section).

**Result:** Agent correctly:
- Searched before answering substantive questions (Rule 1)
- Saved team goal when user said "we're trying to reduce cloud egress costs" (Rule 4)
- Retrieved and applied learnings in subsequent session

---

### 05_learned_knowledge/02_propose_mode.py

**Status:** PASS

**Description:** Tests PROPOSE mode where agent proposes learnings for user approval before saving.

**Result:** Agent correctly:
- Proposed a learning with title/context/insight format (no emoji - fix verified)
- Did NOT save when user said "No, don't save that"
- Searched for existing learnings

---

### 06_quick_tests/02_learning_true_shorthand.py

**Status:** PASS

**Description:** Tests the `learning=True` shorthand which now enables both UserProfile and UserMemory stores by default.

**Result:**
- LearningMachine created with both stores: `['user_profile', 'user_memory']`
- UserProfileStore extracted: Name "Charlie Brown", Preferred Name "Chuck"
- UserMemoryStore extracted: "User's name is Charlie Brown; friends call him Chuck"
- Session 2 correctly recalled "Chuck"

---

## Priority 2: Smoke Tests

### 00_quickstart/01_always_learn.py

**Status:** PASS

**Description:** Basic ALWAYS mode learning with automatic extraction.

**Result:** Agent learned user info (Alice, Anthropic research scientist, prefers concise responses) and recalled it in session 2.

---

### 00_quickstart/02_agentic_learn.py

**Status:** PASS

**Description:** Basic AGENTIC mode where agent has tools to update memory.

**Result:** Agent used `update_user_memory` tool and correctly recalled user info.

---

### 00_quickstart/03_learned_knowledge.py

**Status:** PASS

**Description:** Tests learned knowledge sharing across users.

**Result:**
- User 1 saved "reduce cloud egress costs" goal
- User 2 received advice that incorporated the egress cost consideration ("Given your org goal to reduce egress costs, this should be a top discriminator")

---

## Priority 3: User Profile/Memory

### 01_basics/1a_user_profile_always.py

**Status:** PASS

**Description:** UserProfileStore with ALWAYS mode extraction.

**Result:** Extracted profile (Alice Chen / Ali) and recalled correctly in session 2.

---

### 01_basics/2a_user_memory_always.py

**Status:** PASS

**Description:** UserMemoryStore with ALWAYS mode extraction.

**Result:** Extracted memories about user's work and preferences, applied them in session 2 response.

---

## Priority 4: Other Stores

### 01_basics/3a_session_context_summary.py

**Status:** PASS

**Description:** SessionContextStore tracking conversation state.

**Result:** Maintained session summary across turns, correctly summarized the API design discussion when asked "What did we decide?"

---

### 01_basics/4_learned_knowledge.py

**Status:** PASS

**Description:** Basic LearnedKnowledgeStore functionality.

**Result:** Agent searched learnings, incorporated egress cost goal into cloud provider recommendations.

---

## Summary

| Category | Tests | Passed | Failed |
|----------|-------|--------|--------|
| Priority 1 (Recent Changes) | 3 | 3 | 0 |
| Priority 2 (Smoke Tests) | 3 | 3 | 0 |
| Priority 3 (User Profile/Memory) | 2 | 2 | 0 |
| Priority 4 (Other Stores) | 2 | 2 | 0 |
| **Total** | **10** | **10** | **0** |

All tests passing after the following changes:
1. `learning=True` now enables both `user_profile` and `user_memory` by default
2. LearnedKnowledgeStore prompt restructured with Rules 1-4 in CRITICAL RULES section
3. Added Rule 3 (explicit save requests) and Rule 4 (org goals/constraints/policies)
4. Removed emoji from PROPOSE mode
5. Fixed `learning_saved` state reset bug
6. Simplified tool docstrings (removed redundant "when to save" criteria)
7. Updated extraction prompt with clearer two-category structure
