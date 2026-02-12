# Test Log: learning

> Updated: 2026-02-11

### 01_team_always_learn.py

**Status:** PASS

**Description:** Simplest learning setup — `learning=True` shorthand on Team. Automatically captures UserProfile and UserMemory. Two-session demo: Alice introduces herself, team remembers across sessions.

**Result:** Ran successfully. UserProfile captured name "Alice". UserMemory stored multiple observations about ML engineer role and code example preferences. Cross-session recall worked — second session referenced first session's info.

---

### 02_team_configured_learning.py

**Status:** PASS

**Description:** Granular learning store configuration — UserProfile (ALWAYS), UserMemory (AGENTIC), SessionContext (ALWAYS). Two-session demo: Bob (VP Engineering) gets org scaling advice.

**Result:** Ran successfully. All three stores populated correctly. UserProfile captured role/company details. SessionContext tracked goals. Second session retained context for hiring strategy advice.

---

### 03_team_entity_memory.py

**Status:** PASS

**Description:** Entity tracking — EntityMemoryConfig captures facts, events, relationships about projects and people. Two-session demo: Carol manages three projects.

**Result:** Ran successfully. Entity memory correctly extracted 3 projects (Atlas, Beacon, Compass) with leads, status, and key events. Second session update (Atlas back on track, Eve on leave) was captured with timestamps. Entity search and print worked correctly.

---

### 04_team_session_planning.py

**Status:** PASS

**Description:** Session planning — `SessionContextConfig(enable_planning=True)` tracks goals and plan steps. Three-turn demo: Diana manages v2.0 release across infra, security, rollout phases.

**Result:** Ran successfully. Session context captured release goal and summary. Planning mode tracked checklist progress across 3 turns (infra → security → rollout). Each turn's session context print showed updated state.

---

### 05_team_learned_knowledge.py

**Status:** PASS

**Description:** Shared knowledge base from conversations — LearnedKnowledgeConfig with PgVector. Three-session demo: SRE team saves incident learnings, then applies them to new situation.

**Result:** Ran successfully. Session 1 saved PgBouncer/connection pooling learning. Session 2 saved Kubernetes resource limits best practice. Session 3 queried and correctly retrieved both prior learnings when asked about deploying new microservice to PostgreSQL + Kubernetes.

---

### 06_team_decision_log.py

**Status:** PASS

**Description:** Decision audit trail — DecisionLogConfig with agent tools (save/search). Two-session demo: Architecture Review Board evaluates database and caching choices.

**Result:** Ran successfully. Session 1 logged Apache Druid selection for analytics DB with reasoning. Session 2 logged Redis as caching layer choice. Decision log print showed all logged decisions with reasoning and alternatives.

---
