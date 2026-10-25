# Background tasks

- `durable_queue.py`: submit, poll, stream and recover durable background runs.
- `durable_continue.py`: resume a paused run through its durable queue ticket.
- `redis_event_stream.py`: share queued-run events across replicas.

Run `durable_queue.py` with PostgreSQL available and `OPENAI_API_KEY` set. Set
`DATABASE_URL` to override the example's local PostgreSQL connection.

## Startup and run logs

The durable PostgreSQL worker creates its jobs table before polling when AgentOS
`auto_provision_dbs=True` (the default). An idle queue produces no routine polling
messages. Set `auto_provision_dbs=False` for an externally managed schema. Stores
without the optional `ensure_jobs_table()` hook retain read-only startup priming.
A preparation failure is reported; the existing lazy enqueue path remains
available, but queue operations may fail until storage is provisioned.

Agno prints plain, unwrapped log lines to container/file output and retains Rich
formatting in interactive terminals and Jupyter notebooks. Custom application
loggers are preserved. Set `AGNO_DEBUG=True` for workflow lifecycle summaries,
including workflow/run IDs, session and step information, and the actual outcome.
Set `AGNO_DEBUG_LEVEL=2` for detailed preparation and storage diagnostics.

Connection pool health checks stay enabled. To diagnose pool activity explicitly:

```python
import logging

logging.basicConfig()
logging.getLogger("sqlalchemy.pool").setLevel(logging.DEBUG)
```

Alternatively, pass `echo_pool="debug"` to `create_postgres_engine`. Routine
Agno debug output does not enable connection checkouts, pre-pings or resets.

Example workflow output with `AGNO_DEBUG=True`:

```text
INFO    Workflow queued: sync-docs run=<run-id>
DEBUG   Session: <session-id>
DEBUG   Workflow started: sync-docs run=<run-id>
DEBUG   Step started: sync-docs step=1/1 streaming=true
DEBUG   Workflow completed: sync-docs run=<run-id> duration=2.31s
```

Debug summaries report `Workflow failed`, paused, or cancelled as appropriate.
Existing execution errors remain visible without debug logging. A successful
health/status HTTP request is not workflow completion.
