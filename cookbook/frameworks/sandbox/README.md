# Sandboxed agents

Run each turn of a Claude Code or Codex agent in its own computer: a Docker container on a host you operate, an Amazon Bedrock AgentCore microVM, or a Modal sandbox. The agent's workspace and native conversation are checkpointed after every turn, so the next turn can run on a fresh computer anywhere, and AgentOS runs these agents behind a durable queue.

This is different from `DockerTools`, which gives an agent tools to manage containers on the host. `DockerSandbox` gives each session its own isolated container that the agent works inside.

Install the repository development environment and Docker, then run:

```bash
docker pull python:3.12-slim
.venv/bin/python cookbook/frameworks/sandbox/docker/docker_execution.py
```

The example creates a sandbox container, writes and reads a file, reuses that container and deletes it. No model credentials are needed. Set `AGNO_SANDBOX_IMAGE` to a trusted Linux image containing `python`; pin its digest for repeatable deployments. The Docker context on the service host selects the trusted daemon and its authentication configuration.

`DockerSandbox(image=..., memory_mb=...)` holds settings shared by every session of an agent. `create(session_id, agent_id=None, generation=1, env=None)` identifies one session and returns a `SandboxHandle`; pass that handle to `exec`, `stop` and `destroy` so a stale caller can never act on a newer container that reuses the name. `namespace` (default `"default"`) separates deployments sharing a daemon. Repeating `create` with the same identity and configuration returns a handle to the same running container, including after an uncertain creation response. A stopped generation cannot be restarted through `create`: recovery must call `create` with a new `generation`. This prevents accidentally treating lost tmpfs files as retained session state.

`DockerSandbox` offers `create/get/exec/stop/destroy` and their asynchronous `acreate/aget/aexec/astop/adestroy` counterparts. Command arguments are passed as a sequence; explicitly use `sh -c` when shell syntax is intended. Nonzero command exits are returned as `ExecResult`; infrastructure failures raise `SandboxError`. Uncertain commands are never retried automatically.

The code is in `agno.sandbox`. `base.py` and `transfer.py` hold the protocols every provider implements: `Sandbox` for compute and `CheckpointTransfer` for moving checkpoints. Each provider is a package with one module per protocol:

| Package | Modules |
|---|---|
| `agno.sandbox.docker` | `sandbox.py` (`DockerSandbox`), `transfer.py` (`DockerCheckpointTransfer`) |
| `agno.sandbox.agentcore` | `sandbox.py` (`AgentCoreSandbox`), `transfer.py` (`AgentCoreCheckpointTransfer`), `server.py` (runs inside the microVM) |
| `agno.sandbox.modal` | `sandbox.py` (`ModalSandbox`), `transfer.py` (`ModalCheckpointTransfer`) |

Import the classes from the package, for example `from agno.sandbox.docker import DockerSandbox`. The checkpoint archive and stores in `checkpoint.py` and the runtime in `runtime.py` and `client.py` are shared by every provider.

## Layout

| Path | What it holds |
|---|---|
| `docker/` | Cookbooks for `DockerSandbox`: execution, warm reuse, the runtime transport, checkpoints, the session coordinator and AgentOS. Start with [docker/README.md](docker/README.md). |
| `agentcore/` | Deploying the runtime to Amazon Bedrock AgentCore and running the same agents there. Start with [agentcore/README.md](agentcore/README.md), which has the step-by-step setup. |
| `modal/` | Running the same agents in Modal sandboxes, with the runtime image built on Modal from the shared `Dockerfile`. Start with [modal/README.md](modal/README.md). |
| `Dockerfile`, `build_image.py` | The one runtime image every provider uses; `build_image.py --tag agno-sandbox:local` builds it from the package sources. |
| `warm_turns.py` | Provider-neutral: four coordinator turns on Docker, AgentCore or Modal showing warm reuse and the cold fallback, with create and restore counted per turn. |

Each folder keeps its own `TEST_LOG.md`.

## Validation

```bash
.venv/bin/python -m pytest libs/agno/tests/unit/sandbox -q
AGNO_TEST_DOCKER_IMAGE=python:3.12-slim .venv/bin/python -m pytest libs/agno/tests/integration/sandbox -q
```

Integration tests use unique namespaces and remove only their own containers. See [docker/TEST_LOG.md](docker/TEST_LOG.md), [agentcore/TEST_LOG.md](agentcore/TEST_LOG.md) and [modal/TEST_LOG.md](modal/TEST_LOG.md) for the tested environment and limits.

