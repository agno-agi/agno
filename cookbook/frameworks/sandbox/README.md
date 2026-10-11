# Durable sandbox coding agents

Run Claude or Codex inside customer-operated Docker computers while AgentOS owns the API, queue, conversation history and recovery references. This first implementation targets trusted teams. A logical session survives computer replacement; compute is destroyed after every completed turn.

A completed turn means its conversation/native state and managed workspace have been committed together. Content can stream before that point. Checkpoint failure retries finalization without rerunning the model or tools. Live applications restart after replacement; remote MCP effects are not rolled back.

## Start with a credential-free exercise

Use the repository development environment and a running Docker daemon:

```bash
.venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
.venv/bin/python cookbook/frameworks/sandbox/coding_workload.py
```

Expected output reports successful clone, dependency installation, a failing test followed by a code fix and passing test, an HTTP application/database write, then restoration on a second computer. The fixture creates its Git repository and dependency wheel locally; it needs no model credentials or network. Its SQLite application commits writes and stops before capture. This demonstrates provider/checkpoint behavior; the AgentOS examples below add durable orchestration.

The build context contains only public package and packaging sources. It pins the Python base, Claude SDK, Codex SDK and SQLAlchemy. Transitive Python and Debian dependencies resolve at build time; record the resulting image digest for deployment.

## Serve AgentOS

`agentos.py` is the complete configuration example. Install `psycopg[binary]`, `redis`, `fastapi` and `uvicorn` in the service environment and configure existing local test services:

```bash
export SANDBOX_DATABASE_URL=postgresql+psycopg://ai:ai@localhost:5573/ai
export SANDBOX_REDIS_URL=redis://localhost:6407/0
export SANDBOX_CHECKPOINT_DIRECTORY=/absolute/path/to/durable/shared/checkpoints
export SANDBOX_RUNTIME_IMAGE=agno-sandbox:local
export SANDBOX_HARNESS=fixture
.venv/bin/python cookbook/frameworks/sandbox/agentos.py
```

Every replica must reach the same Postgres, Redis, Docker daemon and checkpoint storage, with identical runtime configuration. A local directory is suitable for development; it does not provide host-loss recovery. Production checkpoint storage must survive the intended failure domain and be accessible to every coordinator. `FileCheckpointStore` expects a trusted service-owned directory, never mounted into agent compute.

For a real harness, set `SANDBOX_HARNESS=claude` with `ANTHROPIC_API_KEY`, or `SANDBOX_HARNESS=codex` with `OPENAI_API_KEY`. These are live model calls. The example forwards only the explicitly selected model environment values and enables bridge networking for real harnesses. Customer infrastructure owns egress policy. Never pass service Postgres/Redis credentials into compute.

```bash
curl -X POST http://localhost:7777/agents/coder/runs \
  -H 'Idempotency-Key: first-turn' \
  -F session_id=example -F message='Create a small application and test it' \
  -F stream=false -F background=true
```

All HTTP response modes use the durable queue. API disconnect does not cancel accepted work. Independent sessions run concurrently; same-session turns wait in acceptance order without spending attempts on contention. Duplicate keys require identical scope, input and options; conflicts return 409.

Keep the run ID. Reconnect with `POST /agents/coder/runs/{run_id}/resume` using form fields `session_id` and optionally `last_event_index`. Cancel with `POST /agents/coder/runs/{run_id}/cancel?session_id=example`. Retained indexed events support replay after live Redis events expire; content-delta retention follows `events_to_skip`. Queue settlement follows confirmed compute cleanup and authoritative terminal persistence.

Direct Python `SandboxAgent.run/arun` use the same Postgres session fence. Python background submissions require that agent's active AgentOS queue. `SandboxCoordinator.run` requires `PostgresDb`; `arun` supports both Postgres adapters.

## Files, artifacts and deletion

With the fixture server running:

```bash
.venv/bin/python cookbook/frameworks/sandbox/upload_input.py
.venv/bin/python cookbook/frameworks/sandbox/download_artifact.py \
  --session example --path fixture-effects.txt --output /tmp/completed-effects.txt
.venv/bin/python cookbook/frameworks/sandbox/retire_recovery.py
```

The upload example creates its own session and verifies bytes after a second turn. The deletion example creates and deletes only its own session. `SANDBOX_API_URL` overrides the server URL; `SANDBOX_BEARER_TOKEN` supplies configured authentication.

