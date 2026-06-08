# Learnings CRUD Cookbook - Test Log

### learnings_with_agentos.py

**Status:** PASS

**Description:** Starts an AgentOS with a learning-enabled agent backed by SqliteDb. Exposes the `/learnings` endpoints. Verified the server boots, registers the routes, and responds to GET /learnings returning the empty page envelope.

**Result:** Server starts cleanly on http://127.0.0.1:7777 and serves the learnings router.

---

### rest_api_learnings.py

**Status:** PASS

**Description:** Exercises the full CRUD cycle against the running AgentOS: POST creates a `user_profile` learning, GET lists it, GET /learnings/users lists the owning users with per-user counts, GET by id fetches it, PATCH replaces content + metadata, DELETE removes it, and a follow-up GET returns 404.

**Result:** All verbs returned the expected status codes and payloads. The `/learnings/users` listing grouped records by `user_id` with correct counts and last-updated timestamps. Pagination metadata populated correctly. PATCH performed a full replace of `content` and `metadata` while preserving identity fields.

---
