# Test log

## 2026-10-09

Environment: demo venv, claude-agent-sdk, claude-sonnet-4-6, SQLite transcript storage in a temporary workspace per run. A finished run is always continued as a new sibling run with fork lineage. Assertions are on files, tool results and lineage, not on the model's wording.

Finding while writing these: the SDK's default system prompt does not tell the model its working directory, so the Write tool wrote to `/slugify.py` and failed with a read-only file system error. Cookbooks that create files now set `system_prompt` naming the workspace. Bash was never affected because the subprocess runs in `cwd`.

### 01_continue_finished_run.py

**Status:** PASS

**Description:** The source run writes `slugify.py` and runs it. The continuation asks for `test_slugify.py` covering "the function you just wrote" without naming it, then runs the tests. Asserts both files exist, the continuation has a new run_id with `forked_from_run_id` and `forked_from_message_index` set, the source run is unchanged, and the session holds two runs.

**Result:** Source replied `hello-world`; continuation wrote and ran the tests and replied `ok`. Two runs in the session, the second forked from the first.

---

### 02_fork_from_checkpoint.py

**Status:** PASS

**Description:** Three Bash steps over a seeded `sales.csv` (count rows, sum amount, write summary.txt). Lists checkpoints, forks after the first step, and asks the branch without tools what it knows. Asserts the branch carries exactly the kept tool results, lineage, and that the source run and summary.txt are intact.

**Result:** Checkpoints at 3 (`5`), 5 (`500`), 7 (file written), 8 (end). The branch answered rows 5 and "not computed yet" for the total. summary.txt still on disk.

---

### 03_replay_user_turn.py

**Status:** PASS

**Description:** Lists `notes/*.md`, adds `retro.md`, replays the prompt with `continue_from="last_user"`, then rewrites the prompt with `continue_from=0`. Asserts the replayed tool output contains the new file and that both branches carry lineage.

**Result:** Original answer `roadmap.md`; replay answered `retro.md, roadmap.md`; rewrite counted bullets per file. Three runs in the session.

---

### 04_background_continue.py

**Status:** PASS

**Description:** Writes `fizzbuzz.py`, then continues with `background=True, stream=True, yield_run_output=True` to run it. Prints RunStarted, ToolCallStarted, ToolCallCompleted, RunContent and RunCompleted as they arrive, checks the final RunOutput and lineage, then reads the stored run. Ends with `await_background_runs()`.

**Result:** Events streamed live; final content `FizzBuzz`; stored run COMPLETED with two tool results. Before `await_background_runs()` was added, the script logged "Failed to complete event stream" on exit because the loop closed while the run was marking its event stream complete; the run itself was already COMPLETED. The helper was added to `agno.run.background` and the warning no longer appears.

---

### 05_agentos_api.py --verify

**Status:** PASS

**Description:** Through the AgentOS test client: POST a three-step CSV run, GET `/checkpoints`, POST `/continue` with `fork=true` from the first checkpoint asking what the branch knows, POST `/continue` from `end` streamed with a question about the data, then list the session runs.

**Result:** Run replied `rows=5 total=500 max=east`; checkpoints 3, 5, 7, 8; the branch knew the row count and said the total was not computed yet; the streamed follow-up answered `east`; the session listed the source plus two forked runs.

---

### 06_recover_failed_tool_run.py

**Status:** PASS

**Description:** Runs a script that appends one invoice entry to an audit log, deliberately hits `max_turns=1`, then forks from the failed run's end. Checks the completed tool result survives and that recovery executes no additional tools or invoice writes.

**Result:** Live Claude SDK 0.2.110 with claude-sonnet-4-6 and SQLite: the initial run returned `error_max_turns` after recording invoice-1042. Its stored result reported one audit entry, and continuation answered from that result. The audit log still contained exactly one entry.

---

### 07_subagent_checkpoints.py

**Status:** PASS

**Description:** Delegates CSV analysis to a sales analyst subagent, checks that nested tool results have no checkpoint markers, then forks from the top-level Agent result without re-running the analysis.

**Result:** Live Claude SDK 0.2.110 with claude-sonnet-4-6 and SQLite: the parent result at message 3 was a checkpoint; nested results at messages 5 and 7 were excluded. The branch recalled 3 rows and a total of 400 without new tool calls.

---

### 06_recover_failed_tool_run.py --stream

**Status:** PASS

**Description:** Repeats the invoice-recovery scenario with streamed events and a final `RunOutput`. Checks that the terminal RunError retains the completed tool checkpoint for continuation.

**Result:** Live Claude SDK 0.2.110: streamed run ended with `error_max_turns`, preserved the result at message 3, and recovered successfully. No additional tools ran and the audit log contained exactly one invoice entry.

---
