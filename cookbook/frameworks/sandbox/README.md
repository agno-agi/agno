# Sandbox execution primitives

Run commands in a customer-operated Docker environment for trusted teams. This is the compute foundation for session sandboxes. It does not yet connect Claude/Codex agents to AgentOS or provide durable session recovery.

This is different from `DockerTools`, which gives an agent tools to manage containers on the host. `DockerSandbox` gives each session its own isolated container that the agent works inside.

Install the repository development environment and Docker, then run:

```bash
docker pull python:3.12-slim
.venv/bin/python cookbook/frameworks/sandbox/docker_execution.py
```

The example creates a sandbox container, writes and reads a file, reuses that container and deletes it. No model credentials are needed. Set `AGNO_SANDBOX_IMAGE` to a trusted Linux image containing `python`; pin its digest for repeatable deployments. The Docker context on the service host selects the trusted daemon and its authentication configuration.

`DockerSandbox(image=..., memory_mb=...)` holds settings shared by every session of an agent. `create(session_id, agent_id=None, generation=1, env=None)` identifies one session and returns a `SandboxHandle`; pass that handle to `exec`, `stop` and `destroy` so a stale caller can never act on a newer container that reuses the name. `namespace` (default `"default"`) separates deployments sharing a daemon. Repeating `create` with the same identity and configuration returns a handle to the same running container, including after an uncertain creation response. A stopped generation cannot be restarted through `create`: recovery must call `create` with a new `generation`. This prevents accidentally treating lost tmpfs files as retained session state.

`DockerSandbox` offers `create/get/exec/stop/destroy` and their asynchronous `acreate/aget/aexec/astop/adestroy` counterparts. Command arguments are passed as a sequence; explicitly use `sh -c` when shell syntax is intended. Nonzero command exits are returned as `ExecResult`; infrastructure failures raise `SandboxError`. Uncertain commands are never retried automatically.

The code is in `agno.sandbox`. `base.py` and `transfer.py` hold the protocols every provider implements: `Sandbox` for compute and `CheckpointTransfer` for moving checkpoints. Each provider is a package with one module per protocol:

| Package | Modules |
|---|---|
| `agno.sandbox.docker` | `sandbox.py` (`DockerSandbox`), `transfer.py` (`DockerCheckpointTransfer`) |
| `agno.sandbox.agentcore` | `sandbox.py` (`AgentCoreSandbox`), `transfer.py` (`AgentCoreCheckpointTransfer`), `server.py` (runs inside the microVM) |

Import the classes from the package, for example `from agno.sandbox.docker import DockerSandbox`. The checkpoint archive and stores in `checkpoint.py` and the runtime in `runtime.py` and `client.py` are shared by every provider.

## Warm reuse between turns

```bash
.venv/bin/python cookbook/frameworks/sandbox/warm_reuse.py
```

The example does a turn's worth of work, writing a file and leaving a background process running, then pauses the container. Pausing uses the kernel freezer: files, memory and processes stay exactly as they are, no bytes are copied anywhere, and commands are refused until the container resumes. The next turn calls `resume` and gets the same container back running, with the file present and the background process continuing from where it froze; `create` on the paused generation is refused. The example then stops the container to show the cold path: the tmpfs files are gone, the generation cannot restart, and the next turn needs generation 2 restored from a checkpoint.

`pause`, `resume` and their async counterparts are part of the `Sandbox` contract. A provider without a native pause raises `NotImplementedError`, so a caller can fall back to keeping the container running or to the cold path. A paused container is still tied to one host and still counts against its memory, so pausing complements checkpoints rather than replacing them: checkpoints remain the recovery path when the host or the container is gone.

## The smallest sandboxed agent

```bash
export ANTHROPIC_API_KEY=...   # or CLAUDE_CODE_OAUTH_TOKEN
.venv/bin/python cookbook/frameworks/sandbox/sandbox_claude.py
```

`sandbox_claude.py` is a `ClaudeAgent` with a `PostgresDb` and `sandbox=DockerSandbox(image)`, nothing else. It runs two turns on a new session: the first writes and runs a file, the second asks what file was created. Each turn runs the whole Claude Code process in a container from the image; when it completes, its workspace and Claude Code's own conversation are checkpointed and the container is removed, and the next turn starts a fresh container restored from that checkpoint, which is how turn 2 knows the file name. The credential in the process environment (`ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`) is forwarded into the container. Checkpoints default to `~/.agno/sandbox/checkpoints`, which suits a single host.

`sandbox_claude_agentcore.py` is the same agent with `sandbox=AgentCoreSandbox(runtime_arn, env=...)`, so each turn runs in an AgentCore microVM instead of a local container. Claude reaches Bedrock through the runtime's execution role: the sandbox's `env` sets `CLAUDE_CODE_USE_BEDROCK` and `AWS_REGION`. With that flag set, the harness does not forward `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` from the host, so no API key goes into the microVM. Deploy the runtime with `agentcore_setup.py` and set `AGENTCORE_RUNTIME_ARN` first.

`sandbox_claude_agentcore_agentos.py` serves that agent through AgentOS with a durable queue, as `sandbox_claude_agentos.py` does for Docker. AgentOS, the queue and the database stay on your host; only the turns run on AgentCore.

