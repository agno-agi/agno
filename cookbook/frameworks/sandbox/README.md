# Session sandboxes for coding agents

Run Claude Code or Codex in a container belonging to one session. AgentOS serves
requests, stores runs, and dispatches durable queue tickets. The sandbox runs the
harness and owns its queue lease, so restarting AgentOS does not stop its work.
Postgres stores sessions, transcripts, tickets and bindings. Redis carries events
and cancellation between the runtime and every API replica.

## Run the deterministic acceptance test

Requires Docker with Compose and Python with `httpx`. No model keys or hosted
sandbox account are needed. From the repository root:

```bash
docker compose -f cookbook/frameworks/sandbox/compose.yaml up --build -d
.venvs/demo/bin/python cookbook/frameworks/sandbox/verify.py
```

The fixture starts Postgres, Redis, a private test Git remote and two AgentOS
replicas at `http://localhost:18781` and `http://localhost:18782`. A deterministic
harness executes inside the same runtime used by Claude; the actual Docker,
Postgres, Redis, HTTP routing, queue handoff and Git checkpoints are exercised.
The script checks:

1. First turn and pushed workspace checkpoint.
2. Client disconnect and API restart while a run is active.
3. Event replay through the other replica.
4. Foreground responses and foreground streaming.
5. Subsequent turns with conversation history and workspace contents.
6. Cancellation of a claimed turn waiting behind another turn.
7. Cross-replica cancellation.
8. Container death followed by a fresh-container retry.
9. Exhausted retries ending in ERROR with the provider's reason.
10. Idle destruction followed by workspace restoration.
11. Session deletion destroying its sandbox.

The test creates isolated session IDs. Sandboxes expire after 15 idle seconds;
wait for them to disappear before removing the stack:

```bash
docker compose -f cookbook/frameworks/sandbox/compose.yaml down
```

The stack's database and Git remote are disposable. `down` removes their test data.
These fixed ports and network name allow one copy of the example at a time.

## Real Claude acceptance

Export `ANTHROPIC_API_KEY` in your shell, then:

```bash
docker compose -f cookbook/frameworks/sandbox/compose.yaml \
  -f cookbook/frameworks/sandbox/compose.live.yaml up --build -d
.venvs/demo/bin/python cookbook/frameworks/sandbox/verify_live.py
```

This makes two real Claude calls, each with `max_budget_usd=2`, `max_turns=8`, and
one queue attempt. It writes a file, destroys the container, and checks that a
fresh container recalls a random conversation fact and reads the restored file.
The SDK's budget is a turn budget; it is not an account billing limit. The adapter
does not currently expose cost metrics in `RunOutput`.

The reference image includes both pinned harness SDKs. Set `harness="codex"` and
supply Codex credentials/configuration to use Codex. Codex defaults to
`approval_mode="deny_all"`; after destruction its conversation uses Agno's history
fallback because its local thread files are gone. Live Codex acceptance is not
part of this example's verified results.

## Configure a deployment

See `control_plane.py`. Register `SandboxAgent` with a `DockerSandboxProvider`, a
runtime image, the same Postgres DB instance used by AgentOS, and `QueueConfig(durable=True, redis=...)`. The
control plane requires the Docker CLI and access to the Docker daemon. Every API
replica needs the same agent IDs, queue settings and `AGNO_SANDBOX_SECRET` (at
least 32 characters). The runtime receives a token derived for its session and
generation; the shared signing secret stays in the control plane.

`runtime_db_url` and `runtime_redis_url` override addresses when the runtime sees
a different network. With host-based AgentOS, configure
`DockerSandboxProvider(publish_localhost=True)` and reachable runtime storage
addresses. The reference deployment puts AgentOS and sandboxes on one Docker
network. API replicas must point to the same Docker host.

Set `runtime_env` from your secret source for model and Git credentials. Customize
the reference Dockerfile with the customer's repository toolchain. Runtime images
must contain Python, Agno, the harness SDK, and a non-root user with a writable
`/workspace`. `agno runtime serve` and `python -m agno.sandbox.runtime` start the
same executor. `AGNO_RUNTIME_CONFIG` and `AGNO_RUNTIME_TOKEN` are injected by the
control plane; callers should not construct them.

Each sandbox defaults to 2 CPUs, 2 GiB RAM and 512 PIDs; adjust `cpus`, `memory`,
and `pids_limit` on `SandboxAgent`. One run executes per session. Queue concurrency
limits apply within each executor and to control-plane dispatch; they are not a
fleet-wide sandbox quota. Provision host capacity and admission policy for the
number of active sessions.

## Recovery and ownership

A queue claim transfers atomically from the API worker to the runtime, preserving
the attempt number. The runtime owns heartbeats, execution, event publication and
settlement. Lost HTTP acknowledgements can be retried without starting a second
execution. An API shutdown cannot settle a claim after transfer. A replacement
sandbox is created only after the old environment is gone. Retry execution is
at-least-once: external effects from a failed attempt can happen again. Production
queue defaults remain one attempt; this deterministic example opts into two.

`GitWorkspace` clones a repository and pushes a session-specific checkpoint after
each turn. A failed checkpoint retains the container instead of allowing idle
cleanup. Recovery preserves the last successful push, including changes committed
by the checkpoint hook. Changes since that push, ignored files, processes and
untracked runtime state do not survive destruction. With `workspace=None`, all
workspace files are disposable. `push=False` makes local commits but provides no
recovery after destruction. Git credentials must be usable by the sandbox's Git
client; there is no shared host filesystem mount.

The runtime is a trusted component with direct access to the deployment's DB and
Redis credentials. A shell in that container can access those credentials. This
is appropriate for a trusted customer deployment; it does not isolate hostile
tenants sharing storage credentials. Use separate deployment/storage credentials
where that isolation is needed. The runtime has no Docker socket or host workspace
mount. Configure network policy and storage permissions for your deployment.

## API

Use the existing AgentOS routes to start, poll, resume streams and cancel runs.
Foreground calls also submit a durable ticket and wait for its result. A new turn
uses the same `session_id`; `/continue` for HITL and step replay is unsupported.

- `GET /sandboxes`: list bindings, optionally filtered by `agent_id` and `status`.
- `GET /sessions/{session_id}/sandbox`: inspect a binding and checkpoint.
- `DELETE /sandboxes/{sandbox_id}`: destroy an inactive sandbox; a later turn recreates it.
- `POST /sessions/{session_id}/sandbox:pause`: returns 501 for Docker.

Management routes use session scopes and the configured user-isolation policy.
Responses omit internal runtime URLs and credentials. Deleting a session destroys
its inactive sandbox and retains a registry tombstone to prevent queued requests
from recreating it. Active sessions return 409: cancel and wait for cleanup first.
Deleted session IDs cannot be reused.

Hosted providers, pause/resume, warm pools, fleet quotas, UI integration and
in-container HITL are follow-up work.
