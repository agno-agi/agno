# AgentOS Cookbook Test Prompt

Thoroughly test the currently published AgentOS curriculum: root `basic.py`
and numbered lessons `01_getting_started` through `04_run_lifecycle`.

## Read first

- `AGENTS.md`
- `cookbook/STYLE_GUIDE.md`
- `cookbook/05_agent_os/README.md`
- Every Python file, README, and TEST_LOG in the root and lessons 01–04

Do not infer behavior from filenames or old test results. Verify parameters,
client methods, endpoints, form fields, and response shapes against
`libs/agno/agno` before changing an example.

## Environment

- Cookbook Python: `.venvs/demo/bin/python`
- Development checks: `.venv`
- Environment variables: load with `direnv allow` when available
- Postgres: `./cookbook/scripts/run_pgvector.sh`
- SurrealDB: `./cookbook/scripts/run_surrealdb.sh`

Use `tmp/` only for runtime artifacts. Remove generated databases,
`__pycache__`, and temporary server output when the run is complete.

## Result contract

Every Python file needs a dated entry in the nearest TEST_LOG with:

- `Status: PASS`
- `Test mode: LIVE` or `Test mode: CONSTRUCTION_SMOKE`
- The command or behavior tested
- Concrete observed output

`CONSTRUCTION_SMOKE` is reserved for credential-gated examples. It must prove
imports, object construction, app construction, and the expected registered
route. State which credentials were missing and what was not exercised.
Never leave a final FAIL, MANUAL, PENDING, unexecuted placeholder, or
fabricated success entry.

For each credentials-free server, boot it, assert `GET /health` returns 200,
inspect `GET /config`, and terminate it. For every client/server pair, run both
halves and record both observations.

## Lesson checks

### Root and 01_getting_started

- Root `basic.py`: verify `/health`, `/config`, the `agno-assist` agent, and
  MCP tool discovery.
- `full_os.py`: verify the agent, team, workflow, knowledge, sessions, and
  config surfaces are present.
- `run_over_http.py`: start `full_os.py`, then observe config discovery, a
  non-streaming run, SSE events, and the persisted session.

### 02_databases

- `basic.py`: verify the OS-level SQLite database is inherited by the agent
  and auto-provisioned.
- `postgres.py`: start pgvector and test both the sync and async database
  variants.
- `surreal.py`: start SurrealDB and observe a real persisted session.
- Confirm the README backend table uses real imports and constructor shapes,
  labels ClickHouse as traces-only, and documents `/databases/{id}/migrate`.

### 03_python_client

- Start `_server.py` on port 7778.
- Run clients 01–06 against it, including sync and async config, typed run
  streaming, session and memory CRUD, the complete knowledge lifecycle, eval
  result reads, and authenticated calls.
- Exercise both unauthenticated and `OS_SECURITY_KEY` modes where directed.

### 04_run_lifecycle

- Observe `background=true` plus `stream=false` return 202 with a database,
  then poll the nested run route with `session_id`.
- Start and cancel a long background run and observe its final status.
- Resume an interrupted SSE stream with the raw-httpx workaround.
- Use `checkpoint="tool-batch"`, list checkpoints, and continue from a
  selected `message_index`.
- Observe blocking and background hook/eval behavior.

## Required validation

```bash
.venv/bin/pytest cookbook/scripts/tests/test_check_cookbook_pattern.py

.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/01_getting_started --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/02_databases --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/03_python_client --recursive
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py \
  --base-dir cookbook/05_agent_os/04_run_lifecycle --recursive

source .venv/bin/activate
./scripts/format.sh
./scripts/validate.sh
git diff --check
```

Also reject stale models, deprecated AgentOS/MCP names, emojis, and non-final
test statuses in the root and lessons 01–04. Report exact commands, observed
results, live-versus-construction coverage, and any library follow-up.
