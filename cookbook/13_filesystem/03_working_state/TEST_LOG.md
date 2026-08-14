# Test Log - 03_working_state

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.1 (source tree, branch feat/agent-fs at 7df2fad3a).
Re-run fresh at the final sweep (same date): every file in this folder PASS.
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased rather than quoted.

### basic.py

**Status:** PASS

**Description:** A four-step migration run as two sessions of two steps each; the agent reads state/checkpoint.md at the start of each session and overwrites it at the end, so session 2 resumes with no shared history.

**Result:** Session 1 (session_id `migration-1`) called `list_files(directory=state, pattern=checkpoint.md, ...)` then `write_file(path=state/checkpoint.md, content=1. Export the users table\n2. Export the orders table, overwrite=True)`. The printed checkpoint after session 1 held exactly those two steps. Session 2 (session_id `migration-2`, a distinct session) called `read_file(path=state/checkpoint.md, ...)` first and then wrote all four steps back. The printed checkpoint after session 2 listed steps 1 through 4, so session 2 resumed at step 3 rather than restarting.

---

### last_seen_monitor.py

**Status:** PASS

**Description:** A latency monitor comparing current p95 readings against state/last-run.md, flagging movers over 20 percent only, then updating the baseline.

**Result:** Run 1 reported a baseline with no previous readings and saved all three. Run 2 called `read_file(path=state/last-run.md, ...)`, flagged exactly one service, `checkout-api: 210ms → 540ms (+157.1%)`, and stated that no other service moved more than 20 percent; billing-api (180 to 185ms) and search-api (95 to 96ms) went unmentioned. It then called `write_file(path=state/last-run.md, ...)` and the printed baseline afterwards read checkout-api: 540ms / billing-api: 185ms / search-api: 96ms.

---
