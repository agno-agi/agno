# run control

Examples for team workflows in run_control.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- Some examples require additional services (for example PostgreSQL, LanceDB, or Infinity server) as noted in file docstrings.

## Files

- cancel_run.py - Demonstrates cancel run.
- cancel_run_persistence.py - Cancel a running team and verify partial content is persisted.
- team_cancel_while_member_runs.py - Cancel a team run while a member agent is actively streaming.
- background_execution.py - Demonstrates background execution and polling.
- model_inheritance.py - Demonstrates model inheritance.
- remote_team.py - Demonstrates remote team.
- retries.py - Demonstrates retries.
