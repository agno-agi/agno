# Test Log: 04_run_lifecycle

Tested on 2026-07-24 against Agno source commit
`64129408633bb3f4837b2a09a0eb087eddbed86a`.

### background_run.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in AgentOS server with its SQLite-backed
agent and ran the checked-in `--demo` client using OpenAI Responses
`gpt-5.5`.

**Result:** The create route returned HTTP 202 with `PENDING`, the nested poll
route observed `RUNNING` and `COMPLETED`, and the client printed the persisted
model result. The returned session was `background-run-session`.

---

### cancel_run.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Started the checked-in cancellable AgentOS server and used
the checked-in `--demo` client to submit a long OpenAI Responses `gpt-5.5`
request, cancel it, and poll its persisted state.

**Result:** The create route returned HTTP 202 with `PENDING`, the nested
cancel route returned HTTP 200, and polling observed `RUNNING` followed by
`CANCELLED`. The final live run ID was
`1fa2c79e-588c-4268-aafe-f93520c50ede`.

---

### sse_reconnect.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran both checked-in raw-`httpx` clients against the live
OpenAI Responses `gpt-5.5` server: a new background SSE run and a
confirmation-paused run continued with `background=true`, `stream=true`.

**Result:** The new-run flow disconnected after `event_index=1`, received
`catch_up` and `subscribed` metadata, replayed indexed events `2..46`, and
ended at `RunCompleted`. The continue flow observed `RunPaused`, approved the
pending tool, disconnected after `RunContinued` and `ToolCallStarted`, replayed
indexed events `2..14`, and ended at `RunCompleted` after
`ToolCallCompleted`.

---

### checkpoints.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran the checked-in `checkpoint="tool-batch"` agent and HTTP
client with OpenAI Responses `gpt-5.5`. The model called
`get_city_fact` for Paris and Kyoto before answering.

**Result:** The nested checkpoint endpoint returned an interior
`message_index=5` checkpoint with `RUNNING` status and a terminal
`message_index=6` boundary. Posting `continue_from=5` created a completed
sibling run with the source run ID in `forked_from_run_id` and returned the
requested Paris-only response.

---

### hooks_in_background.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Ran both checked-in server modes with OpenAI Responses
`gpt-5.5`. The global mode exercised plain pre- and post-hooks under
`AgentOS(run_hooks_in_background=True)`. The mixed mode ran a blocking hook,
a blocking `AgentAsJudgeEval`, a decorated background notification, and a
background `AgentAsJudgeEval`.

**Result:** Both HTTP runs returned `COMPLETED`. In mixed mode, the blocking
completeness judge finished before the run response and reported a 100% pass
rate. The response then returned while the notification and background clarity
judge continued; the clarity judge also completed with a 100% pass rate and
persisted its eval run.

---

## Validation

- `pytest cookbook/scripts/tests/test_check_cookbook_pattern.py -q`:
  `3 passed`.
- Recursive pattern validation of this lesson: exactly 5 Python files checked,
  0 violations.
- All five apps imported and built their OpenAPI documents; the expected
  nested poll, cancel, resume, checkpoint, and continue routes were present.
- Targeted Ruff checks passed.
- Stale-model, deprecated checkpoint, emoji, and old-background-folder scans
  returned no target hits.
- `git diff --check` passed.
