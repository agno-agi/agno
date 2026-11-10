# Python client test log

Tested live on 2026-07-24 from the pinned Agno source worktree with
`.venvs/demo/bin/python` and the repository's `direnv` environment. The live
suite covered model responses, streaming tool events, embeddings, evaluations,
and central Bearer authentication.

### `_server.py`

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the shared server on port 7778, exercised its health
and configuration endpoints, and then terminated it cleanly.

**Observed:** `GET /health` returned HTTP 200 with `status: ok`. `GET /config`
identified `python-client-demo` and listed agent `assistant`, team
`research-team`, and workflow `qa-workflow`. OpenAPI contained the agent-run,
session, memory, knowledge-content, knowledge-search, and evaluation routes.

---

### `01_connect.py`

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the client against the live server with no central auth.

**Observed:** Both `get_config()` and `aget_config()` connected successfully
and printed the same agent, team, and workflow IDs.

---

### `02_run_and_stream.py`

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran one complete response and one typed event stream against
the live `assistant` agent.

**Observed:** The non-streaming calculator run returned `391`. The stream
emitted `RunStarted`, `ToolCallStarted`, `ToolCallCompleted`, content, and
`RunCompleted` events, and the calculator returned `42`.

---

### `03_sessions_and_memory.py`

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the full session lifecycle and memory CRUD example,
including a model-backed run inside the created session.

**Observed:** The client created one session and one run, listed and read the
session, renamed it, created/read/updated a memory, and deleted both the memory
and session during cleanup.

---

### `04_knowledge.py`

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the full upload, status polling, list, search, and delete
lifecycle against the live knowledge base.

**Observed:** The upload moved from `processing` to `completed`, the collection
contained one item, and search returned the uploaded AgentOS sentence as its
single result. The content item was deleted successfully.

---

### `05_evals.py`

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran accuracy and tool-call reliability evaluations, then
listed and fetched their stored results.

**Observed:** The accuracy evaluation scored `10`. The reliability evaluation
reported `PASSED` with `multiply` in both its passed tool calls and passed
argument checks. The API listed two stored evaluations and fetched both by ID.

---

### `06_auth.py`

**Status:** PASS

**Test mode:** LIVE

**Description:** Restarted `_server.py` with a temporary `OS_SECURITY_KEY` and
ran the authenticated configuration and model calls.

**Observed:** The unauthenticated request returned HTTP 401. Passing
`headers={"Authorization": "Bearer <key>"}` to `aget_config()` returned
`python-client-demo`, and the authenticated agent run returned a successful
one-sentence confirmation.

---
