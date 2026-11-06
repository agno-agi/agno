# Responsive Company conversation

Run the deterministic PostgreSQL example without a model provider or external calls:

```bash
DATABASE_URL=postgresql+psycopg://agno:agno@localhost:5532/agno \
  .venv/bin/python cookbook/05_agent_os/30_company/13_background_conversation/background_conversation.py
```

It creates an accepted Task through the Company API, submits a coordinator message,
and returns a durable receipt before running the coordinator. The Super Agent's
`submit_accepted_task` tool starts the Task through the existing execution API and
ends its turn with Task/run identifiers. The worker has a separate session. Status
and an unrelated message complete while the worker is deliberately held open.
The example uses a disposable database schema and removes it when finished.
Authentication is disabled only for this local example.

With a configured durable queue, send a JSON `message` to
`POST /company/conversations/{session_id}/messages`. An optional `Idempotency-Key`
reuses the same coordinator run for the same caller and conversation. The 202
receipt confirms coordinator submission; Task acceptance and dispatch are separate.
Turns in this conversation serialize even if the general queue permits parallel
session execution. Other conversations and Task workers run independently.

The coordinator can call `get_submitted_tasks`; HTTP clients can read
`GET /company/conversations/{session_id}/tasks`, optionally filtering `origin_run_id`.
Origins remain in Task transition history after queue retention and restart, including
multiple conversations joining the same existing attempt. Authenticated deployments
require the coordinator's team run permission, Task write/wiki read and executor run
permissions to dispatch, and Task read permission to inspect associated work.
Managed-role revocation is checked again before worker execution.

Generic agent/team endpoints remain available. The explicit conversation endpoint
provides the per-conversation serialization contract. This example does not steer
an active worker or deliver channel notifications. Successful execution leaves the
Task in review; automated acceptance and outcome assessment are separate lifecycle
operations.