`sandbox_claude_agentos.py` serves the same agent through AgentOS with a durable queue (Postgres and Redis). Every API request submits to the queue, a dropped connection does not cancel the turn, and a second request on the same session waits for the first. It names its checkpoint store explicitly: with a queue, any replica may run the next attempt, so the default host-local store is refused.

## A live Claude session in a sandbox

```bash
export ANTHROPIC_API_KEY=...   # or CLAUDE_CODE_OAUTH_TOKEN
.venv/bin/python cookbook/frameworks/sandbox/claude_runtime.py
```

The example runs two Claude turns on one session inside a container built from the runtime image, with a pause between them. Turn 1 asks Claude to write and run a program; its tool calls and content stream back through the runtime journal, the file lands in `/workspace`, and Claude Code's own session is kept under `/runtime/native` next to the local history database. The container is then paused and resumed. Turn 2 asks, without tools, what the previous turn did. Claude answers from its native session, and the example asserts the Claude session id recorded on the local session row is the same for both turns.

Only the selected model credential is forwarded into the container environment. `runtime_config` holds the `ClaudeAgent` settings (model, permission mode, allowed tools, turn limit); the runtime adds the workspace, the local database and the strict settings itself. The execution result is output, not a completed run: the coordinator layer that checkpoints and commits it to the service database is a later PR, so this example writes nothing outside the container.

## Runtime transport: exec or an in-container server

The host reaches the runtime two ways. By default `DockerSandbox` starts the container with a sleep entrypoint and every runtime request spawns `python -m agno.sandbox.runtime` through `docker exec`: it works on any image that carries the package and needs no port, but each request is a process through the Docker daemon. With `runtime_port` set, the container's entrypoint is the runtime itself as a small HTTP server, Docker publishes that port on the host's loopback only, and `rpc` becomes a pooled connection: `POST /start`, `POST /poll`, `GET /health`. Same JSON, same journal, same locks; the daemon is used for create, pause, resume, stop and destroy and nothing else. `create` waits for `/health` before handing the sandbox out. The server needs a network, so `runtime_port` is refused with `network="none"`.

```python
sandbox = DockerSandbox("agno-sandbox:local", network="isolated", runtime_port=8765)
# Replicas on other hosts sharing this daemon: advertise the daemon host's address instead.
shared = DockerSandbox("agno-sandbox:local", network="isolated", runtime_port=8765, runtime_host="10.0.0.5")
```

Polls long-poll on both transports: the container holds a `poll` for up to `wait` seconds (default 10, cap 30) and answers as soon as the journal grows or the result lands, so an idle turn costs one request per `wait` and events arrive when they are written. `wait=0` restores the sleep-between-requests loop.

```bash
AGNO_SANDBOX_LOAD_SESSIONS=8 .venv/bin/python cookbook/frameworks/sandbox/runtime_transport_load.py
```

The example runs the same concurrent fixture turns three ways and prints requests per turn, Docker daemon calls per turn and the cost of an idle poll. Requests and daemon calls per turn are what grow with concurrent users; the idle poll is the per-request overhead of the transport. The exec transport with a poll loop is the pre-long-poll behaviour and the reference point.

Every container gets its own bearer token, generated at create, delivered through the private env file and read back onto the handle as `runtime_token`, so any replica holding the handle can talk to the server and nothing else can. Where the token is inside the container, precisely: the supervisor takes it out of its environment at startup and hands it to the server on stdin, so the serving process holds it only in memory; workers are spawned without it, so the agent's tools do not find it in their environment; every `docker exec` from the host runs with the variable blanked. What remains: the token is delivered through the container's environment so the host can read it back from the daemon, and the exec-time environment of PID 1 and of the supervisor still contains it, readable through `/proc` by anything running as the same UID. A determined agent can therefore still recover it, and it only ever grants what that container's own server does, which the agent can already drive by writing the journal; a sandbox must not be able to reach another sandbox's port (see networking). Running the server under a separate UID is the follow-up that makes the token unreachable. The port is published on `runtime_host`, `127.0.0.1` by default, which only this host's replicas reach and which the container's gateway does not. With one Docker daemon shared by replicas on several hosts, set `runtime_host` to the daemon host's address those replicas can reach; that network must be trusted, since the token travels over plain HTTP, and the value is part of the generation's configuration, so every replica must use the same one. Hosted providers implement `rpc` against the same server and the same token through whatever port exposure they offer.

With `runtime_port` set, the container's main process is a supervisor (`python -m agno.sandbox.runtime supervise`) under Docker's init. It runs the HTTP server as a child and restarts it with backoff if it exits; workers run detached, so a server crash does not touch a turn, and the host sees at most a short gap that the cursor-based reconnect absorbs. `SIGTERM`, which Docker sends on `stop`, ends the server and the supervisor.

```bash
.venv/bin/python cookbook/frameworks/sandbox/runtime_resilience.py
```

