# Claude cookbook test log

**Date:** 2026-10-09 (Europe/London)

**Source:** main `ff9b86d5be5245bd349e55c459bce45ba3d3cc21` plus this PR's cookbook/test changes, run from an isolated worktree before commit. The imported Agno path was the worktree's `libs/agno/agno/__init__.py`, not a released wheel or the user's checkout.

**Environment:** Python 3.12.8; editable Agno 3.1.2; SQLAlchemy 2.0.52; pytest 9.1.1. Fresh worktree development venv. Existing local CLI authentication; no credential values read or printed.

**Harness:** claude-agent-sdk 0.2.165; Claude Code 2.1.294; model claude-sonnet-4-6.

**Command:** `AGNO_TEST_CLAUDE_SDK=1 AGNO_TEST_CODEX_SDK=1 .venv/bin/python -m pytest libs/agno/tests/integration/agents/test_harness_cookbooks.py -q -o addopts=''`. Both providers together: 8 passed in 70.07 seconds; none skipped; no retries.

### basic.py

**Status:** PASS

**Description:** Real one-shot Agno wrapper run with the inclusive shipping-threshold prompt.

**Result:** Returned zero-dollar shipping and a COMPLETED RunOutput. A separate run with an invalid model exited 1 at the terminal-status assertion. A provider failure cannot silently pass this example.

---

### native_sdk.py

**Status:** PASS

**Description:** Same prompt/model using the native SDK directly.

**Result:** Returned zero-dollar shipping, a native Claude session ID and successful terminal status. This is a one-shot API comparison, not a timing benchmark or native-resume test.

---

### tools.py

**Status:** PASS

**Description:** Real streamed review of shipping.py and orders.json through the Agno wrapper.

**Result:** Text deltas and tool start/end events appeared; returned tool data contained the fixture's subtotal and boundary values. The answer correctly explained fees 8, 0, 0. The final RunOutput completed with successful tool data. Fixture file hashes stayed unchanged.

---

### agent_os.py

**Status:** PASS

**Description:** Started this exact server script on a loopback port with a temporary SQLite directory. Exercised health, agent discovery, one non-streaming tool run and one SSE tool run in independent sessions. Retrieved both runs through GET /agents/{id}/runs/{run_id}?session_id=... .

**Result:** Both runs were COMPLETED and retained two Read results each. The SSE response contained 146 events in this run, including RunStarted, RunContent, ToolCallStarted, ToolCallCompleted and RunCompleted. IDs were consistent; no RunError/RunCancelled appeared. Both answers correctly explained the boundary. Fixture hashes were unchanged. Event counts vary and are not acceptance thresholds.

---

## Limits

**Clean-install follow-up:** This provider's four cases also passed in the
minimal README environment: agno[os,sqlite], the pinned SDKs, pytest and
pytest-asyncio, with SQLAlchemy 2.1.4. Both providers together: 8 passed in
74.15 seconds. The first collection attempt exposed a missing pytest-asyncio
setup instruction; it was corrected before rerunning. See the root test log.

No browser disconnect, server restart, native transcript recovery, production authorization, queue retry, compaction, approval, subagent or sandbox-replacement claim is made by these tests. API access was real loopback HTTP, not an in-process ASGI mock. The SQLite result checks are separate from native conversation durability. Older tests in cookbook/frameworks retain their historical scope.
