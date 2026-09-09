# Test Log: 10_knowledge

Tested on 2026-07-24 against Phase 3 base commit
`74c0bfb1499c2636aa7c3f1ccd8935ceeb824b4b`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in SQLite- and Chroma-backed server through
its main execution path, including the `skip_if_exists` seed insertion.

**Result:** The seed inserted one document, the app started on port 7777, and
`GET /health` returned `200` with status `ok`. `GET /config` discovered agent
`knowledge-assistant` and the single knowledge instance `AgentOS Knowledge`.
The live REST client below used that same server and knowledge instance.

---

### rest_api_knowledge.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the raw-httpx upload, status, list, search, delete, and
follow-up-read lifecycle against `basic.py`.

**Result:** `POST /knowledge/content` returned `202` for content
`2477354a-20a6-5364-a70e-b8ef4e494fb4`. Status polling observed `processing`
then `completed`. The paginated list contained two items: the server seed and
the upload. Search returned two results and matched the unique marker
`control-plane-3f063fd0`. DELETE returned `200`, and the follow-up content GET
returned `404`.

---