The example prints every event as it arrives with its cursor and elapsed time. It runs a fixture turn and shows the variables the turn could see, with the token absent; starts a turn that streams eight events over four seconds, kills the server with `SIGKILL` after the second one, and shows the host's polls failing for a few hundred milliseconds, the supervisor bringing the server back, and the remaining events arriving from the same cursor with nothing missing or repeated; then forces a control request on the exec transport to time out and shows the container still running and the turn still finishing.

Without `runtime_port`, `rpc` falls back to exec with the rule of a control request: a failed or lost reply raises and leaves compute alone, never stopping the container, since start and poll exit on their own and are idempotent. Arbitrary `exec` keeps its stop-on-uncertainty rule. `runtime_port` and `runtime_host` are part of the generation's config digest, so changing them, including flipping a default, makes `create` refuse every live generation; treat such a change as a migration that drains sessions rather than a rolling deploy.

## Amazon Bedrock AgentCore Runtime

```bash
export AWS_PROFILE=staging AWS_REGION=us-east-1
.venv/bin/python cookbook/frameworks/sandbox/agentcore_setup.py deploy --name agno-sandbox
export AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:...:runtime/agno_sandbox-...
.venv/bin/python cookbook/frameworks/sandbox/agentcore_session.py                    # fixture, no model calls
.venv/bin/python cookbook/frameworks/sandbox/agentcore_session.py --harness codex    # forwards OPENAI_API_KEY
.venv/bin/python cookbook/frameworks/sandbox/agentcore_session.py --harness claude   # Bedrock via the execution role
.venv/bin/python cookbook/frameworks/sandbox/agentcore_session.py --harness codex --replace  # turn 2 on a restored microVM
.venv/bin/python cookbook/frameworks/sandbox/agentcore_session.py --harness codex --resume   # needs deploy --session-storage
.venv/bin/python cookbook/frameworks/sandbox/agentcore_setup.py teardown --name agno-sandbox
```

These create AWS resources and billable compute. Install `agno[agentcore-sandbox]`. `agentcore_setup.py` builds the ARM64 image from the same `Dockerfile` that Docker uses, pushes it to a new ECR repository, creates an execution role that may call Claude models on Bedrock, and creates a PUBLIC runtime. It prints the runtime ARN and the runtime's `maxLifetime`; keep `AgentCoreSandbox(lifetime=...)` at or below it, or AgentCore ends the microVM first. Code in the sandbox can use the execution role, so it can call any model the role allows. `--session-storage` also mounts AgentCore session storage at `/mnt/agno` for the warm resume described below. Without permission to create ECR repositories or IAM roles, pass ones an administrator created with `--repository` and `--role-arn`, and add `--skip-build` with `--tag` to deploy an image already pushed. Teardown with the same flags leaves them in place.

The image's entrypoint is the AgentCore server, since AgentCore cannot override it. `DockerSandbox` sets the user, entrypoint and working directory at create, so the same image works there.

`AgentCoreSandbox(runtime_arn, namespace=...)` implements the same `Sandbox` contract as `DockerSandbox`. Each generation is the AgentCore runtime session named after its namespace, agent, session and generation, so `create` is idempotent and finds a computer again after a lost reply. Every session is a Firecracker microVM with 2 vCPU and 8 GiB.

The image's entrypoint, `agno.sandbox.agentcore.server`, runs as root and answers AgentCore on port 8080. `create` claims the microVM: the server records the identity, environment and a lifetime deadline where the agent cannot read them, creates `/workspace` and `/runtime` for UID 1000, and starts the runtime server as UID 1000 with a token only it holds. `rpc` reaches that server through `InvokeAgentRuntime`, so long polls work without publishing a port. Commands go through `InvokeAgentRuntimeCommand` behind a guard that refuses an unclaimed microVM, applies the claimed environment and drops to UID 1000 in `/workspace`.

The example runs two turns of one session. By default turn 2 calls `create` again, as a new request would, gets the same microVM, and the harness resumes its native session with nothing to restore. `--replace` takes the cold path instead: it captures a checkpoint after turn 1, destroys the microVM, creates generation 2 and restores into it, so turn 2 runs on a fresh microVM. With a real harness, turn 2 must recall a codeword that only the conversation from turn 1 holds.

`AgentCoreCheckpointTransfer` implements the same `CheckpointTransfer` protocol as `DockerCheckpointTransfer`. Inside the microVM, the server stops the agent's UID 1000 processes and runs `CheckpointArchive.capture` in a child process dropped to UID 1000, so root never reads, writes or changes ownership of a path the agent controls; there is no microVM pause. The archive comes out through `InvokeAgentRuntime` in chunks of at most 8 MiB and the host validates it before storing it. Restore validates the stored archive, sends it to a claimed generation that has not run a command or turn, and a UID 1000 child restores it with `CheckpointArchive.restore`. A failed restore leaves the computer refusing all further work, and the transfer stops it. AgentCore's default exclusions add `native/codex/.tmp/plugins` and its `.sha` marker, a plugin marketplace of about 100 MiB that Codex clones on start.

The server on port 8080 refuses connections from sockets owned by UID 1000, so agent code cannot call it; AgentCore's forwarder connects over loopback as another user. Every request after create names the claim's random incarnation, kept in `SandboxHandle.name`, so a handle never runs work on a microVM that AgentCore started after its own ended.

Differences from Docker:

