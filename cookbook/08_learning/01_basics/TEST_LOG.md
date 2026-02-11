# Test Log: 01_basics

**Date:** 2026-02-10
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o
**Services:** pgvector

## Structure Check

**Result:** Checked 9 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 1a_user_profile_always.py

**Status:** PASS
**Time:** ~27s
**Description:** ALWAYS mode user profile extraction. Agent auto-extracts profile for Alice Chen / Ali. Cross-session recall confirmed.
**Output:** Profile extracted with name and preferred name, recalled in second session.
**Triage:** n/a

---

### 1b_user_profile_agentic.py

**Status:** PASS
**Time:** ~28s
**Description:** AGENTIC mode user profile via update_profile tool. Agent stores profile for Robert Johnson / Bob. Cross-session recall confirmed.
**Output:** Agent called update_profile tool, second session recalled name and preferences.
**Triage:** n/a

---

### 2a_user_memory_always.py

**Status:** PASS
**Time:** ~25s
**Description:** ALWAYS mode user memory. Agent auto-extracts memories including occupation (Anthropic scientist), preferences (concise style), and interests (transformer paper).
**Output:** Memories persisted and recalled across sessions.
**Triage:** n/a

---

### 2b_user_memory_agentic.py

**Status:** PASS
**Time:** ~30s
**Description:** AGENTIC mode user memory via tools. Agent stores memories for Stripe engineer who prefers Rust.
**Output:** Agent called add_memory tool, memories recalled in follow-up session.
**Triage:** n/a

---

### 3a_session_context_summary.py

**Status:** PASS
**Time:** ~40s
**Description:** Session context in SUMMARY mode. API design decisions tracked across multiple messages in a conversation.
**Output:** Summary updated after each turn, context maintained throughout session.
**Triage:** n/a

---

### 3b_session_context_planning.py

**Status:** PASS
**Time:** ~40s
**Description:** Session context in PLANNING mode. App deployment goals, blockers, and next-steps tracked across turns.
**Output:** Planning context updated incrementally, goals and blockers tracked.
**Triage:** n/a

---

### 4_learned_knowledge.py

**Status:** PASS
**Time:** ~50s
**Description:** Learned knowledge feature. Agent saves cloud egress costs and DB migration insights, then retrieves them via search in a later session.
**Output:** Knowledge saved and retrieved successfully on follow-up queries.
**Triage:** n/a

---

### 5a_entity_memory_always.py

**Status:** PASS
**Time:** ~35s
**Description:** ALWAYS mode entity memory. Agent auto-extracts entities including Acme Corp, Jane Smith, and Sequoia from conversation.
**Output:** Entities extracted with facts, events, and relationships persisted.
**Triage:** n/a

---

### 5b_entity_memory_agentic.py

**Status:** PASS
**Time:** ~35s
**Description:** AGENTIC mode entity memory via tools. Agent uses search_entities, add_event, and add_relationship tools.
**Output:** Agent called entity tools, entities with relationships persisted and searchable.
**Triage:** n/a

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 1a_user_profile_always.py | PASS | n/a | Alice Chen / Ali profile extracted |
| 1b_user_profile_agentic.py | PASS | n/a | Robert Johnson / Bob via tool |
| 2a_user_memory_always.py | PASS | n/a | Auto-extracted memories |
| 2b_user_memory_agentic.py | PASS | n/a | Tool-based memory storage |
| 3a_session_context_summary.py | PASS | n/a | Summary mode tracking |
| 3b_session_context_planning.py | PASS | n/a | Planning mode tracking |
| 4_learned_knowledge.py | PASS | n/a | Save and search knowledge |
| 5a_entity_memory_always.py | PASS | n/a | Auto entity extraction |
| 5b_entity_memory_agentic.py | PASS | n/a | Tool-based entity management |

**Totals:** 9 PASS, 0 FAIL, 0 SKIP, 0 ERROR
