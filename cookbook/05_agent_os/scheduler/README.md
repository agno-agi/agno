# AgentOS Scheduler

The AgentOS scheduler provides cron-based task scheduling for agents, teams, workflows, and arbitrary endpoints.

## Features

- **Cron-based scheduling**: Schedule tasks using standard cron expressions
- **Timezone support**: Configure schedules in any timezone
- **Distributed locking**: Safe execution in multi-container deployments (PostgreSQL)
- **Retry logic**: Configurable retry attempts with delay
- **Manual triggers**: Trigger schedules on-demand via API
- **Execution tracking**: Track run history, status, and errors
- **SSE streaming**: Non-blocking execution with real-time status tracking

## Quick Start

```python
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Create an agent
agent = Agent(
    id="daily-reporter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Generate a daily report.",
)

# Create AgentOS with scheduler enabled
db = SqliteDb(db_file="scheduler.db")
agent_os = AgentOS(
    agents=[agent],
    db=db,
    enable_scheduler=True,  # Enable the scheduler
    scheduler_poll_interval=30,  # Check for due schedules every 30 seconds
)

# Run the server
app = agent_os.get_app()
agent_os.serve(app, port=7777)
```

## Creating Schedules via API

Once the server is running, create schedules using the REST API:

```bash
# Create a schedule that runs an agent daily at 3 AM
curl -X POST http://localhost:7777/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "daily-report",
    "endpoint": "/agents/daily-reporter/runs",
    "method": "POST",
    "payload": {"message": "Generate the daily report"},
    "cron_expr": "0 3 * * *",
    "timezone": "America/New_York"
  }'
```

## Cron Expression Reference

| Expression | Description |
|------------|-------------|
| `* * * * *` | Every minute |
| `0 * * * *` | Every hour |
| `0 0 * * *` | Every day at midnight |
| `0 3 * * *` | Every day at 3 AM |
| `0 0 * * 0` | Every Sunday at midnight |
| `0 0 1 * *` | First day of every month |
| `*/5 * * * *` | Every 5 minutes |
| `0 9-17 * * 1-5` | Every hour 9 AM-5 PM, Mon-Fri |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/schedules` | List all schedules |
| POST | `/schedules` | Create a new schedule |
| GET | `/schedules/{id}` | Get a specific schedule |
| PATCH | `/schedules/{id}` | Update a schedule |
| DELETE | `/schedules/{id}` | Delete a schedule |
| POST | `/schedules/{id}/enable` | Enable a schedule |
| POST | `/schedules/{id}/disable` | Disable a schedule |
| POST | `/schedules/{id}/trigger` | Manually trigger a schedule |
| GET | `/schedules/{id}/runs` | Get run history |
| GET | `/schedules/{id}/runs/{run_id}` | Get a specific run |

## Examples

- `01_basic_scheduler.py` - Basic scheduler setup with SQLite
- `02_schedule_agent_runs.py` - Schedule agent executions
- `03_schedule_workflow.py` - Schedule workflow executions
- `04_async_scheduler.py` - Async database support
- `05_manual_trigger.py` - Manually trigger schedules via API

## Requirements

Install the scheduler dependencies:

```bash
pip install agno[scheduler]
```

This installs the `croniter` package required for cron expression parsing.

## Production Considerations

1. **Use PostgreSQL**: For multi-container deployments, use PostgreSQL which supports `SELECT FOR UPDATE SKIP LOCKED` for atomic schedule claiming.

2. **External Scheduler**: For high-availability, consider using external schedulers (Kubernetes CronJobs, AWS EventBridge) that call the AgentOS trigger endpoint.

3. **Authentication**: The scheduler uses an internal service token for scheduled HTTP calls. This token is accepted by OS security-key auth, and (when JWT middleware/RBAC is enabled) is treated as an internal admin token so schedules keep working. Keep this token secret.
