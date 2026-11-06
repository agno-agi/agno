# Managed Company lifecycle

This offline example sends a delegated request through the actual Company Manager API, creates an active Project and accepted Task, and submits it to the PostgreSQL queue. The worker writes and reads an artifact. The assessment requests one revision, then completes the same Task/session and its Project. An unrelated conversation turn completes before the worker starts.

```bash
DATABASE_URL=postgresql+psycopg://agno:agno@localhost:5532/agno .venv/bin/python cookbook/05_agent_os/30_company/14_managed_lifecycle/managed_lifecycle.py
```

Use a disposable database: the example creates and drops its own unique schema. It uses deterministic local model fixtures and explicitly drives the existing queue worker, with no paid model calls. The local example has authentication disabled. Integration tests also exercise this path through managed platform roles, including revocation and permission denials.

For deployment, configure `scheduler=True`, a durable PostgreSQL queue, and a registered executor. `CompanyConfig(model=OpenAIResponses(id="gpt-5.6-luna"), max_task_attempts=3)` provides the manager and outcome assessor. Running a configured provider makes model calls. The limit includes the original attempt, and accepts integers from 1 through 10. Normal lifecycle management uses the caller's existing Product, Project, Task, wiki and executor permissions; it does not grant new authority. The saved authorization is checked again when work resumes.

Only the framework Company Manager receives the explicit activation, acceptance and delegation tools. Ordinary Company tools and Routines retain their existing constraints. System decisions and the actual authorizing identity are recorded in transition history. The completed worker's persisted output and tool results are assessed against the requested outcome; successful run status alone does not complete work.

Missing inputs, invalid verification and exhausted revisions return the Task to Backlog with a reason. Cancellation and revoked authority stop management. Existing Company scheduler reconciliation resumes after an interrupted completion. Defined dependent sequences belong in Workflows; these tools delegate independent Tasks. Channel-specific delivery is separate from lifecycle assessment.
