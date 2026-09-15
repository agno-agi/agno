# Test Log: 01_basics

> Tested 2026-09-15 against `gpt-5.6-luna` (OpenAIResponses), demo venv, agno source tree.

### verify_done.py

**Status:** PASS

**Description:** A callable check requires report.md with a "## Trade-offs" section the prompt never mentions; output via print_response and get_last_run_output.

**Result:** Exit 0. Attempt 0 FAIL report_complete, attempt 1 PASS; `Verification: verified / passed`. The Response panel carried the model's one-sentence summary of the report. Run twice in a row: report.md is emptied at setup, and the second run showed the same attempt 0 FAIL, attempt 1 PASS.

---

### unverified.py

**Status:** PASS

**Description:** An impossible check with max_attempts=2 on a SqliteDb agent at tmp/verifiers/unverified.db; the record is read back from the session.

**Result:** Exit 0. `Status: UNVERIFIED`, `Stop reason: exhausted`, `Attempts: 2`; the stored run read back as `UNVERIFIED` with record `unverified / exhausted`.

---

### print_unverified.py

**Status:** PASS

**Description:** print_response (stream) on an agent with an impossible check and max_attempts=2, then the outcome read off get_last_run_output() from an InMemoryDb.

**Result:** Exit 0 on two runs in a row, identical outcome. The Response panel showed only the last attempt's answer, with no status panel; the lines after it read `Status: UNVERIFIED`, `Stop reason: exhausted`, `Attempts: 2 of 2`.

---

### streamed.py

**Status:** PASS

**Description:** A streamed run with stream_events=True, dispatching on RunEvent.verification_started / verification_completed; the check requires a "Further reading:" line the prompt never asks for.

**Result:** Exit 0 on two runs in a row, identical output. `[Verification attempt 1 of 3 started]`, `[Verification attempt 1 failed]` with `notes_complete: notes.txt has no 'Further reading:' line`, then attempt 2 started and passed. The model wrote the file through tool calls and streamed no RunContent text.

---

### async_verify.py

**Status:** PASS

**Description:** agent.arun with a coroutine check requiring a "## Trade-offs" section.

**Result:** Exit 0 on two runs in a row, both `Status: COMPLETED`, `Verification: verified / passed`; attempt 0 FAIL report_complete, attempt 1 PASS.

---

### check_policy.py

**Status:** PASS

**Description:** A required non-empty check on summary.md, an advisory length check (required=False), and a JudgeScorer gated by run_condition on the required checks passing.

**Result:** Exit 0 on two runs in a row, identical output. Attempt 0: summary_written PASS, short_enough PASS, JudgeScorer FAIL; attempt 1: all three PASS. `Verification: verified / passed`.

---

### flaky_check.py

**Status:** PASS

**Description:** verifier(service_ready, max_retries=2) over a probe that fails its first two calls.

**Result:** Exit 0. `Verification: verified / passed`, `Model attempts: 1`, `Probe calls: 3`: the retries absorbed the probe failures without a model re-entry.

---

### stop_on_failure_check.py

**Status:** PASS

**Description:** verifier(config_present, stop_on_failure=True) requiring a config file the agent has no tool to create, budget 3.

**Result:** Exit 0. `Status: UNVERIFIED`, `Verification: unverified / fatal`, `Attempts: 1 of 3`.

---

### budget_timeout.py

**Status:** PASS

**Description:** VerificationConfig(max_attempts=5, timeout=1.0) with a check that never passes.

**Result:** Exit 0. The first model call outran the one-second clock: `Verification: unverified / timeout`, `Attempts: 1 of 5`.

---
