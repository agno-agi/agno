# Test Log: 01_basics

> 2026-07-25 (feat/entity-memory-revamp): 5a/5b replaced by 5_entity_memory.py -
> entity memory is AGENTIC-only on the four-tool surface. Ran live against gpt-5.5:
> PASS (Acme Corp captured with properties + CTO edge in s1; s2 answered from the
> injected block with no tool call). 6_extraction_limits.py no longer includes
> entity memory (it has no extraction pass to limit).

> Tests not yet run. Run each file and update this log.

### 1a_user_profile_always.py

**Status:** PENDING

**Description:** Run and validate `1a_user_profile_always.py` example behavior.

**Result:** Not run yet.

---

### 1b_user_profile_agentic.py

**Status:** PENDING

**Description:** Run and validate `1b_user_profile_agentic.py` example behavior.

**Result:** Not run yet.

---

### 2a_user_memory_always.py

**Status:** PENDING

**Description:** Run and validate `2a_user_memory_always.py` example behavior.

**Result:** Not run yet.

---

### 2b_user_memory_agentic.py

**Status:** PENDING

**Description:** Run and validate `2b_user_memory_agentic.py` example behavior.

**Result:** Not run yet.

---

### 3a_session_context_summary.py

**Status:** PENDING

**Description:** Run and validate `3a_session_context_summary.py` example behavior.

**Result:** Not run yet.

---

### 3b_session_context_planning.py

**Status:** PENDING

**Description:** Run and validate `3b_session_context_planning.py` example behavior.

**Result:** Not run yet.

---

### 4_learned_knowledge.py

**Status:** PENDING

**Description:** Run and validate `4_learned_knowledge.py` example behavior.

**Result:** Not run yet.

---

### 5_entity_memory.py

**Status:** PASS

**Description:** The four entity tools; capture in one session, recall in a fresh one.

**Result:** Run live 2026-07-25 (gpt-5.5): Acme Corp captured with properties and the CTO
edge in s1; s2 answered from the injected block with no tool call.

---

### 6_extraction_limits.py

**Status:** PENDING

**Description:** max_updates_per_run caps for user_profile/user_memory (entity memory
removed - it has no extraction pass to limit).

**Result:** Not re-run in this pass.

---
