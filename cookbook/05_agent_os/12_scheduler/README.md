# Scheduler

AgentOS can persist cron schedules, claim due work, call an AgentOS endpoint,
and store each execution attempt. This lesson covers the four ways operators
usually meet that surface: natural execution, REST, direct Python management,
and an agentic `SchedulerTools` path.

## Files

| File | What it teaches |
|---|---|
| `01_run_in_agentos.py` | Seed a Postgres schedule before serving, let the poller claim it naturally, and observe persisted history. |
| `02_rest_api.py` | Use raw HTTP for CRUD, enable/disable, manual trigger, and `{data, meta}` pagination. |
| `03_manage_with_python.py` | Use sync and async `ScheduleManager` APIs, including `page`, `cron_expr`, validation, retry, and timeout settings. |
| `04_scheduler_tools_agent.py` | Let an agent create a schedule while preserving a configured default endpoint and payload. |

## Prerequisites

Start Postgres and export an OpenAI key:

```bash
./cookbook/scripts/run_pgvector.sh
export OPENAI_API_KEY=...
```

`03_manage_with_python.py` does not call a model and only needs Postgres.
The other examples make live `gpt-5.5` calls.

## Natural execution

Start the scheduler-enabled server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/01_run_in_agentos.py
```

In another terminal, start the observer:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/01_run_in_agentos.py --demo
```

The server creates a fresh `* * * * *` schedule before startup. It does not
force the row due before the HTTP listener exists. The poller checks every five
seconds, claims the next naturally due minute, calls the agent as a background
non-streaming run, and persists the result. The observer waits up to 200
seconds for a new `success` history row, covering the minute boundary, poll
interval, configured 120-second run timeout, and a small margin.

With that server still running, exercise the REST surface:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/02_rest_api.py
```

The list and history routes return an object with `data` and `meta`; they do
not return a bare list. Pagination uses `page`, not `offset`.

## Python management

Run the standalone manager walkthrough:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/03_manage_with_python.py
```

`ScheduleManager.create()` accepts `cron`, but direct updates pass database
field names, so a cron update is `cron_expr="..."`. The example disables the
row, updates `cron_expr`, and enables it again so `next_run_at` is recomputed.
Both synchronous `PostgresDb` and genuine `AsyncPostgresDb` paths run.

## SchedulerTools

Stop the first server, then start the tools example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/04_scheduler_tools_agent.py
```

In another terminal:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/04_scheduler_tools_agent.py --demo
```

The agent calls `create_schedule` from natural language. A small
`SchedulerTools` subclass narrows the agent-facing create schema so callers
cannot override its execution target. The client reads the stored row back and
proves that the toolkit used the canonical
`/agents/scheduler-tools-agent/runs` endpoint and its complete default payload.

## Deployment notes

- `scheduler_base_url` is the URL the in-process executor calls. It defaults to
  `http://127.0.0.1:7777`; set it explicitly when AgentOS listens elsewhere.
- When scheduling is enabled, AgentOS creates an internal service token unless
  `internal_service_token` is supplied. The executor sends it as a bearer
  credential. Keep an explicitly supplied value secret; it is for
  scheduler-to-AgentOS traffic, not an end-user API key.
- SQLite supports local development and one local scheduler process. Use
  Postgres when multiple AgentOS workers share schedules: its claim uses an
  atomic update around a `FOR UPDATE SKIP LOCKED` selection so workers do not
  execute the same due row.
- Run endpoints must receive a `message` in their payload. The executor forces
  scheduled Agent, Team, and Workflow calls to `stream=false` and
  `background=true`, then polls the persisted run until it reaches a terminal
  state.
