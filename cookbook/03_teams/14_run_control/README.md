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

## AgentOS team run states

AgentOS exposes the lifecycle of a team run through the `status` field on the
run response and through team-specific stream events. Treat `run_id` and
`session_id` as the identifiers for every follow-up request; a run can remain
paused for an arbitrary amount of time while waiting for a human decision.

| State | Meaning | Typical next action |
|---|---|---|
| `PENDING` | A background run was accepted but has not started producing output. | Poll or subscribe to the run. |
| `RUNNING` | The team is processing the request. | Consume the response or stream events. |
| `PAUSED` | Human-in-the-loop requirements are unresolved; no pending tool call should be assumed to have completed. | Resolve the returned requirements, then call `/continue`. |
| `COMPLETED` | The team produced a terminal response. | Store the response or start a new/follow-up run. |
| `ERROR` | The run stopped because an error prevented completion. | Inspect the error and decide whether a new or continued run is appropriate. |
| `CANCELLED` | Cancellation was requested and the run stopped; partial content may still be persisted. | Do not retry blindly; start a new run when the operation is safe to repeat. |

For a non-streaming request, the team route is:

```http
POST /teams/{team_id}/runs
Content-Type: application/x-www-form-urlencoded

message=Summarize+the+latest+release&stream=false&session_id={session_id}
```

A completed response has the same lifecycle identifiers and a terminal status:

```json
{
  "run_id": "run-123",
  "session_id": "session-456",
  "status": "COMPLETED",
  "content": "The release adds ..."
}
```

With `stream=true`, the first and last lifecycle events are normally
`TeamRunStarted` and `TeamRunCompleted`. A human-in-the-loop run can instead
emit `TeamRunPaused` and return the unresolved `requirements` on the paused
run output:

```json
{
  "event": "TeamRunPaused",
  "run_id": "run-123",
  "session_id": "session-456",
  "status": "PAUSED",
  "requirements": [{"tool_name": "send_email", "requires_confirmation": true}]
}
```

After the human decision is recorded, resume the same team run. Pass the
resolved requirements back unchanged except for their resolution fields:

```http
POST /teams/{team_id}/runs/run-123/continue
Content-Type: application/x-www-form-urlencoded

session_id=session-456&stream=false&requirements=[...resolved requirements...]
```

Cancellation uses the same identifiers and is terminal for that run:

```http
POST /teams/{team_id}/runs/run-123/cancel
```

The stream may emit `TeamRunError` or `TeamRunCancelled`; the persisted run
output and its `status` remain the source of truth for the final state. The
existing examples in this directory show cancellation, background polling,
retry configuration, and continued runs with real model-backed teams.