| Behavior | AgentCore |
|---|---|
| Stopped generation | AgentCore starts a fresh microVM when a stopped session is called again. The provider stops an unclaimed microVM and recovery takes a new generation restored with `AgentCoreCheckpointTransfer`. Without durable state outside the microVM, `create` cannot tell an expired generation from a new one and claims a fresh, empty microVM for it; a coordinator that records generations must move to a new one after any loss. |
| Pause | Not supported. Keep the generation running between turns; the runtime's idle timeout and maximum lifetime bound it. A checkpoint capture sends SIGSTOP to the agent's processes, including the runtime server, so host polls fail until the export finishes; the client's cursor reconnect absorbs this, as with Docker's pause. |
| Lifetime | Enforced inside the microVM: at the deadline it ends the agent's processes and exits, and a turn still running dies with it. Set `lifetime` from the coordinator's turn budget. |
| Lookup | `get` on an ended generation is not read-only. Calling the session starts a replacement microVM, about 12 seconds cold, which the provider then stops, about 12 seconds more. A provider object answers sessions it stopped itself without a call; other replicas pay about 25 seconds per lookup. |
| Files | On the microVM's disk. AgentCore session storage is NFS, where SQLite cannot open a database and POSIX locks fail, so the managed roots never live there. |
| Warm resume | With session storage mounted at `/mnt/agno`, each capture keeps a copy of its checkpoint there, and `AgentCoreCheckpointTransfer.aresume(session_id, reference)` brings the ended generation back on a replacement microVM without moving the checkpoint from the store. The storage enforces no permissions, so agent code can read or replace the copy; the server imports it only when its SHA-256 and size match `reference`, and the resumed computer gets a new incarnation. Session storage survives a stop, holds 1 GB, and is wiped when the runtime is updated. When there is no matching copy, the generation is still running, or the restore fails, `aresume` raises and the caller restores from the store into a new generation as usual. A resume saves the checkpoint transfer: on staging, a 200 MB workspace was ready again in 2.8 seconds by resume and 37.9 seconds by cold restore, and a 60 KB one in 1.3 and 2.1 seconds. |
| Credentials | Codex logs in with `OPENAI_API_KEY` only when no stored login matches it: checkpoints exclude `auth.json`, so a restored computer logs in again, and a ChatGPT login the user set up is kept. Code in the sandbox can use the runtime's IAM role through the metadata service. Give the role only the model access the harness needs. The runtime server shares the agent's UID, so its token does not separate the two; the agent could already write the runtime journal. |
| Limits | Commands run for at most 3,500 seconds; the command client waits up to an hour and three minutes for the result, which leaves room for AgentCore's 3,600-second cap. Argv and stdin go in a staged request of at most 12 MiB once encoded. Checkpoints are limited to 2 GiB, and the provider refuses a larger `CheckpointLimits.max_bytes` when the transfer is built. Export and import wait on the same long-timeout client, since the computer allows them 14 minutes. At the claimed lifetime the computer refuses work, ends the agent's processes and exits the entrypoint. `/tmp` is not size-limited, so a runaway command can fill the microVM's own disk. |
| Bursts | The default quota is 25 new sessions per second per account. The provider retries throttled calls with jitter; `agentcore_load.py` completed 497 of 500 simultaneous sessions, so pace larger bursts or raise the quota. Set `max_connections` to the number of sessions one process serves at once. With 1,000 sessions alive at once from one host every call succeeded; at 2,000, AWS's load balancer in front of AgentCore answered most calls with an HTML 403 before they reached the service, so spread that many sessions across hosts. |

## Boundaries

- The image, Docker daemon and its administrator are trusted. This is not a hostile multitenant isolation service.
- UID/GID 1000, read-only image filesystem, dropped capabilities, no privilege escalation, explicit CPU/memory/process limits, no host bind mounts or Docker socket mounts.
- Networking defaults to `none`. A harness that needs the network should use `network="isolated"`: the provider creates one bridge per host, `agno-sandbox`, labelled as Agno-managed, with inter-container traffic off and a pinned subnet (`subnet`, default `172.30.0.0/22`), so sandboxes reach the internet and the host's published ports but not each other. One network serves every namespace on the host: with inter-container traffic off, sharing it adds no reach between sandboxes, and the pinned subnet never draws from Docker's default address pools, which allow only a few dozen networks per host. A `/22` keeps the network under the roughly one thousand interfaces one bridge can carry; a host that needs more sandboxes than that needs a second daemon. Every replica must configure the same subnet; a mismatch, an overlap with another network on the host, or a same-named network the provider did not create each fail with a `SandboxError` that says what to change. `destroy` leaves the network in place and `remove_network` deletes it when nothing is attached. Docker's default `bridge` is accepted but puts every sandbox on `docker0`, where they can reach each other and anything bound on the host; an operator-managed network is accepted as is. Host and other-container network sharing are rejected. The isolated bridge does not block a sandbox from reaching services listening on the host itself; that needs a `DOCKER-USER` firewall rule or binding those services away from the bridge. Egress policy and DNS filtering belong to deployment infrastructure.
- Only explicitly configured environment values are added to the image environment. Do not put AgentOS database/Redis credentials in the image or sandbox environment. Image-baked credentials are also visible to repository code.
- `/workspace` and `/runtime` (`HOME`) use Docker-managed bounded tmpfs volumes, allowing daemon checkpoint transfer while the container is paused. `/tmp` is a container tmpfs. Stopping or removing compute loses these files. A later checkpoint layer must establish durability before completed-turn recovery can be promised.
- Command output is bounded by raw bytes, then decoded with UTF-8 replacement. Timeouts, excessive output, cancellation and uncertain command transport stop the whole container to terminate remote child processes. A stop failure is an infrastructure error requiring reconciliation; do not start a replacement writer until shutdown is confirmed. Completed commands can intentionally leave background applications running.
- Caller cancellation during creation may leave an allocated container. Reconcile by calling `create` again with the same identity/configuration; do not invent another generation until the previous allocation is accounted for.
- `pause` and `resume` are the warm path between turns. A paused container keeps its files, memory and processes under the kernel freezer; `resume` brings the same generation back running with nothing to restore. `create` refuses a paused generation, because only the caller that paused it knows its files are whole; anyone else destroys it and recovers a new generation from the checkpoint. Commands are refused while paused. `stop` and `destroy` remain the cold path and lose the tmpfs files, so a later turn needs a new generation restored from a checkpoint. Pausing does not replace checkpoints: a paused container is still tied to one host.
- No preview, nested Docker, artifact API, shared admission, checkpoint or terminal-success semantics are implied by this sandbox.

