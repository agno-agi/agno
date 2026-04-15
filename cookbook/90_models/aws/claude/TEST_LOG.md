# TEST_LOG

### basic.py

**Status:** PASS

**Description:** Runs Claude via Bedrock (global.anthropic.claude-sonnet-4-5-20250929-v1:0) across sync, sync+stream, async, async+stream to verify PR #7492 did not regress the env-var-credentials path.

**Result:** All 4 variants returned a response (9.2s / 6.5s / 3.4s / 4.5s). No warnings. Confirms the "no session" path works end-to-end against real Bedrock after the shared-HTTP/2-client injection was removed.

---

### tool_use.py

**Status:** PASS

**Description:** Runs Claude via Bedrock with WebSearchTools across sync, sync+stream, async+stream to validate tool_use on the main code path after PR #7492.

**Result:** All variants executed search and produced responses (longest ~11.5s). No warnings, no regressions.

---