| Operation | Behavior |
|---|---|
| Multipart `files` | Image/document bytes, up to 16 attachments and 512 KiB combined per turn. |
| JSON form `images` / `input_files` | Arrays with base64 `content` and optional format/MIME/filename. `files` is reserved for multipart uploads. |
| Direct SDK `Image` / `File` | Bytes or explicitly supplied regular local files; only bytes cross the runtime boundary. |
| `GET /agents/{id}/sessions/{sid}/sandbox` | Persisted phase, generation, active/last completed run and checkpoint/compute references; not a provider health probe. |
| `GET .../sandbox/artifacts?offset=0&limit=100` | Paginated regular-file listing from the last completed checkpoint, without allocating compute. |
| `GET .../sandbox/artifact?path=relative/path` | Bounded download, 8 MiB by default, with checkpoint/run identity. |
| `POST .../sandbox/retire` | Cancel/reconcile active compute; retain the previous completed checkpoint. Later turns can resume. |
| `DELETE .../sandbox/recovery` | Idle sessions only. Permanently retire this session ID and delete its published recovery objects. Retry partial failures. |
| Ordinary session deletion | Allowed after recovery deletion; Postgres protects this ordering transactionally, including bulk deletion. |

HTTP attachments cannot name service paths, remote URLs or storage references. Audio/video and malformed media are rejected before enqueue. Canonical bytes survive queue reconstruction; staged files live under `/workspace/.agno/uploads/<run_id>/` and completed checkpoints. Recovery deletion retains conversation inputs until ordinary history is deleted.

Artifact routes use agent-run permission and configured user isolation. Library `SandboxArtifacts` and `SandboxLifecycle` methods enforce exact agent/session/user ownership, including `user_id=None`. Downloads reject traversal, symlinks and native runtime files. Checksums and session-incarnation manifests are verified. The last completed checkpoint remains readable during a later turn.

## Recovery and execution boundaries

| State | Authority and recovery |
|---|---|
| Conversation, tools, runs, queue ownership | Service Postgres; lease epochs and queue attempts fence authoritative writes. |
| Native Claude/Codex state | `/runtime/native`, captured with the workspace; strict native resume, with no silent stored-history fallback. |
| Workspace, Git, dependencies, ignored/untracked files | `/workspace`, captured into an immutable bounded archive. |
| Live processes | Terminated with compute; restart explicitly. Database files need application-consistent backup/quiescence. |
| Remote MCP and external effects | Remain external. Crash retries can repeat effects; use application idempotency. |

Docker uses UID/GID 1000, a read-only image, dropped capabilities, no privilege escalation, explicit CPU/memory/process limits and bounded managed tmpfs volumes. No host bind mounts or Docker socket enter compute. This is not a hostile multitenant security boundary. Networking defaults to none; host/container network sharing is rejected.

Runtime start/poll uses an execution journal: lost replies reconnect to the same identity, not a new model turn. Poll cancellation detaches; explicit cancellation stops compute. Unknown execution fails visibly. Native mirror/persistence failures cannot trigger a second tool execution just to repair storage. Safe relative symlinks and permissions survive checkpoints; special files and escaping/cyclic links are rejected. Known Claude/Codex credential files are excluded, but archive exclusions are not a secret scanner.

Unsupported in this release: hosted execution adapters, warm reuse, automatic idle/retention scheduling, fleet quotas, nested Docker/Compose, previews, historical step replay/fork, version-pinned instances and arbitrary per-turn native options. Skills/plugins must be baked into the trusted runtime image; a transcript does not reinstall them. Unreferenced uploads, provider logs, backups and external effects need separate retention policies.

## Verify and inspect the layers

```bash
.venv/bin/python -m pytest libs/agno/tests/unit/sandbox -q
AGNO_TEST_DOCKER_IMAGE=agno-sandbox:local \
AGNO_TEST_RUNTIME_IMAGE=agno-sandbox:local \
AGNO_TEST_SANDBOX_DB_URL=postgresql+psycopg://ai:ai@localhost:5573/ai \
AGNO_TEST_REDIS_URL=redis://localhost:6407/0 \
.venv/bin/python -m pytest libs/agno/tests/integration/sandbox -q
```

Tests use unique tables/namespaces and remove their own resources. Run unit and integration directories separately to avoid duplicate test-module names. [TEST_LOG.md](TEST_LOG.md) distinguishes deterministic tests, real local infrastructure, and live model/provider acceptance; fixture success is not live harness certification.