## Validation

```bash
.venv/bin/python -m pytest libs/agno/tests/unit/sandbox -q
AGNO_TEST_DOCKER_IMAGE=python:3.12-slim .venv/bin/python -m pytest libs/agno/tests/integration/sandbox -q
```

Integration tests use unique namespaces and remove only their own containers. See [TEST_LOG.md](TEST_LOG.md) for the tested environment and limits.

## Checkpoint archive and storage

```bash
.venv/bin/python cookbook/frameworks/sandbox/checkpoint_files.py
```

This credential-free example captures real filesystem roots, uploads an immutable object, deletes the original files, and restores them through another store instance. `CheckpointArchive` requires `workspace` and `native` roots and a JSON state manifest. `FileCheckpointStore` stores immutable SHA-256-addressed bytes with size/checksum verification and atomic publication, and is the first implementation of the `CheckpointStore` protocol. Reading an object that storage no longer holds raises `CheckpointObjectNotFound`, so a service can tell storage loss apart from a checkpoint it merely cannot serve. Read an object back through `open_archive`, which verifies it and then yields a path valid for the duration of the context, which retention removing the object meanwhile does not invalidate; a store whose objects are remote materializes a temporary copy there and removes it on exit, while a local object is never removed by reading it. Both classes provide sync and async operations.

Drain native SDK writes and quiesce all applications before capture. The native root must contain only restorable state; keep credentials outside it or explicitly exclude credential paths. Exclusions are exact relative paths (and their descendants), not glob expressions. The two roots must be disjoint, and capture refuses them otherwise: an exclusion names one archive prefix, so a root containing the other would carry an excluded file in under that other prefix. Capture also refuses a hardlink that would carry an excluded file's contents out under another name, for as long as the excluded path itself exists; once the original is deleted a surviving link cannot be told from an ordinary file, so break such links rather than relying on the exclusion. Ignored and untracked workspace files are included. Safe relative symlinks, file permissions and modification times survive; hardlinked source files become separate files. Special files, escaping/cyclic links and malicious archives are rejected. Archives are gzip-compressed by default; `CheckpointArchive(compress=False)` writes plain tar, and either stored representation is read back whatever the reader's own setting is. Archive limits bound bytes, entry counts and metadata. The byte limit measures the expanded archive, entry framing included, on write as much as on read: a capture that succeeds is one restore accepts, and a decompression bomb is rejected before it is written. The digest and size in a reference always describe the stored bytes. Restore validates all paths before materializing into a new directory. Restore never updates a running workspace in place.

The object directory and restore parent must be trusted coordinator-owned paths, never mounted into sandbox compute or exposed to agent tools. Production storage must survive the intended failure domain, for example a suitably configured shared filesystem; a service-local directory does not provide host-loss recovery. The demo uses temporary local disk and proves filesystem semantics only. Objects are not deleted when compute is destroyed; `delete` exists for a retention reconciler, which is separate and does not ship here.

### Required filesystem capabilities

Checkpoint file reads require `os.O_NOFOLLOW`; the implementation refuses to read without it instead of following a symlink. `FileCheckpointStore` also requires hard links for immutable publication and reader leases, file and directory `fsync` for durability, and atomic rename for archive restore. Restoring symlinks requires symlink creation and timestamp updates with `follow_symlinks=False`. These requirements apply to the host running the checkpoint code and its filesystem, regardless of the Docker container image.

A missing `O_NOFOLLOW`, or an explicitly unsupported hard-link or directory-sync operation, raises an actionable `SandboxError`. The underlying operation error is retained as its cause. Permission, disk-full and other I/O errors propagate unchanged; no protection or durability step is silently skipped. Capabilities are checked when used, not certified at construction: a failed directory sync can occur after an object has been linked or deleted, so an error does not mean nothing changed. Do not publish a checkpoint reference from a failed upload.