## Checkpoint archive and storage

```bash
.venv/bin/python cookbook/frameworks/sandbox/docker/checkpoint_files.py
```

This credential-free example captures real filesystem roots, uploads an immutable object, deletes the original files, and restores them through another store instance. `CheckpointArchive` requires `workspace` and `native` roots and a JSON state manifest. `FileCheckpointStore` stores immutable SHA-256-addressed bytes with size/checksum verification and atomic publication, and is the first implementation of the `CheckpointStore` protocol. Reading an object that storage no longer holds raises `CheckpointObjectNotFound`, so a service can tell storage loss apart from a checkpoint it merely cannot serve. Read an object back through `open_archive`, which verifies it and then yields a path valid for the duration of the context, which retention removing the object meanwhile does not invalidate; a store whose objects are remote materializes a temporary copy there and removes it on exit, while a local object is never removed by reading it. Both classes provide sync and async operations.

Drain native SDK writes and quiesce all applications before capture. The native root must contain only restorable state; keep credentials outside it or explicitly exclude credential paths. Exclusions are exact relative paths (and their descendants), not glob expressions. The two roots must be disjoint, and capture refuses them otherwise: an exclusion names one archive prefix, so a root containing the other would carry an excluded file in under that other prefix. Capture also refuses a hardlink that would carry an excluded file's contents out under another name, for as long as the excluded path itself exists; once the original is deleted a surviving link cannot be told from an ordinary file, so break such links rather than relying on the exclusion. Ignored and untracked workspace files are included. Safe relative symlinks, file permissions and modification times survive; hardlinked source files become separate files. Symlinks to absolute paths, such as a virtualenv's interpreter link, are stored verbatim and recreated only by a restore inside a computer; a host-side restore leaves them out. Special files, escaping/cyclic links and malicious archives are rejected with `CheckpointContentError`. Archives are gzip-compressed by default; `CheckpointArchive(compress=False)` writes plain tar, and either stored representation is read back whatever the reader's own setting is. Archive limits bound bytes, entry counts and metadata. The byte limit measures the expanded archive, entry framing included, on write as much as on read: a capture that succeeds is one restore accepts, and a decompression bomb is rejected before it is written. The digest and size in a reference always describe the stored bytes. Restore validates all paths before materializing into a new directory. Restore never updates a running workspace in place.

The object directory and restore parent must be trusted coordinator-owned paths, never mounted into sandbox compute or exposed to agent tools. Production storage must survive the intended failure domain, for example a suitably configured shared filesystem; a service-local directory does not provide host-loss recovery. The demo uses temporary local disk and proves filesystem semantics only. Objects are not deleted when compute is destroyed; `delete` exists for a retention reconciler, which is separate and does not ship here.

### Required filesystem capabilities

Checkpoint file reads require `os.O_NOFOLLOW`; the implementation refuses to read without it instead of following a symlink. `FileCheckpointStore` also requires hard links for immutable publication and reader leases, file and directory `fsync` for durability, and atomic rename for archive restore. Restoring symlinks requires symlink creation and timestamp updates with `follow_symlinks=False`. These requirements apply to the host running the checkpoint code and its filesystem, regardless of the Docker container image.

A missing `O_NOFOLLOW`, or an explicitly unsupported hard-link or directory-sync operation, raises an actionable `SandboxError`. The underlying operation error is retained as its cause. Permission, disk-full and other I/O errors propagate unchanged; no protection or durability step is silently skipped. Capabilities are checked when used, not certified at construction: a failed directory sync can occur after an object has been linked or deleted, so an error does not mean nothing changed. Do not publish a checkpoint reference from a failed upload.

Windows support has not been established or tested for this checkpoint implementation. These checks report unavailable primitives; they do not add a Windows fallback. Use a host and filesystem that provide the required capabilities.

An upload is not a completed run. A following coordinator transaction must publish the checkpoint reference together with authoritative conversation/native metadata and terminal run state, fenced against the current session generation. These archive/store primitives do not implement that transaction, SDK capture, Docker transport or automatic session recovery. Async cancellation waits for in-progress filesystem work to finish, so cleanup does not race a background writer; callers must reconcile whether that operation completed.

## How a turn completes

The store is internal: the coordinator builds it from the agent's `PostgresDb`. Its lease table lives in that same database, named by `PostgresDb(sandbox_table=...)` (default `<session_table>_sandbox_bindings`, since each bindings table has a foreign key to exactly one session table), and is created on first use like every other agno table, so there is no setup call. Async methods support both Postgres adapters; synchronous methods require `PostgresDb`.

