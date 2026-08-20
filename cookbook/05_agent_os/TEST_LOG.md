# Test Log: 05_agent_os


## Verification - 2026-08-20 round 4, focus areas (feat/v3.0, base ca5697ecd9)

**Environment:** `.venvs/demo/bin/python`, batch runner (240s timeout) + manual retries

| File | Status | Note |
|---|---|---|
| basic.py | PASS | served over HTTP; /health, /config, POST run COMPLETED |

---

Tested on 2026-07-24 against Agno source commit
`64129408633bb3f4837b2a09a0eb087eddbed86a`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the AgentOS server and exercised its health and
configuration endpoints. Also connected the hosted Agno documentation MCP
server during an isolated application probe.

**Result:** `/health` returned `200` with status `ok`. `/config` reported OS ID
`hello-agent-os`, SQLite database `hello-agent-os-db`, agent `agno-assist`, and
OpenAI Responses model `gpt-5.5`. The MCP toolset exposed
`query_docs_filesystem_agno`, `search_agno`, and `submit_feedback`.

---
