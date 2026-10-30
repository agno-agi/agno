# Test Log: suite

### suite_basic.py

**Status:** PASS

**Description:** Runs two cases (judge + reliability on a calculator agent, judge-only on a prose answer) through the built-in suite CLI. Tested `--list`, a full run with `--json-output`, and an unknown `--tag` selector.

**Result:** 2/2 cases passed with exit code 0. JSON payload written with the expected summary/cases shape. Unknown tag exited with code 2 and listed the available case names.

**Re-test (2026-07-05, after the external-review fix round):** full run with `--json-output` passed 2/2 with exit code 0 and the expected payload (`tools_called: ["factorial"]`, `status: "PASS"`); the falsy-check guard rejects `expected_tool_calls=()` at construction; the `python -m agno.eval` module entry is removed.

---

### suite_team_scoring.py

**Status:** PASS

**Description:** Runs two cases against one Team whose leader delegates to a calculator member and a writer member. The first case grades a numeric-scored arithmetic answer and checks the member's `multiply` tool; the second grades a numeric-scored explanation the leader delegates to the writer member. Exercised `--list`, `--list --json-output`, `--tag smoke`, `--name`, and a full run with `--json-output`, plus the programmatic `run_cases` and `arun_cases` entry points.

**Result:** 2/2 cases passed with exit code 0. Both cases carry `team_id: "assistant-team"` and `agent_id: null`. The arithmetic case's reliability saw the member's real tool (`tools_called: ["delegate_task_to_member", "multiply"]`) via `team_response=`, and both cases reported `judge_score: 10` in the payload.

---

### suite_session.py

**Status:** PASS

**Description:** Runs four cases against a booking agent whose tools read `session_state`. The first passes `session_state` and `user_id` on the case and asks for open slots. The second sets `session_id` and `user_id`, runs the first turn of the conversation in its `setup` hook, picks a slot, and deletes the session in `teardown`. The third passes no run arguments. The fourth gives a `Message` with an image (by URL) as the input, with `session_state` and `user_id`. Exercised a full run with `--json-output` and `--name books_the_chosen_slot`.

**Result:** 4/4 cases passed with exit code 0 (1/1 with `--name books_the_chosen_slot`). The first case reported `tools_called: ["get_open_slots"]` in a generated `eval-offers_open_slots-<hex>` session; the second reported `session_id: "booking-1"` with `tools_called: ["create_appointment"]`; the third offered no slots; the fourth named the Golden Gate Bridge and offered both slots with `tools_called: ["get_open_slots"]`.

---

### suite_api.py

**Status:** PASS

**Description:** Tested on 2026-10-28 using `.venv/bin/python` and FastAPI
TestClient in a temporary directory. Loaded the cookbook app, posted a calculator
suite, and retrieved the saved report. Agent streaming output was stubbed; the
HTTP route, actual suite runner, reliability evaluator, and SQLite persistence
were exercised. No external model calls were made.

**Result:** Suite returned PASS with one successful case and appeared in the
suite listing. Companion route tests cover permissions, owner isolation, invalid
inputs, selection, rerunnable definitions, and failed tool checks across in-memory,
sync SQLite, and async SQLite storage (42 tests passed). Live model behavior was
not tested.

---

### suite_api_smoke.py / suite_api_smoke.json

**Status:** PASS

**Description:** On 2026-10-28, ran all ten cases against the live Math Tutor
AgentOS at `http://localhost:7780`, using real model calls. Covered three tool-only
checks, six combined judge/tool checks, and one judge-only check, including numeric
judging, strict tool matching, and division-by-zero handling.

**Result:** 10/10 cases passed. Saved suite run
`203de479-e6ca-4107-b638-0d10596c1c88` in `suite-db` and verified the retrieved report
matches the local JSON report at `tmp/suite-api-smoke-result.json`. The fixture
also passed API schema validation and its Python runner passed Ruff checks.

---

### suite_api_samples.py / suite_api_samples.json

**Status:** PASS

**Description:** On 2026-10-28, validated all 12 sample payloads (24 cases) against
`EvalSuiteRunInput`, checked the Python runner with Ruff, and exercised `--list`.
The sample set includes nine intended passing suites and three intended failing
suites. Manual form-entry instructions are in `SAMPLE_SUITES.md`.

**Result:** All payloads validated, lint/format checks passed, and all 12 suite
names and intended statuses were listed. These sample suites have not been
executed against live models; PASS here refers to fixture and runner validation.

---

### suite_api_samples.json — live failure scenarios

**Status:** PASS

**Description:** On 2026-10-28, expanded suites 10-12 to three cases each
(27 total sample cases), validated every payload, and ran all three negative suites
against the live Math Tutor at port 7780. Verified each saved report via GET.
Covered wrong tools, a missing second required tool, forbidden additional tools,
binary judge failure, a numeric score below threshold, and combined check failure.

**Result:** All 9 cases matched their intended outcomes: 3 controls passed and
6 negative cases failed without runtime errors or timeouts. The numeric failure
scored 1 against a threshold of 8. All three suite statuses were FAIL as intended.
Schema validation, runner Ruff checks, and `--list` passed.

- Suite 10: `9db880ed-f552-4908-b6f9-94e47271bde3` — 1 control passed, 2 intentional failures.
- Suite 11: `c5c67599-3660-43e5-af23-be04bdfc891e` — 1 control passed, 2 intentional failures.
- Suite 12: `0160837b-cfff-4a89-a881-e08751df257a` — 1 control passed, 2 intentional failures.

---

### suite_api_failure_cases.json

**Status:** PASS

**Description:** On 2026-10-28, extracted the six previously live-verified
negative cases into a JSON array for the frontend case uploader. Validated the
array inside an `EvalSuiteRunInput` payload.

**Result:** All six cases validated with unique names and the Math Tutor target.
No additional live execution was performed for this copied fixture.

---