A runtime result is staged first. A verified checkpoint reference and provider-confirmed compute cleanup are required before one transaction publishes the run and session recovery reference. Lease epochs and queue attempts fence previous coordinators. Native session data is nested under `session_data.sandbox.native`. The run takes only runtime output fields (content, messages, tools, metrics, media, events, status) from the result; identity, input, lineage and service metadata stay as stored, and runtime metadata is nested under `metadata.sandbox.native_metadata`. The store keeps nothing it depends on in `session_data`, so editing a session mid-run is safe. The binding row has a foreign key to its session with `ON DELETE CASCADE`: deleting a session deletes its binding, a recreated session (even with the same id, `created_at` and run id) starts from a fresh binding, and every lease carries its binding's incarnation, so a coordinator still holding a lease for the deleted session is refused. The store then no longer tracks a computer that was running for the deleted session; providers should sweep orphaned computers by their labels. The binding's `checkpoint` is the authoritative recovery point. `session_data.sandbox` is a copy for readers, and a stale session upsert can overwrite it.

The store has no public API of its own, so these steps are walked against a real Postgres by `test_durable_completion_walkthrough` in `libs/agno/tests/integration/sandbox/test_postgres.py`: the run stays RUNNING after its result is staged, a session edit mid-turn keeps the lease, a coordinator that stops renewing is fenced by its successor, and a cancelled turn keeps the previous turn's checkpoint.

## Session coordinator

`SandboxCoordinator` runs a session's turns on sandbox computers with durable recovery. These three cookbooks use only its public API and the credential-free fixture runtime; build the runtime image and start pgvector first:

```bash
./cookbook/scripts/run_pgvector.sh
.venv/bin/python cookbook/frameworks/sandbox/build_image.py
```

| Cookbook | What it shows |
|----------|---------------|
| `session_computer.py` | Several turns of one session: turn 2 resumes turn 1's computer from its pause, a later turn after the warm window runs on a fresh computer restored from the checkpoint; retrying a finished run returns its stored result |
| `resume_after_disconnect.py` | The caller drops mid-turn, the turn keeps running in its container, and another coordinator reattaches to it |
| `cancel_turn.py` | A cancelled turn publishes nothing; the next turn continues from the last completed one |
| `open_checkpoint.py` | A completed run's checkpoint opened on the host through the agent (`checkpoint_store`, `open_run_checkpoint`) and restored to a directory; unknown, unfinished and other agents' runs are refused |
| `warm_turns.py` | Four turns on Docker, AgentCore (`--provider agentcore`) or Modal (`--provider modal`): which path each takes, what it costs, and the cold fallback after the warm window; counts create and restore on the provider rather than guessing from timing |

```python
coordinator = SandboxCoordinator(db, DockerSandbox(image), transfer)
coordinator.run(
    "session-id",
    agent_id="coder",
    run_id="turn-1",
    input="...",
    sdk="claude",
    env={"ANTHROPIC_API_KEY": key},
)
```

`db` is the agent's `PostgresDb`; the coordinator keeps its leases there, with no setup call. Image and resource limits belong to the provider, and `env` is the per-session runtime environment. A real SDK also needs network access, for example `DockerSandbox(image, network="bridge")`.

Each commit records the native conversation id the checkpoint holds (Claude's session id, Codex's thread id) on the session's binding. The next turn passes it as `native_session_id`, so a restore that did not bring the native state back fails with `native_state_missing` before the model runs, instead of completing on a new conversation. The turn ends as a retryable error and the previous checkpoint stays the recovery point.

`SandboxCoordinator` stages the execution result before capturing an archive, persists that reference before removing compute, and atomically publishes conversation plus recovery metadata afterwards. A reconnect uses the same execution identity; a finalization retry never starts another model turn. Missing compute before capture fails visibly and preserves the previous checkpoint. A missing cleanup or commit acknowledgement can be reconciled with the same run ID and input. `run()` requires PostgresDb; `arun()` supports both Postgres adapters.

Provider mutation operations hold the session ownership rows until their bounded transport calls drain. Takeover waits for an in-flight restore/capture instead of racing it. This costs a database connection and can delay cancellation until a transfer finishes. After a completed turn the computer is kept for `warm_computer_seconds` (default 300), paused on Docker and idle on AgentCore and Modal, and the next turn resumes it with nothing to restore. The checkpoint is still captured after every turn and remains the recovery point: a kept computer that is gone, expired, differently configured or past the provider's lifetime is retired and the turn runs on a fresh generation restored from the checkpoint, which is the only path with `warm_computer_seconds=0`. Cancellation and failures always retire the computer. A warm computer is retired by its session's next claim, so a session that never returns leaves a paused container until something sweeps it; deployments should sweep provider computers idle past the window.

