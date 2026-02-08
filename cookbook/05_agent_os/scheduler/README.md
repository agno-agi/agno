# Scheduler Cookbook

Examples for `scheduler` in AgentOS.

## Files
- `basic_schedule.py` — Basic scheduled agent run.
- `schedule_management.py` — Schedule management via REST API.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Some examples require local services (for example Postgres, Redis, Slack, or MCP servers).

Install scheduler dependencies:

```bash
pip install agno[scheduler]
```

This installs `croniter` and `pytz`.

## Examples

### basic_schedule.py

Minimal example: creates an AgentOS with a single agent and enables the scheduler. A schedule is created via the API that triggers the agent every 5 minutes.

### schedule_management.py

Demonstrates full CRUD lifecycle: creating, listing, updating, enabling/disabling, triggering, and deleting schedules via the REST API.

## Key Concepts

- **Cron expressions**: Standard 5-field cron syntax (minute, hour, day-of-month, month, day-of-week)
- **Timezones**: All schedules support timezone-aware scheduling via pytz
- **Retries**: Configurable retry count and delay for failed executions
- **Internal auth**: The scheduler authenticates to AgentOS using an auto-generated internal service token
- **Run history**: Every execution is tracked with status, timing, and error details

## Configuration

```python
AgentOS(
    agents=[my_agent],
    db=db,
    scheduler=True,                  # Enable the scheduler
    scheduler_poll_interval=15,      # Poll every 15 seconds (default)
    scheduler_base_url="http://127.0.0.1:7777",  # AgentOS base URL
)
```