Windows support has not been established or tested for this checkpoint implementation. These checks report unavailable primitives; they do not add a Windows fallback. Use a host and filesystem that provide the required capabilities.

An upload is not a completed run. A following coordinator transaction must publish the checkpoint reference together with authoritative conversation/native metadata and terminal run state, fenced against the current session generation. These archive/store primitives do not implement that transaction, SDK capture, Docker transport or automatic session recovery. Async cancellation waits for in-progress filesystem work to finish, so cleanup does not race a background writer; callers must reconcile whether that operation completed.

## Reconnectable runtime journal

Build the runtime from public package sources only, then run a deterministic fixture:

```bash
.venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
.venv/bin/python cookbook/frameworks/sandbox/runtime_journal.py
AGNO_TEST_RUNTIME_IMAGE=agno-sandbox:local .venv/bin/python -m pytest libs/agno/tests/integration/sandbox/test_runtime.py -q
```

The build sends a temporary context containing package sources and public packaging files, excluding local environments, credentials and unrelated working-tree files. It pins the Python base digest, Claude SDK, Codex SDK and SQLAlchemy; transitive packages and Debian packages are resolved at build time. Record the resulting image digest and dependency list for deployments. Docker's init process reaps detached runtime children.

`SandboxRuntimeClient` has sync/async start, poll, page iteration, wait and cancel operations. Start identity is `execution_id`, scoped to the session computer; retries with identical configuration/input attach to the existing execution. Different input under the same identity is rejected. The runtime also binds itself to one agent/session and permits one active writer. Its lock is a defensive local check, not a replacement for durable queue admission.

Polling uses byte cursors into the bounded event journal. Reconnecting or replaying does not invoke the SDK again. A completion/poll race cannot hide final events. A dead worker returns `execution_unknown`; callers must reconcile effects before choosing a new execution identity. Poll timeout/cancellation detaches the caller, while explicit runtime cancellation stops the whole computer and loses ephemeral files. Runtime control RPC failures leave compute available for reconciliation by its current owner. They never implicitly stop a model turn. Arbitrary command execution retains its stop-on-failure behavior.

The deterministic `fixture` SDK requires the explicit test-only environment flag used in the example. It does not call a model. Production runtime requests accept `claude` or `codex` and JSON-compatible adapter configuration. Model/MCP credentials must be explicitly provisioned through the compute environment; broad service credentials must stay outside. SDK retries are disabled here so the coordinator owns retry decisions. Local SQLite is a native-state cache inside the computer; it is not the authoritative AgentOS database. `/runtime/native` contains the local session cache and SDK home directories. Quiesce it before capture, and exclude or separately provision SDK credential files.

Runtime frames deliberately suppress service terminal events. `execution_finished` includes the SDK run and local session metadata; its run may have succeeded, failed or been cancelled. AgentOS must validate the result, capture native/workspace state, fence ownership and atomically commit recovery metadata before publishing a successful terminal event. This PR does not yet register a sandbox agent in AgentOS, import existing Phase 1 sessions, stage remote media, provide historical workspace replay, or implement that durable completion transaction. Live Claude/Codex authentication and native recovery remain separate acceptance work. Do not interpret fixture acceptance as live SDK certification.


## Destroy and replace a session computer

```bash
AGNO_SANDBOX_IMAGE=agno-sandbox:local .venv/bin/python cookbook/frameworks/sandbox/replace_computer.py
```

The example clones a deterministic local Git fixture, edits tracked code, runs its tests, and creates ignored/untracked files and a native-state fixture. It captures one immutable checkpoint, destroys compute and its volumes, restores into generation 2, reruns the application tests, then retrieves an artifact after all compute is gone. No network or model credentials are required.

`CheckpointTransfer` is the provider-neutral protocol a coordinator depends on: sync/async capture returning a `CheckpointRef`, restore returning the manifest state, and the `CheckpointStore` it uses. Only the transport differs per provider; the archive format, exclusions and store are shared. `DockerCheckpointTransfer` is its Docker implementation and provides sync/async capture and restore. Capture pauses compute for two bounded raw archive exports, resumes it, then validates and uploads the combined archive. Docker never extracts an untrusted archive on the service host. Restore verifies the immutable checkpoint, requires an empty computer, and writes directly into the writable managed volumes while preserving UID 1000 access. Failure after partial restoration stops that generation. The managed roots retain their configured ownership/permissions; permissions beneath the roots are restored.

Plain container tmpfs is rejected by the transport: Docker can return a successful but empty copy for it. The provider now creates labeled, bounded, daemon-visible tmpfs volumes and verifies their configuration on reuse. Destruction removes only matching owned volumes, including recovery after a lost container-removal response. A failed create before a container exists removes its unmounted volumes, so a corrected configuration can retry the same generation; a coordinator crash in that window can still leave labeled empty volumes for reconciliation. A paused generation is never resumed implicitly: `create` and `exec` reject it, because a warm pause looks the same as an interrupted capture or a partial restore. Only the caller that paused it calls `resume`; anyone else uses `stop` or `destroy`, then a new generation. These volumes still provide no host-loss durability; the external checkpoint store does.

