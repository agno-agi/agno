# Test Log: 10_demo

## 2026-06-12

### seed.py

**Status:** PASS

**Description:** Ran the full seed end to end with a live OPENAI_API_KEY against the pgvector container. All scripted conversations completed and every store populated: user profiles and user memories for both users, session context for all three sessions, 7 global entity memories (Postgres Cluster with 4 facts, Marcus Lee, Sarah Kim, Northwind, Vantage Labs, Design System, PostgreSQL), 4 decision logs, and 5 learned-knowledge entries in the vector table including the explicit "rehearse the cutover on a clone" rule that transfers from Alice to Ben.

**Result:** 18 rows in ai.agno_learnings across all five learning types, 5 entries in ai.learning_demo_knowledge. Knowledge transfer beat works.

---

### run.py (live server)

**Status:** PASS

**Description:** With the server running on port 7777, exercised the full /learnings API against the seeded data: list with pagination, learning_type and user_id filters, GET /learnings/users (both users indexed), GET by deterministic identity id (user_profile_alice@vantagelabs.dev), then a full CRUD cycle on a throwaway decision_log record: POST (201, UUID id), PATCH content and metadata, DELETE (204), GET after delete (404). Seeded data unaffected.

**Result:** All endpoints respond correctly; CRUD round-trip verified.

---

### agents.py / run.py (offline smoke)

**Status:** PASS

**Description:** Imported the demo agent against Postgres + pgvector, confirmed all six stores initialize (user_profile, user_memory, session_context, entity_memory, learned_knowledge, decision_log), built the AgentOS app, and exercised the learnings endpoints with a FastAPI TestClient.

**Result:** App builds and the /learnings endpoints respond with paginated results.

---