Smaller exercises: `docker_execution.py` (provider), `checkpoint_files.py` (archive/store), `runtime_journal.py` (reconnection), `replace_computer.py` (transfer), `durable_completion.py` (Postgres publication), and `session_computer.py` (two coordinated fixture turns). Public operations provide synchronous/asynchronous variants. These primitives alone do not imply the complete durability contract; use the integrated coordinator and AgentOS configuration.

### Hosted allocation contract

Hosted adapters use a service-side `PostgresAllocationJournal` alongside the
existing `PostgresSandboxStore`. Initialize the journal with `await journal.asetup()`
(or `journal.setup()`) after creating the sandbox store. Keep its database access
on the service. Every replica must use the same provider/deployment namespace and
allocation capacity. Active computers and uncertain creates both consume capacity.

A durable intent is recorded before a provider create request. After a lost
response, reconciliation must locate the computer by its exact allocation token.
An empty inventory response does not authorize a second create: the first request
may still be processing. Pending intents do not expire automatically. A confirmed
destruction releases capacity; uncertain allocations require reconciliation.

The base compute specification accepts `pids_limit=None` and `workspace_mb=None`
to explicitly select a hosted provider's default controls where per-computer hard
limits cannot be requested. These values do not promise unlimited or durable disk.
Docker continues to require both limits. Portable checkpoint limits apply separately
from the live filesystem size. Provider-specific setup and live acceptance are
required before claiming hosted execution support.

### Prepared hosted runtime

The hosted transport requires a prepared Linux image containing this package and
its chosen native SDK, installed into root-owned directories. Provider control
commands run as root. Agent commands run as UID/GID 1000 with Linux
`no_new_privs`; `/workspace` and `/runtime` must initially be empty. Provider
daemons must run under other users and must not write the managed roots.

`HostedCheckpointTransfer(provider, checkpoint_store)` implements the same portable
archive format as Docker. Its initial transfer limit is 64 MiB per checkpoint;
the service buffers those bytes during upload/download. Configure a smaller
`CheckpointArchive(CheckpointLimits(...))` when needed. This limit is independent
of the provider's live disk allocation. Large repositories and dependencies can
exceed it and must fail completion rather than silently discard files.

Capture freezes all UID 1000 processes and leaves them frozen until teardown.
Only managed workspace and native files are restored; applications must restart.
Quiesce database/application writers first if logical consistency is required.
A captured computer cannot run another command. Lost capture responses can be
recaptured during finalization without repeating model work. Imports require an
unused computer; failures stop it. Known native credential files are excluded,
but that exclusion is not a general secret scanner.

The runtime helper is trusted control code. The initial deployment remains for
customer-operated trusted teams; it is not a hostile multitenant security claim.
The provider adapter must never auto-resume a stopped execution during inspection.
Local acceptance exercises the helper with real Linux processes through a Docker
test bridge; each hosted provider still requires live acceptance.

### E2B (live acceptance required)

Install `agno[e2b-sandbox]` with Python 3.10+ (SDK pinned to 2.55.1). Set
`E2B_API_KEY` on the service and prepare an E2B template from a published image
containing the hosted runtime and native SDKs. For example, with the installed
E2B SDK: `Template.build(Template().from_image(image), alias=alias, cpu_count=2,
memory_mb=2048)`. Building a template and running the following command can incur
provider charges. Do not put service credentials in the image or template.

```bash
python cookbook/frameworks/sandbox/hosted_workload.py --provider e2b --image YOUR_TEMPLATE_ID
```

Set `AGNO_TEST_SANDBOX_DB_URL` to a dedicated Postgres database. The workload
creates two successive computers, clones/edits/tests/runs a local application,
checkpoints it, destroys compute, and verifies restoration/application restart.
It uses no model calls. Test allocation tables are retained for reconciliation
rather than deleting uncertain intents during cleanup.

For AgentOS wiring, create `E2BSandboxProvider(namespace, journal)` and
`HostedCheckpointTransfer(provider, object_store)`, then pass them to
`SandboxCoordinator` and `SandboxAgent` as in the Docker example. Set the agent's
`pids_limit=None`, `workspace_mb=None`, image to the template ID, and CPU/memory to
the template's actual resources. Set `network="internet"` explicitly for remote
model/MCP calls. The account/template must support the configured lifetime.

E2B transport uses a read-only SDK endpoint to retrieve the secure connection
information; it does not call `connect`, which can resume paused computers.
Allocation and control HTTP retries are disabled. Expiry kills compute and the
next turn restores from the last completed checkpoint. SDK contract tests run
without network; live account, template, filesystem permissions and both native
harnesses still need acceptance.
