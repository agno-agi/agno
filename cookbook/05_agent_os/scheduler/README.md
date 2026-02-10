# Scheduler Cookbooks

Examples for the AgentOS cron scheduler.

## Prerequisites

- Python 3.12+
- Optional deps: `pip install agno[scheduler]` (croniter, pytz)

## Examples

| File | Description |
|------|-------------|
| `basic_schedule.py` | Create a schedule, list schedules, display with Rich |
| `async_schedule.py` | Full async API: acreate, alist, aget, aupdate, adelete |
| `schedule_management.py` | Full CRUD lifecycle: create, list, disable, enable, update, delete |
| `schedule_validation.py` | Error handling: invalid cron, bad timezone, duplicate names, complex patterns |
| `multi_agent_schedules.py` | Multiple agents with different cron patterns, retries, timeouts |
| `team_workflow_schedules.py` | Scheduling teams, workflows, and non-run endpoints |
| `run_history.py` | Viewing run history with Rich, pagination, status analysis |
| `scheduler_with_agentos.py` | Full AgentOS with `scheduler=True` -- automatic polling and REST API |
| `rest_api_schedules.py` | Using the REST API directly (requires running server) |

## Running

```bash
# Standalone examples (no server needed)
.venvs/demo/bin/python cookbook/05_agent_os/scheduler/basic_schedule.py
.venvs/demo/bin/python cookbook/05_agent_os/scheduler/schedule_management.py
.venvs/demo/bin/python cookbook/05_agent_os/scheduler/run_history.py

# Server example (runs uvicorn)
.venvs/demo/bin/python cookbook/05_agent_os/scheduler/scheduler_with_agentos.py

# REST API example (requires server running in another terminal)
.venvs/demo/bin/python cookbook/05_agent_os/scheduler/rest_api_schedules.py
```
