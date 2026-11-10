# Run Control

Controlling a team run: cancelling one mid-flight, running one in the background
and polling it, retrying transient errors, inheriting a model across members, and
calling a team hosted on another AgentOS.

Seven of these drive the team object in process; `remote_team.py` is the one that
goes over HTTP. Pausing a team for a human decision lives in
[`../20_human_in_the_loop/`](../20_human_in_the_loop/), and the same run control
driven through AgentOS routes lives in
[`cookbook/05_agent_os/04_run_lifecycle`](../../05_agent_os/04_run_lifecycle/).

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- Some examples require additional services (for example PostgreSQL, LanceDB, or Infinity server) as noted in file docstrings.

## Examples

| Example | What it shows | Needs |
|---|---|---|
| [`cancel_run.py`](./cancel_run.py) | Cancel an in-flight team run from a separate thread. | — |
| [`cancel_run_persistence.py`](./cancel_run_persistence.py) | Cancel mid-stream and verify partial content and messages are preserved in the database. | PostgreSQL |
| [`team_cancel_while_member_runs.py`](./team_cancel_while_member_runs.py) | Cancel a team run while a member agent is actively streaming; the cancellation propagates and both runs persist as cancelled. | PostgreSQL |
| [`background_execution.py`](./background_execution.py) | Start a run that returns immediately as `PENDING`, then poll for completion or cancel it. | PostgreSQL |
| [`background_execution_metrics.py`](./background_execution_metrics.py) | Metrics are tracked for team background runs and read back off the stored run. | PostgreSQL |
| [`model_inheritance.py`](./model_inheritance.py) | Member models inherit from the parent team's model. | — |
| [`remote_team.py`](./remote_team.py) | Call and stream a team hosted on a remote AgentOS instance. | AgentOS on `:7778` |
| [`retries.py`](./retries.py) | Team retry configuration for transient run errors. | — |

## Running

```bash
.venvs/demo/bin/python cookbook/03_teams/14_run_control/cancel_run.py
.venvs/demo/bin/python cookbook/03_teams/14_run_control/model_inheritance.py
.venvs/demo/bin/python cookbook/03_teams/14_run_control/retries.py
```
