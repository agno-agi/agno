# Eval Suite Cookbooks

Suite examples run multiple eval cases as one aggregated suite with tag selection, per-case timeouts, a JSON report, and CI exit codes.

## Files

- `suite_basic.py` - Two cases (judge + reliability checks) run through the built-in `cli()`.
- `suite_team_scoring.py` - A Team run through the suite (the leader delegates to a calculator member and a writer member); reliability sees the members' tool calls, and every answer is graded by a numeric 1-10 judge.
- `suite_session.py` - Cases that pass `session_state` and `user_id` to the run, and a case that continues a session (`session_id`) whose earlier turn runs in its `setup` hook, to check a two-turn booking conversation; the last case sends an image with its turn by giving a `Message` as the input.

## Usage

```bash
python cookbook/09_evals/suite/suite_basic.py                 # run all cases
python cookbook/09_evals/suite/suite_basic.py --list          # list cases without running
python cookbook/09_evals/suite/suite_basic.py --tag smoke     # run a tagged subset
python cookbook/09_evals/suite/suite_basic.py --name factorial_uses_calculator
python cookbook/09_evals/suite/suite_basic.py --json-output tmp/evals.json
python cookbook/09_evals/suite/suite_basic.py -v              # full run panels per case
```

For programmatic use (CI workflows, embedding), call `run_cases(CASES)` or `await arun_cases(CASES)` instead and read `SuiteResult.to_dict()` - the runner does no console I/O.

## AgentOS frontend and API

`suite_api.py` serves a calculator agent with a local development database. Set
`OPENAI_API_KEY`, start the server, connect the frontend, and open **Evaluations >
Suites > New Suite**. Add named cases, select an agent or team for each, and configure judge
criteria, expected tool calls, or both. Cases support tags, binary or numeric judge
checks, timeout overrides, and optional tag/name selection. SQLite is for local
development; use PostgreSQL in production.

```bash
.venv/bin/python cookbook/09_evals/suite/suite_api.py
curl -X POST 'http://localhost:7777/eval-suites?db_id=suite-db' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Calculator smoke","cases":[{"name":"sum","agent_id":"math-tutor","input":"What is 2 + 2? Use the calculator.","expected_tool_calls":["add"],"tags":["smoke"]}]}'
```

`POST /eval-suites` executes cases sequentially and saves one aggregate evaluation
run. `GET /eval-suites` lists suite runs with `page`, `limit`, `db_id`, and `table`;
`GET /eval-suites/{id}` retrieves a report. Responses use the existing evaluation
record envelope, with the runner's `summary` and `cases` in `eval_data`, and the
submitted definition in `eval_input`. The shared `/eval-runs` endpoints support
`eval_types=suite`, rename, and deletion. The frontend separates standalone evaluations and suites into tabs, and supports rerunning a saved
definition, inspecting per-case evidence, filtering failed cases, and exporting
its JSON report.

With authorization enabled, reads require `evals:read`, execution requires
`evals:write` plus run access to every selected target, and deletion requires
`evals:delete`. Send your bearer token in the Authorization header. Stored suites
follow the configured user isolation policy. `db_id` and `table` select storage.

The HTTP editor supports declarative judge and tool checks against local Agno
agents/teams. Python scorers, lifecycle callbacks, custom judge model objects, and
remote components remain available through the Python runner where supported;
the HTTP request does not accept executable code. A suite run is a saved report
and rerunnable definition, not a separately editable or scheduled suite resource.

## Ten-case API smoke suite

`suite_api_smoke.json` contains ten Math Tutor cases: addition, subtraction,
multiplication, division, exponentiation, factorial, prime checking, square roots,
division by zero, and a plain-language explanation of prime numbers. Three cases
check tools only, six combine tool checks with judging, and one uses judging only.
Two cases use numeric judging with a passing threshold of 8. Strict tool matching
and tags exercise selection and reliability options.

With `suite_api.py` running, execute:

```bash
.venv/bin/python cookbook/09_evals/suite/suite_api_smoke.py
# For the local test server on port 7780:
.venv/bin/python cookbook/09_evals/suite/suite_api_smoke.py --url http://localhost:7780
# Run just the three tool-only cases:
.venv/bin/python cookbook/09_evals/suite/suite_api_smoke.py --url http://localhost:7780 --tag reliability
```

The script makes live model calls through the server, saves one suite run in
`suite-db`, and writes the full response to `tmp/suite-api-smoke-result.json`.
It exits with code 1 if any case fails. Open **Evaluations > Suites** to inspect
`Math Tutor - 10-case smoke suite`, or rerun it from the frontend. These are positive
smoke cases: a failed case should be investigated, not treated as an expected failure.

## Twelve sample suites for UI testing

See [SAMPLE_SUITES.md](SAMPLE_SUITES.md) for field-by-field inputs for 12 suites
with 27 cases. [suite_api_samples.json](suite_api_samples.json) contains their API
payloads and intended outcomes. Nine suites are expected to pass; the final three
each contain one positive control and two intentional failures for testing failure displays.
These cover missing or wrong tools, forbidden extra tools, binary and numeric judge
failures, and combined judge/tool failures. Use the `negative` tag in the UI subset
filter to run only failing cases. Use
`suite_api_samples.py --list` to browse, `--suite 1` to run one, or omit both to
execute all twelve. Set `--url http://localhost:7780` for the local test server.
These sample definitions are validated against the HTTP schema; model-dependent
outcomes can vary.
