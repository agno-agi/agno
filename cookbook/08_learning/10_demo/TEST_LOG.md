# Test Log: 10_demo

## 2026-06-12

### agents.py / run.py

**Status:** PASS

**Description:** Imported the demo agent against Postgres + pgvector (port 5532), confirmed all six stores initialize (user_profile, user_memory, session_context, entity_memory, learned_knowledge, decision_log), built the AgentOS app, and exercised GET /learnings, GET /learnings/users, and learning_type filtering with a FastAPI TestClient.

**Result:** App builds and the /learnings endpoints respond with paginated results.

---

### seed.py

**Status:** PENDING

**Description:** Runs scripted conversations across two users to populate every learning store, including a learned-knowledge insight that transfers from Alice to Ben. Requires OPENAI_API_KEY for live extraction and the pgvector container.

**Result:** Not yet run end to end (no API key in test environment). Imports and store accessors verified.

---
