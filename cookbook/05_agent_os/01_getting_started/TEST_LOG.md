# Test Log: 01_getting_started

Tested on 2026-07-24 against Agno source commit
`64129408633bb3f4837b2a09a0eb087eddbed86a`.

### full_os.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the full AgentOS server with its SQLite database,
Chroma knowledge base, agent, team, and workflow, then exercised the live
health, configuration, knowledge-configuration, and session endpoints.

**Result:** `/health` returned `200` with status `ok`. `/config` reported OS ID
`getting-started-os`, database `getting-started-db`, agent
`getting-started-agent`, team `getting-started-team`, workflow
`getting-started-workflow`, and knowledge table `agno_knowledge`.
`/knowledge/config` reported a ChromaDB backend with vector, keyword, and
hybrid search. The paired HTTP walkthrough persisted one agent session.

---

### run_over_http.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the raw `httpx` walkthrough against `full_os.py`, including
discovery, a non-streaming model run, an SSE-streaming model run, and paginated
session retrieval.

**Result:** The client discovered all three runtime components, completed both
OpenAI Responses `gpt-5.5` runs, received a terminal SSE event, and found the
persisted session `getting-started-http-session` in `/sessions`.

---
