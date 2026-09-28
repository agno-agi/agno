# Test Log: 06_agentos

> Tested 2026-09-15 against `gpt-5.6-luna` (OpenAIResponses), demo venv, agno source tree.

### verified_agent_os.py

**Status:** PASS

**Description:** Served with `uvicorn verified_agent_os:app --port 7890` and exercised over HTTP with curl; the check requires a "Call to action:" line in pitch.md the request never mentions.

**Result:** Streaming POST to `/agents/verified-writer/runs`: the SSE stream carried `VerificationStarted` / `VerificationCompleted` twice, the first with `passed: false` and the report `pitch.md has no 'Call to action:' line`, the second `passed: true, stop_reason: passed`, then `RunCompleted`. A second non-stream POST on the same server (a different pitch) also failed attempt 0 and passed attempt 1, returning `COMPLETED` with record `verified / passed`; `GET /sessions/{id}/runs` listed the row as `('COMPLETED', 'passed')`. Two server starts in a row: each start emptied pitch.md (0 bytes at startup), and each start's streamed run showed attempt 1 `passed: false`, attempt 2 `passed: true`, then `RunCompleted`. Starting through `python verified_agent_os.py` (reload=True) also served `/health` with 200.

---
