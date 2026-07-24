# Test Log - _03_working_state

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.1 (source tree, branch feat/agent-fs at 937e1e973).
Re-run fresh at the final sweep (same date): every file in this folder PASS.

### basic.py

**Status:** PASS

**Description:** A four-step migration run as two sessions of two steps each; the agent reads state/checkpoint.md at the start of each session and overwrites it at the end, so session 2 resumes with no shared history.

**Result:** Session 1 (session_id `migration-1`) replied "Completed this session: 1. Exported the users table / 2. Exported the orders table"; checkpoint after session 1 contained exactly steps 1-2. Session 2 (session_id `migration-2`, a genuinely distinct session) read the checkpoint and replied "Completed these migration steps this session: 3. Verify row counts match / 4. Write the summary report"; the final checkpoint listed all four steps.

---

### last_seen_monitor.py

**Status:** PASS

**Description:** A latency monitor comparing current p95 readings against state/last-run.md, flagging >20 percent movers only, then updating the baseline.

**Result:** Run 1: "Baseline run: no previous readings found." and saved all three readings. Run 2 flagged exactly the mover: "checkout-api: 210ms -> 540ms, increased by 157.1%" with no mention of the two stable services. Stored baseline afterwards read checkout-api: 540ms / billing-api: 185ms / search-api: 96ms.

---