The caller must hold exclusive generation ownership and finish/drain the SDK before capture. Applications requiring logical database backups need an explicit quiesce/backup procedure; pausing processes only establishes a filesystem capture boundary. No nested-container or anonymous-volume data is included. Current capture uses local staging space for raw and combined archives in the coordinator's object directory; provision several times the checkpoint byte limit per concurrent capture. A transfer is bounded to 120 seconds per root. These limits intentionally fail finalization rather than publish an incomplete recovery point.

The known Codex `auth.json` and Claude `.credentials.json` paths are excluded by default. These defaults are not a secret scanner: use explicit exclusions or keep other credentials outside durable roots. Passing `exclude` replaces the default list. Keep native credentials provisioned separately for restored compute. Atomic run/conversation/checkpoint publication still belongs to the following AgentOS coordinator layer.

Archive validation stays strict: absolute or root-escaping symlinks and special files such as FIFOs fail capture, and the error names the offending path. Virtual environments usually link `bin/python` to the image interpreter by absolute path, so exclude them and recreate them after restore from the project's lock file:

```python
ref = transfer.capture(handle, state=state, exclude=(*DEFAULT_NATIVE_EXCLUSIONS, "workspace/.venv"))
...
transfer.restore(new_handle, ref)
sandbox.exec(new_handle, ["sh", "-c", "cd /workspace && python -m venv .venv && .venv/bin/pip install -r requirements.txt"])
```

Reinstalling needs network access or a local package source, since sandbox networking defaults to `none`. Exclusions are never inferred, so dependencies are not dropped silently.

## Native recovery: the sandbox never runs a turn on state it cannot verify

```bash
.venv/bin/python cookbook/frameworks/sandbox/native_recovery.py
```

A harness turn continues its own native conversation from files under `/runtime/native`. After a cold replacement those files come back from a checkpoint, and three guards make sure a restore that did not land whole cannot pass as a finished turn. First, the caller passes the native id it committed for the session as `native_session_id` on `start`; before the model runs, the runtime checks that the local database records exactly that conversation and otherwise reports an execution error with reason `native_state_missing`. This is the only check that catches a lost database, since without a session row the adapter would treat the turn as a new conversation. Second, the runtime constructs the adapters with `require_native_resume=True`, so when the SDK cannot resume the recorded native session the turn errors and the stored id is kept, instead of the laptop fallback of starting a new conversation with the chat history pasted into the prompt. Third, `strict_persistence=True` makes a failed local write fail the turn, and the runtime reads its own run row back before returning a result. Ordinary SDK users keep the fallback defaults unless they enable these options.

The example walks the whole path on one Claude session, through five generations of the same container. Turn 1 runs, the session is checkpointed with `DockerCheckpointTransfer`, and the container is destroyed. Generation 2 is restored from the checkpoint and turn 2, with the committed native id as its expectation, recalls the conversation: the cold path working. Generation 3 is created with the restore skipped, standing in for a restore that did not land, and a turn without an expectation starts a new native session, answers NONE and reports COMPLETED: the old outcome, a fork a coordinator could not detect. Generation 4, restore skipped again, is refused before the model runs with `native_state_missing` when the committed id is passed. Generation 5 is the coordinator's reaction: replace the generation, restore the same checkpoint, start again with the same expectation, and the session is whole. A coordinator derives the expectation from the native id it published with the last committed checkpoint and leaves it unset for a session's first turn.

## How a turn completes

The store is internal: the coordinator builds it from the agent's `PostgresDb`. Its lease table lives in that same database, named by `PostgresDb(sandbox_table=...)` (default `<session_table>_sandbox_bindings`, since each bindings table has a foreign key to exactly one session table), and is created on first use like every other agno table, so there is no setup call. Async methods support both Postgres adapters; synchronous methods require `PostgresDb`.

A runtime result is staged first. A verified checkpoint reference and provider-confirmed compute cleanup are required before one transaction publishes the run and session recovery reference. Lease epochs and queue attempts fence previous coordinators. Native session data is nested under `session_data.sandbox.native`. The run takes only runtime output fields (content, messages, tools, metrics, media, events, status) from the result; identity, input, lineage and service metadata stay as stored, and runtime metadata is nested under `metadata.sandbox.native_metadata`. The store keeps nothing it depends on in `session_data`, so editing a session mid-run is safe. The binding row has a foreign key to its session with `ON DELETE CASCADE`: deleting a session deletes its binding, a recreated session (even with the same id, `created_at` and run id) starts from a fresh binding, and every lease carries its binding's incarnation, so a coordinator still holding a lease for the deleted session is refused. The store then no longer tracks a computer that was running for the deleted session; providers should sweep orphaned computers by their labels. The binding's `checkpoint` is the authoritative recovery point. `session_data.sandbox` is a copy for readers, and a stale session upsert can overwrite it.

## Session coordinator

`SandboxCoordinator` runs a session's turns on sandbox computers with durable recovery. These three cookbooks use only its public API and the credential-free fixture runtime; build the runtime image and start pgvector first:

