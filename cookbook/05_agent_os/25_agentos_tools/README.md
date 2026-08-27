# AgentOS Tools

AgentOSTools gives an agent a read-only ops view of the AgentOS it runs on:
usage, latency, failures, tool statistics, schedules, eval history, pending
approvals and runtime-built components. The toolkit takes the database, never
the AgentOS instance — agents are constructed before the OS, so every tool
reads only from `db`.

## Files

| File | What it teaches |
|---|---|
| `platform_ops_agent.py` | Generate traced activity with a worker agent, then answer platform questions with an ops agent using AgentOSTools. |

## Prerequisites

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
```

## Run platform_ops_agent.py

```bash
.venvs/demo/bin/python cookbook/05_agent_os/25_agentos_tools/platform_ops_agent.py
```

The demo runs the worker agent twice, verifies the activity is visible through
the toolkit (run counts, tool statistics, session metrics), then asks the ops
agent for a platform summary.

## Notes

- No tool mutates platform state; schedule, approval and component management
  are deliberately not exposed. The one write is the metrics rollup refresh
  inside `get_platform_metrics` (derived data, no user content). The tools read
  the database directly, so AgentOS endpoint scopes do not apply — expose the
  ops agent to operators, and trim surfaces with the enable flags for wider
  audiences.
- Sensitive payloads are never returned: span attributes, approval tool
  arguments and schedule run input/output can hold conversation content and are
  excluded from every tool result.
- Per-surface flags (`metrics`, `traces`, `schedules`, `evals`, `components`,
  `approvals`) control which tools a deployment exposes.
- On SQLite, `p95_duration_ms` is reported as null (no SQL percentile support);
  PostgreSQL reports real percentiles. The payload says so when it applies.
