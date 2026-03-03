# Scheduling

Agno supports scheduled agent and workflow execution via a built-in scheduler integrated into `AgentOS`. Agents can run on cron schedules, at fixed intervals, or be triggered by time-based events.

**Directory:** `libs/agno/agno/scheduler/`
**Cookbook:** `cookbook/05_agent_os/scheduler/`

---

## Overview

The scheduler runs as part of `AgentOS`. When `scheduler=True` is set, AgentOS polls for due schedules and executes them automatically.

```
AgentOS startup
    │
    ▼
ScheduleManager initialised
    │
    ▼
SchedulePoller runs every N seconds
    │
    ▼
For each schedule whose next_run <= now:
    ├── invoke the registered agent/workflow endpoint
    └── update next_run based on cron expression
```

---

## Basic schedule

**Cookbook:** `cookbook/05_agent_os/scheduler/basic_schedule.py`

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

db = PostgresDb(
    id="scheduler-demo-db",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

greeter = Agent(
    id="greeter",
    name="Greeter Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["You are a friendly greeter. Say hello and include the current time."],
    db=db,
    markdown=True,
)

app = AgentOS(
    agents=[greeter],
    db=db,
    scheduler=True,
    scheduler_poll_interval=15,   # check for due schedules every 15 seconds
).get_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7777)
```

Then create a schedule via the REST API:

```bash
curl -X POST http://localhost:7777/schedules \
    -H "Content-Type: application/json" \
    -d '{
        "name": "greeting-every-5m",
        "cron_expr": "*/5 * * * *",
        "endpoint": "/agents/greeter/runs",
        "payload": {"message": "Say hello!"}
    }'
```

---

## Cron expressions

Standard cron syntax:

```
┌─────── minute  (0-59)
│ ┌───── hour    (0-23)
│ │ ┌─── day     (1-31)
│ │ │ ┌─ month   (1-12)
│ │ │ │ ┌ weekday (0-6, Sun=0)
│ │ │ │ │
* * * * *
```

Examples:

| Cron | Meaning |
|------|---------|
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Every hour |
| `0 9 * * 1-5` | 9 AM Monday–Friday |
| `0 0 * * *` | Daily at midnight |
| `0 9 1 * *` | First day of each month at 9 AM |
| `30 18 * * 5` | Every Friday at 6:30 PM |

---

## Multi-agent schedules

**Cookbook:** `cookbook/05_agent_os/scheduler/multi_agent_schedules.py`

```python
from agno.os import AgentOS
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url=DB_URL)

app = AgentOS(
    agents=[
        morning_brief_agent,    # id="morning-brief"
        eod_report_agent,       # id="eod-report"
        weekly_summary_agent,   # id="weekly-summary"
    ],
    db=db,
    scheduler=True,
).get_app()
```

After starting, create separate schedules for each:

```bash
# Morning brief at 8 AM weekdays
curl -X POST http://localhost:7777/schedules \
    -d '{"name": "morning-brief", "cron_expr": "0 8 * * 1-5", "endpoint": "/agents/morning-brief/runs", "payload": {"message": "Generate today briefing"}}'

# EOD report at 5 PM weekdays
curl -X POST http://localhost:7777/schedules \
    -d '{"name": "eod-report", "cron_expr": "0 17 * * 1-5", "endpoint": "/agents/eod-report/runs", "payload": {"message": "Generate EOD report"}}'

# Weekly summary every Sunday at 7 PM
curl -X POST http://localhost:7777/schedules \
    -d '{"name": "weekly-summary", "cron_expr": "0 19 * * 0", "endpoint": "/agents/weekly-summary/runs", "payload": {"message": "Summarise this week"}}'
```

---

## Schedule management via REST API

**Cookbook:** `cookbook/05_agent_os/scheduler/schedule_management.py`

```bash
# List all schedules
GET /schedules

# Get a specific schedule
GET /schedules/{schedule_id}

# Create a schedule
POST /schedules
{
    "name": "my-schedule",
    "cron_expr": "0 9 * * *",
    "endpoint": "/agents/my-agent/runs",
    "payload": {"message": "Run daily task"},
    "enabled": true
}