```bash
./cookbook/scripts/run_pgvector.sh
.venv/bin/python cookbook/frameworks/sandbox/build_image.py
```

| Cookbook | What it shows |
|----------|---------------|
| `session_computer.py` | Several turns of one session, each on a fresh computer restored from the last checkpoint; retrying a finished run returns its stored result |
| `resume_after_disconnect.py` | The caller drops mid-turn, the turn keeps running in its container, and another coordinator reattaches to it |
| `cancel_turn.py` | A cancelled turn publishes nothing; the next turn continues from the last completed one |

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

Provider mutation operations hold the session ownership rows until their bounded transport calls drain. Takeover waits for an in-flight restore/capture instead of racing it. This costs a database connection and can delay cancellation until a transfer finishes. The initial implementation uses cold replacement after every completed turn; no warm-computer reuse is claimed.

Each active turn costs the database: one held connection during a provider call, a lease check per poll page, and a heartbeat renewal every third of the lease. Polls long-poll inside the container for up to `poll_wait` seconds (default 5) and return as soon as there are events, so an idle turn makes about one poll and one lease check per `poll_wait`. `poll_wait` also bounds how long a cancellation can go unnoticed while a turn emits nothing. Size the `PostgresDb` connection pool for the number of concurrently active sessions plus the rest of the application; the default pool is small.

Use deployment storage accessible to every coordinator replica for checkpoint bytes. The local directory store in these examples is temporary and does not certify host-loss recovery. Workspace and native files restore; live processes restart, and remote MCP/tool effects are not rolled back. Direct stream reconnection may repeat provisional events; durable event transport remains an AgentOS integration responsibility.

## AgentOS API execution

`agentos.py` registers a `ClaudeAgent` or `CodexAgent` with `sandbox=DockerSandbox(...)`, a durable Postgres queue and shared Redis cancellation/event transport. The agent builds its coordinator from the AgentOS `db` on first use; there is no store or coordinator to construct. `DockerSandbox(checkpoints=...)` names the checkpoint storage (the host-local default `~/.agno/sandbox/checkpoints` is refused once a queue worker is active, since another replica may run the next attempt), `env=` adds variables over the harness's model API key forwarded from the service environment, and `execution_timeout=` bounds one turn. Foreground, streaming and background API requests all submit to the queue; losing the HTTP connection does not cancel the worker. Independent sessions run concurrently; overlapping turns in one session wait without consuming attempts. Direct Python `run`/`arun` use the coordinator's Postgres fence. Python background submission requires the active AgentOS queue.

Build the runtime image with `build_image.py`, install `psycopg[binary]`, `redis`, `docker` CLI, `fastapi` and `uvicorn` in the service environment, and configure:

```bash
export SANDBOX_DATABASE_URL=postgresql+psycopg://ai:ai@localhost:5573/ai
export SANDBOX_REDIS_URL=redis://localhost:6407/0
export SANDBOX_CHECKPOINT_DIRECTORY=/absolute/path/to/durable/shared/checkpoints
export SANDBOX_RUNTIME_IMAGE=agno-sandbox:local
export SANDBOX_HARNESS=fixture
.venv/bin/python cookbook/frameworks/sandbox/agentos.py
```

The fixture harness (`agno.sandbox.fixture.FixtureAgent`) makes no model calls. For a real harness select `claude` or `codex` and configure its model API key. The example uses `network="isolated"` for those harnesses so they can reach their model API; customer network policy must control its egress. Every replica must reach the same Docker daemon, checkpoint storage, Postgres and Redis and use identical runtime configuration. Multiple independent Docker daemons are not interchangeable for an active computer. Local checkpoint directories do not provide host-loss durability unless backed by shared durable storage.

```bash
curl -X POST http://localhost:7777/agents/coder/runs \
  -H 'Idempotency-Key: first-turn' \
  -F session_id=example -F message='Create a small application and test it' \
  -F stream=false -F background=true
```

Keep the returned run ID. Reconnect with `POST /agents/coder/runs/{run_id}/resume` using form fields `session_id` and optionally `last_event_index`; cancel with `POST /agents/coder/runs/{run_id}/cancel?session_id=example`. Reusing an idempotency key requires the same session ID, input and options. Conflicting submissions return 409. Streaming terminal success follows the durable checkpoint commit. Retained indexed events support replay after the live Redis view expires; content deltas follow the agent's `events_to_skip` policy.

Agent settings travel to the sandbox as JSON, including structured-output schemas; callbacks, native option objects (`options`, `client_options`) and host paths (`cwd`, `codex_bin`) are rejected when the agent is constructed. Running a native `Agent` inside a sandbox is not supported yet: `Agent(sandbox=...)` raises. File/image inputs, step replay/fork, version-pinned instances and arbitrary per-turn SDK options are explicitly rejected pending checkpoint-aware integrations. Do not use the ordinary session deletion API to retire sandbox resources; coordinated lifecycle/retention is a separate follow-up. A failed checkpoint upload retries finalization without repeating the model. If the configured queue attempts are exhausted, compute is removed and the turn fails visibly while retaining the previous checkpoint. External effects can still repeat after execution crashes and need application idempotency.
