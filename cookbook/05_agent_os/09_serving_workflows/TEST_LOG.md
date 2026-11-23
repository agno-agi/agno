# Test Log: 09_serving_workflows

Tested on 2026-07-24 against Agno source commit
`37496c5ccd3be632cdbb97a9111a4a09999850fb`.

### basic.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in two-step workflow server on
port 7787 (via the `AGENT_OS_PORT`/`AGENT_OS_BASE_URL` environment
overrides; the checked-in default is 7777)
with the repository's direnv OpenAI credentials.

**Result:** The app started cleanly, `GET /health` returned `ok`, and
`GET /config` discovered `release-notes-workflow`. The same live server
completed the HTTP and WebSocket clients recorded below.

---

### with_workflow_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the WorkflowAgent server and ran the checked-in
`--demo` client for a new brief followed by a question about that brief.

**Result:** `GET /workflows/brief-workflow-agent` reported
`workflow_agent: true`. The first HTTP run completed after the WorkflowAgent
called the deterministic two-step workflow. The second run answered
`automate one end-to-end acceptance test` from persisted workflow history
without executing the workflow again.

---

### with_input_schema.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the input-schema server and ran its checked-in
`--demo` client against health and workflow detail.

**Result:** `GET /health` returned `ok`.
`GET /workflows/research-brief-workflow` returned an `input_schema` titled
`ResearchBrief` with all four expected fields. `topic`, `focus_areas`, and
`target_audience` were required; `sources_required` retained its default.

---

### run_over_api.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the raw-httpx client against `basic.py` using OpenAI
Responses `gpt-5.5`.

**Result:** The non-streaming run
`94106bba-1d5a-4161-90dc-e600d21d5ad7` returned `COMPLETED`. The SSE run
`651ae65f-6a80-4295-92d4-4733d4775698` emitted both steps and ended with
`WorkflowCompleted`. The nested run-list route returned both new IDs in
`workflow-http-session`.

---

### ws_stream.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Connected the checked-in `websockets` client to the genuine
`/workflows/ws` route exposed by `basic.py`, sent `start-workflow`, and
consumed the live OpenAI Responses event stream.

**Result:** The server greeting reported that authentication was not required.
Run `674482f3-412f-4f71-80b8-d56e5ffa37ce` emitted indexed events through
index 105 and ended with `WorkflowCompleted`.

---

## Validation

- All five Python files imported; all three server apps constructed their
  expected workflow routes.
- Recursive pattern validation checked exactly 5 Python files with 0
  violations.
- Targeted Ruff format and check passed.
- Stale-model, emoji, fake-WebSocket, and non-PASS status scans returned no
  target hits.
- `git diff --check` passed for the lesson.