# Update a schedule
PUT /schedules/{schedule_id}
{
    "cron_expr": "0 10 * * *",   # change to 10 AM
    "enabled": true
}

# Pause a schedule
PUT /schedules/{schedule_id}
{"enabled": false}

# Delete a schedule
DELETE /schedules/{schedule_id}
```

---

## Schedule validation

**Cookbook:** `cookbook/05_agent_os/scheduler/schedule_validation.py`

```python
from agno.scheduler import CronSchedule

# Validate a cron expression
cron = CronSchedule(expr="0 9 * * 1-5")
print(f"Next run: {cron.next_run()}")
print(f"Next 5 runs: {cron.next_n_runs(5)}")
print(f"Is valid: {cron.is_valid()}")
```

---

## Schedule history / run logs

**Cookbook:** `cookbook/05_agent_os/scheduler/run_history.py`

```bash
# Get run history for a schedule
GET /schedules/{schedule_id}/runs?limit=20

# Get all scheduled runs across all schedules
GET /schedules/runs?status=success&limit=50
```

---

## Workflow scheduling

**Cookbook:** `cookbook/05_agent_os/scheduler/team_workflow_schedules.py`

Workflows can also be scheduled:

```bash
POST /schedules
{
    "name": "weekly-pipeline",
    "cron_expr": "0 2 * * 1",
    "endpoint": "/workflows/data-pipeline/runs",
    "payload": {"trigger": "weekly-batch"}
}
```

---

## Async scheduling

**Cookbook:** `cookbook/05_agent_os/scheduler/async_schedule.py`

For long-running agents, use async execution to avoid blocking the scheduler:

```python
app = AgentOS(
    agents=[long_running_agent],
    db=db,
    scheduler=True,
    scheduler_poll_interval=30,
    scheduler_async=True,        # run scheduled agents asynchronously
).get_app()
```

---

## Scheduler internals

**Files:**

| File | Purpose |
|------|---------|
| `scheduler/manager.py` | Create, update, delete, list schedules |
| `scheduler/executor.py` | Execute due schedules |
| `scheduler/poller.py` | Periodic polling loop (runs in background thread) |
| `scheduler/cron.py` | Parse and evaluate cron expressions |
| `scheduler/cli.py` | CLI commands for schedule management |

### Polling mechanism

```python
# The poller runs as a background asyncio task:
async def poll_loop():
    while True:
        due_schedules = await manager.get_due_schedules()
        for schedule in due_schedules:
            await executor.execute(schedule)
        await asyncio.sleep(poll_interval)
```

### Schedule states

| State | Meaning |
|-------|---------|
| `enabled=True` | Schedule is active and will run |
| `enabled=False` | Schedule is paused |
| `last_run` | Timestamp of last execution |
| `next_run` | Calculated from cron + last_run |
| `run_count` | Total number of executions |
| `error_count` | Number of failed executions |

---

## Environment variable override

```bash
# Override poll interval without code changes
AGNO_SCHEDULER_POLL_INTERVAL=60  # check every minute

# Disable scheduler in testing
AGNO_SCHEDULER_ENABLED=false
```

---

## Example: Daily report agent

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.postgres import PostgresTools
from agno.os import AgentOS
from agno.db.postgres import PostgresDb

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

report_agent = Agent(
    id="daily-report",
    name="Daily Report Generator",
    model=OpenAIChat(id="gpt-4o"),
    tools=[PostgresTools(db_url=DB_URL)],
    instructions=[
        "Generate a daily business report.",
        "Query the database for yesterday's key metrics.",
        "Format as a concise executive summary.",
    ],
    db=PostgresDb(table_name="report_sessions", db_url=DB_URL),
)

app = AgentOS(
    agents=[report_agent],
    db=PostgresDb(table_name="agno_schedules", db_url=DB_URL),
    scheduler=True,
).get_app()

# Create the schedule once after first startup:
# POST /schedules {"name": "daily-report", "cron_expr": "0 7 * * *", ...}
```