Each active turn costs the database: one held connection during a provider call, a lease check per poll page, and a heartbeat renewal every third of the lease. Polls long-poll inside the container for up to `poll_wait` seconds (default 5) and return as soon as there are events, so an idle turn makes about one poll and one lease check per `poll_wait`. `poll_wait` also bounds how long a cancellation can go unnoticed while a turn emits nothing. Size the `PostgresDb` connection pool for the number of concurrently active sessions plus the rest of the application; the default pool is small.

Use deployment storage accessible to every coordinator replica for checkpoint bytes. The local directory store in these examples is temporary and does not certify host-loss recovery. Workspace and native files restore; live processes restart, and remote MCP/tool effects are not rolled back. Direct stream reconnection may repeat provisional events; durable event transport remains an AgentOS integration responsibility.


## Repository workspaces

`repository_workspace.py` configures `repository=Repository(url, branch="main")` on a
sandboxed Codex agent. ClaudeAgent uses the same field. The runtime resolves the branch
on the session's first turn, fetches that commit shallowly, and starts the harness in
`/workspace/repository`. Later turns retain commits and uncommitted files, even after
restoring a checkpoint on a replacement computer. Changing the agent's URL or branch
requires a new session. Passing `repository=` to `run()` or `arun()` is refused.

Set `REPOSITORY_URL`, optionally `REPOSITORY_BRANCH`, `ENGINEER_SESSION_ID`,
`SANDBOX_DATABASE_URL`, `SANDBOX_IMAGE`, and `SANDBOX_CHECKPOINTS`, then run:

```bash
.venv/bin/python cookbook/frameworks/sandbox/repository_workspace.py
```

Public GitHub repositories need no token. For a private repository, set
`env={"GITHUB_READ_TOKEN": ...}` on the sandbox using a short-lived, single-repository
read token. It is read only from the sandbox environment; the host environment is not
forwarded automatically. `GITHUB_TOKEN` is refused once a repository is configured. Git
receives authentication through its child environment, with redirects and interactive
prompting disabled, and never stores the token in the checkout or checkpoint. Model/tools
running inside the sandbox can access its environment; never put a publishing credential
there.

The completed run exposes `{url, branch, commit}` at
`run.metadata["sandbox"]["repository"]`, alongside its checkpoint and resumed status.
Git preparation has a 120-second timeout per command; a preparation failure is retryable
and removes the partial checkout before the model starts. Run attachments are staged under
`.agno/uploads/` inside the checkout; the checkout's `.git/info/exclude` keeps them out of
`git status` and `git add`.

Sandboxed agents require PostgreSQL and an explicit checkpoint store. AgentOS durable
queue deployments also require Redis. Docker needs `network="isolated"` (or another
network with GitHub/model egress); AgentCore and Modal need egress. Size `workspace_mb` for the
shallow checkout and generated files, within the 1 GiB checkpoint cap. With more than
one host, use `S3CheckpointStore` or `PostgresCheckpointStore` so every replica can
restore every checkpoint.

A first turn may select a specific commit or another branch through run metadata:

```python
result = engineer.run(
    "Inspect this revision.",
    session_id="revision-review",
    metadata={"repository": {"commit": "<40-hex commit SHA>"}},
)
# Alternatively: metadata={"repository": {"branch": "release"}}
```

The URL always comes from `agent.repository`; a metadata override containing `url`
is refused, even when it matches. Supply exactly one of `commit` or `branch`.
AgentOS middleware can provide the same value through `request.state.metadata`;
the durable queue carries it to the runtime. Once `native/repository.json` exists,
valid overrides are ignored: the saved pin and engineer's changes win. Invalid
overrides still fail validation without network access.

The published pin has `url`, `branch`, and `commit`. For a commit override, `branch`
remains the agent's configured branch; for a branch override, it is the effective
branch. In the latter case the marker also retains `configured_branch` internally
so changing the agent's configuration mid-session is still refused.

Other inbound metadata is retained in the service run record. The `sandbox`,
`warnings`, `attempts`, `retryable`, and `error_type` keys are reserved for execution
and recovery results. Preparation deadlines and missing restored repository state
are retryable before the harness starts; timeouts after it starts remain terminal.
