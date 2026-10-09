# Test log

## 2026-10-09

Environment: demo venv, claude-agent-sdk, claude-sonnet-4-6, SQLite transcript storage in a temporary directory. The branch behavior under test is the one from the continue-from PR: a finished run is always continued as a new sibling run with fork lineage.

### 01_continue_finished_run.py

**Status:** PASS

**Description:** Runs a one-word turn, then continues it from the end with a question about the previous answer. Asserts the continuation has a new run_id, `forked_from_run_id` pointing at the source, `forked_from_message_index` equal to the source message count, that the source run is unchanged, and that the session holds two runs.

**Result:** Source replied ALPHA; continuation replied ALPHA (remembered the source turn). Session: two runs, second forked from the first.

---

### 02_fork_from_checkpoint.py

**Status:** PASS

**Description:** Two-step Bash run (echo alpha, echo beta, DONE). Lists checkpoints, forks from the first one, and asserts the branch carries exactly the tool results up to that checkpoint while the source run keeps all six messages.

**Result:** Checkpoints at 3 (tool, alpha), 5 (tool, beta), 6 (end, DONE). Branch from step 3 answered with only `echo alpha`.

---

### 03_replay_user_turn.py

**Status:** PASS

**Description:** Runs `date +%s%N`, replays the prompt with `continue_from="last_user"` and no input, then rewrites it with `continue_from=0` and a new input. Asserts lineage on both branches.

**Result:** Replay produced a different timestamp (the tool ran again); rewrite answered `rewritten`. Three runs in the session.

---

### 04_background_continue.py

**Status:** PASS

**Description:** Continues a finished run with `background=True`, checks the accepted output is PENDING with a new run_id, and polls `aget_run_output` until it finishes.

**Result:** Accepted PENDING; finished COMPLETED with content `ALPHA BETA` and `forked_from_run_id` equal to the source.

---

### 05_agentos_api.py --verify

**Status:** PASS

**Description:** Through the AgentOS test client: POST a two-step run, GET `/checkpoints`, POST `/continue` with `fork=true` from the first checkpoint, POST `/continue` from `end` streamed, then list the session runs.

**Result:** Checkpoints 3, 5, 6; fork from step 3 answered `echo alpha`; streamed continuation emitted RunStarted through RunCompleted; the session listed the source run plus two runs forked from it.

---
