# Scheduler Cookbooks

Examples for the AgentOS cron scheduler.

## Prerequisites

- Python 3.12+
- PostgreSQL running (or use SQLite for dev)
- Optional deps: `pip install agno[scheduler]`

## Examples

| File | Description |
|------|-------------|
| `basic_schedule.py` | Create a schedule, list schedules, and display with Rich |
| `schedule_management.py` | Full CRUD demo: create, list, update, trigger, view runs, delete |

## Running

```bash
# Start Postgres (if needed)
./cookbook/scripts/run_pgvector.sh

# Run a cookbook
.venvs/demo/bin/python cookbook/05_agent_os/scheduler/basic_schedule.py
.venvs/demo/bin/python cookbook/05_agent_os/scheduler/schedule_management.py
```
