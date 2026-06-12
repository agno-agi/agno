# Test Log: 10_demo

## 2026-06-12

### agents.py / run.py

**Status:** PASS

**Description:** Imported the demo agent and built the AgentOS app, then exercised the learnings endpoints with a FastAPI TestClient (GET /learnings, GET /learnings/users). Verified all five stores initialize (user_profile, user_memory, session_context, entity_memory, decision_log) and the endpoints return paginated responses against the SQLite database.

**Result:** App builds and the /learnings endpoints respond correctly.

---

### seed.py

**Status:** PENDING

**Description:** Runs six scripted conversations across two users to populate every learning store. Requires OPENAI_API_KEY for live extraction.

**Result:** Not yet run end to end (no API key in test environment). Imports and store accessors verified.

---
