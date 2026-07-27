# Test Log: 11_learnings

Tested on 2026-07-24 against Phase 3 base commit
`74c0bfb1499c2636aa7c3f1ccd8935ceeb824b4b`.

### learnings_with_agentos.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in learning-enabled server with its shared
SQLite database and OpenAI Responses `gpt-5.5` agent and extractors.

**Result:** The app started on port 7777, `GET /health` returned `200` with
status `ok`, and `GET /config` discovered `learning-assistant`. A live
non-streaming run completed, then automatic extraction persisted both a
`user_profile` and `user_memory` for the run's unique user.

---

### rest_api_learnings.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the agent-to-REST round trip followed by the complete
manual learning CRUD and bulk-user deletion flow.

**Result:** The agent run returned `COMPLETED`; immediate
`GET /learnings?user_id=...` read back a profile containing Mira's name and a
memory containing the concise-response preference. The manual flow created
`user_profile_crud-learning-b9897e64`, listed and fetched it, read its owning
user and update timestamp, replaced its content and metadata, deleted it with
`204`, and observed `404` on the follow-up GET. Two temporary decision logs
were then removed through the user-delete route; the final list reported zero
records. Both unique demo users were cleaned up.

---
