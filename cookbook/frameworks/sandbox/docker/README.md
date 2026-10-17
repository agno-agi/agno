# Docker sandbox cookbooks

`DockerSandbox` gives each session its own container on a Docker daemon you operate, for trusted teams. The concepts shared with other providers, the checkpoint archive, how a turn completes and the session coordinator, are in the [parent README](../README.md); this folder shows the Docker provider end to end.

## Warm reuse between turns

```bash
.venv/bin/python cookbook/frameworks/sandbox/docker/warm_reuse.py
```

The example does a turn's worth of work, writing a file and leaving a background process running, then pauses the container. Pausing uses the kernel freezer: files, memory and processes stay exactly as they are, no bytes are copied anywhere, and commands are refused until the container resumes. The next turn calls `resume` and gets the same container back running, with the file present and the background process continuing from where it froze; `create` on the paused generation is refused. The example then stops the container to show the cold path: the tmpfs files are gone, the generation cannot restart, and the next turn needs generation 2 restored from a checkpoint.

`pause`, `resume` and their async counterparts are part of the `Sandbox` contract. A provider without a native pause raises `NotImplementedError`, so a caller can fall back to keeping the container running or to the cold path. A paused container is still tied to one host and still counts against its memory, so pausing complements checkpoints rather than replacing them: checkpoints remain the recovery path when the host or the container is gone.

## The smallest sandboxed agent

```bash
export ANTHROPIC_API_KEY=...   # or CLAUDE_CODE_OAUTH_TOKEN
.venv/bin/python cookbook/frameworks/sandbox/docker/sandbox_claude.py
```

`sandbox_claude.py` is a `ClaudeAgent` with a `PostgresDb` and `sandbox=DockerSandbox(image)`, nothing else. It runs two turns on a new session: the first writes and runs a file, the second asks what file was created. Each turn runs the whole Claude Code process in a container from the image; when it completes, its workspace and Claude Code's own conversation are checkpointed and the container is removed, and the next turn starts a fresh container restored from that checkpoint, which is how turn 2 knows the file name. The credential in the process environment (`ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`) is forwarded into the container. Checkpoints default to `~/.agno/sandbox/checkpoints`, which suits a single host.

The agent needs the network to reach its model API, so this and every other cookbook with a real harness use `network="isolated"`: one bridge per host with a pinned subnet, `172.30.0.0/22` by default (see Boundaries). On a host where another Docker network already uses that range, `create` is refused with the overlap named; set `AGNO_SANDBOX_SUBNET` to a free range for the cookbooks, and `AGNO_TEST_SANDBOX_SUBNET` for the integration tests:

```bash
export AGNO_SANDBOX_SUBNET=10.213.0.0/22
AGNO_TEST_SANDBOX_SUBNET=10.213.0.0/22 AGNO_TEST_RUNTIME_IMAGE=agno-sandbox:local .venv/bin/python -m pytest libs/agno/tests/integration/sandbox/test_runtime.py -q
```

Every process sharing the host's bridge must use the same subnet; remove the bridge with `remove_network` while nothing is attached before changing it.

`sandbox_claude_agentos.py` serves the same agent through AgentOS with a durable queue (Postgres and Redis). Every API request submits to the queue, a dropped connection does not cancel the turn, and a second request on the same session waits for the first. It names its checkpoint store explicitly: with a queue, any replica may run the next attempt, so the default host-local store is refused.

## Attachments

```bash
.venv/bin/python cookbook/frameworks/sandbox/docker/sandbox_attachments.py
```

`run`/`arun` on a sandboxed `ClaudeAgent` or `CodexAgent` accept `images=` and `files=`, and the AgentOS run route accepts them as uploads (`-F files=@photo.png`). Only bytes cross into the sandbox: each attachment is written under `/workspace/.agno/uploads/<run_id>/` and named in the prompt, and the turn's checkpoint keeps it, so later turns on a new computer can still read it. Images given without a format take one from their file suffix or byte signature. A request carries at most 16 attachments and 512 KiB in total. URLs, media references and, over HTTP, server file paths are refused; audio and video are rejected. A `File` whose MIME type is not a document type is refused with a pointer to `images=`, but a `File` given without a MIME type is accepted as a document whatever its bytes, so pass pictures as `images=`. Queued runs store the attachments with the submission, so a retry sends the same bytes, and reusing an idempotency key with different attachments returns 409.

## A live Claude session in a sandbox

```bash
export ANTHROPIC_API_KEY=...   # or CLAUDE_CODE_OAUTH_TOKEN
.venv/bin/python cookbook/frameworks/sandbox/docker/claude_runtime.py
```

The example runs two Claude turns on one session inside a container built from the runtime image, with a pause between them. Turn 1 asks Claude to write and run a program; its tool calls and content stream back through the runtime journal, the file lands in `/workspace`, and Claude Code's own session is kept under `/runtime/native` next to the local history database. The container is then paused and resumed. Turn 2 asks, without tools, what the previous turn did. Claude answers from its native session, and the example asserts the Claude session id recorded on the local session row is the same for both turns.

Only the selected model credential is forwarded into the container environment. `runtime_config` holds the `ClaudeAgent` settings (model, permission mode, allowed tools, turn limit); the runtime adds the workspace, the local database and the strict settings itself. The execution result is output, not a completed run: this example drives the runtime directly and writes nothing outside the container. `SandboxCoordinator` (see Session coordinator) is what checkpoints a result and commits it to the service database.

## Runtime transport: exec or an in-container server

The host reaches the runtime two ways. By default `DockerSandbox` starts the container with a sleep entrypoint and every runtime request spawns `python -m agno.sandbox.runtime` through `docker exec`: it works on any image that carries the package and needs no port, but each request is a process through the Docker daemon. With `runtime_port` set, the container's entrypoint is the runtime itself as a small HTTP server, Docker publishes that port on the host's loopback only, and `rpc` becomes a pooled connection: `POST /start`, `POST /poll`, `GET /health`. Same JSON, same journal, same locks; the daemon is used for create, pause, resume, stop and destroy and nothing else. `create` waits for `/health` before handing the sandbox out. The server needs a network, so `runtime_port` is refused with `network="none"`.

```python
sandbox = DockerSandbox("agno-sandbox:local", network="isolated", runtime_port=8765)
# Replicas on other hosts sharing this daemon: advertise the daemon host's address instead.
shared = DockerSandbox("agno-sandbox:local", network="isolated", runtime_port=8765, runtime_host="10.0.0.5")
```

Polls long-poll on both transports: the container holds a `poll` for up to `wait` seconds (default 10, cap 30) and answers as soon as the journal grows or the result lands, so an idle turn costs one request per `wait` and events arrive when they are written. `wait=0` restores the sleep-between-requests loop.

```bash
AGNO_SANDBOX_LOAD_SESSIONS=8 .venv/bin/python cookbook/frameworks/sandbox/docker/runtime_transport_load.py
```

The example runs the same concurrent fixture turns three ways and prints requests per turn, Docker daemon calls per turn and the cost of an idle poll. Requests and daemon calls per turn are what grow with concurrent users; the idle poll is the per-request overhead of the transport. The exec transport with a poll loop is the pre-long-poll behaviour and the reference point.

Every container gets its own bearer token, generated at create, delivered through the private env file and read back onto the handle as `runtime_token`, so any replica holding the handle can talk to the server and nothing else can. Where the token is inside the container, precisely: the supervisor takes it out of its environment at startup and hands it to the server on stdin, so the serving process holds it only in memory; workers are spawned without it, so the agent's tools do not find it in their environment; every `docker exec` from the host runs with the variable blanked. What remains: the token is delivered through the container's environment so the host can read it back from the daemon, and the exec-time environment of PID 1 and of the supervisor still contains it, readable through `/proc` by anything running as the same UID. A determined agent can therefore still recover it, and it only ever grants what that container's own server does, which the agent can already drive by writing the journal; a sandbox must not be able to reach another sandbox's port (see networking). Running the server under a separate UID is the follow-up that makes the token unreachable. The port is published on `runtime_host`, `127.0.0.1` by default, which only this host's replicas reach and which the container's gateway does not. With one Docker daemon shared by replicas on several hosts, set `runtime_host` to the daemon host's address those replicas can reach; that network must be trusted, since the token travels over plain HTTP, and the value is part of the generation's configuration, so every replica must use the same one. Hosted providers implement `rpc` against the same server and the same token through whatever port exposure they offer.

With `runtime_port` set, the container's main process is a supervisor (`python -m agno.sandbox.runtime supervise`) under Docker's init. It runs the HTTP server as a child and restarts it with backoff if it exits; workers run detached, so a server crash does not touch a turn, and the host sees at most a short gap that the cursor-based reconnect absorbs. `SIGTERM`, which Docker sends on `stop`, ends the server and the supervisor.

```bash
.venv/bin/python cookbook/frameworks/sandbox/docker/runtime_resilience.py
```

The example prints every event as it arrives with its cursor and elapsed time. It runs a fixture turn and shows the variables the turn could see, with the token absent; starts a turn that streams eight events over four seconds, kills the server with `SIGKILL` after the second one, and shows the host's polls failing for a few hundred milliseconds, the supervisor bringing the server back, and the remaining events arriving from the same cursor with nothing missing or repeated; then forces a control request on the exec transport to time out and shows the container still running and the turn still finishing.

Without `runtime_port`, `rpc` falls back to exec with the rule of a control request: a failed or lost reply raises and leaves compute alone, never stopping the container, since start and poll exit on their own and are idempotent. Arbitrary `exec` keeps its stop-on-uncertainty rule. `runtime_port` and `runtime_host` are part of the generation's config digest, so changing them, including flipping a default, makes `create` refuse every live generation; treat such a change as a migration that drains sessions rather than a rolling deploy.

## Boundaries

- The image, Docker daemon and its administrator are trusted. This is not a hostile multitenant isolation service.
- UID/GID 1000, read-only image filesystem, dropped capabilities, no privilege escalation, explicit CPU/memory/process limits, no host bind mounts or Docker socket mounts.
- Networking defaults to `none`. A harness that needs the network should use `network="isolated"`: the provider creates one bridge per host, `agno-sandbox`, labelled as Agno-managed, with inter-container traffic off and a pinned subnet (`subnet`, default `172.30.0.0/22`), so sandboxes reach the internet and the host's published ports but not each other. One network serves every namespace on the host: with inter-container traffic off, sharing it adds no reach between sandboxes, and the pinned subnet never draws from Docker's default address pools, which allow only a few dozen networks per host. A `/22` keeps the network under the roughly one thousand interfaces one bridge can carry; a host that needs more sandboxes than that needs a second daemon. Every replica must configure the same subnet; a mismatch, an overlap with another network on the host, or a same-named network the provider did not create each fail with a `SandboxError` that says what to change. `destroy` leaves the network in place and `remove_network` deletes it when nothing is attached. Docker's default `bridge` is accepted but puts every sandbox on `docker0`, where they can reach each other and anything bound on the host; an operator-managed network is accepted as is. Host and other-container network sharing are rejected. The isolated bridge does not block a sandbox from reaching services listening on the host itself; that needs a `DOCKER-USER` firewall rule or binding those services away from the bridge. Egress policy and DNS filtering belong to deployment infrastructure.
- Only explicitly configured environment values are added to the image environment. Do not put AgentOS database/Redis credentials in the image or sandbox environment. Image-baked credentials are also visible to repository code.
- `/workspace` and `/runtime` (`HOME`) use Docker-managed bounded tmpfs volumes, allowing daemon checkpoint transfer while the container is paused. `/tmp` is a container tmpfs. Stopping or removing compute loses these files; durability comes from the checkpoint store (see Checkpoint archive and storage), not from the volumes.
- Command output is bounded by raw bytes, then decoded with UTF-8 replacement. Timeouts, excessive output, cancellation and uncertain command transport stop the whole container to terminate remote child processes. A stop failure is an infrastructure error requiring reconciliation; do not start a replacement writer until shutdown is confirmed. Completed commands can intentionally leave background applications running.
- Caller cancellation during creation may leave an allocated container. Reconcile by calling `create` again with the same identity/configuration; do not invent another generation until the previous allocation is accounted for.
- `pause` and `resume` are the warm path between turns. A paused container keeps its files, memory and processes under the kernel freezer; `resume` brings the same generation back running with nothing to restore. `create` refuses a paused generation, because only the caller that paused it knows its files are whole; anyone else destroys it and recovers a new generation from the checkpoint. Commands are refused while paused. `stop` and `destroy` remain the cold path and lose the tmpfs files, so a later turn needs a new generation restored from a checkpoint. Pausing does not replace checkpoints: a paused container is still tied to one host.
- No preview, nested Docker or artifact API is implied by this sandbox. Shared admission, checkpoints and terminal-success semantics belong to the coordinator and AgentOS layers described below, not to the provider.

## Reconnectable runtime journal

Build the runtime from public package sources only, then run a deterministic fixture:

```bash
.venv/bin/python cookbook/frameworks/sandbox/build_image.py --tag agno-sandbox:local
.venv/bin/python cookbook/frameworks/sandbox/docker/runtime_journal.py
AGNO_TEST_RUNTIME_IMAGE=agno-sandbox:local .venv/bin/python -m pytest libs/agno/tests/integration/sandbox/test_runtime.py -q
```

The build sends a temporary context containing package sources and public packaging files, excluding local environments, credentials and unrelated working-tree files. It pins the Python base digest, Claude SDK, Codex SDK and SQLAlchemy; transitive packages and Debian packages are resolved at build time. Record the resulting image digest and dependency list for deployments. Docker's init process reaps detached runtime children.

`SandboxRuntimeClient` has sync/async start, poll, page iteration, wait and cancel operations. Start identity is `execution_id`, scoped to the session computer; retries with identical configuration/input attach to the existing execution. Different input under the same identity is rejected. The runtime also binds itself to one agent/session and permits one active writer. Its lock is a defensive local check, not a replacement for durable queue admission.

Polling uses byte cursors into the bounded event journal. Reconnecting or replaying does not invoke the SDK again. A completion/poll race cannot hide final events. A dead worker returns `execution_unknown`; callers must reconcile effects before choosing a new execution identity. Poll timeout/cancellation detaches the caller, while explicit runtime cancellation stops the whole computer and loses ephemeral files. Runtime control RPC failures leave compute available for reconciliation by its current owner. They never implicitly stop a model turn. Arbitrary command execution retains its stop-on-failure behavior.

The deterministic `fixture` SDK requires the explicit test-only environment flag used in the example. It does not call a model. Production runtime requests accept `claude` or `codex` and JSON-compatible adapter configuration. Model/MCP credentials must be explicitly provisioned through the compute environment; broad service credentials must stay outside. SDK retries are disabled here so the coordinator owns retry decisions. Local SQLite is a native-state cache inside the computer; it is not the authoritative AgentOS database. `/runtime/native` contains the local session cache and SDK home directories. Quiesce it before capture, and exclude or separately provision SDK credential files.

Runtime frames deliberately suppress service terminal events. `execution_finished` includes the SDK run and local session metadata; its run may have succeeded, failed or been cancelled. The service must validate the result, capture native/workspace state, fence ownership and atomically commit recovery metadata before publishing a successful terminal event; `SandboxCoordinator` does that (see How a turn completes) and AgentOS API execution registers the agent. Not provided: moving a session that ran outside a sandbox into one (a first binding on such a session is refused), remote media references, and historical workspace replay. Fixture acceptance is not live SDK certification; the model-backed cookbooks above cover live Claude authentication and native recovery.


## Destroy and replace a session computer

```bash
AGNO_SANDBOX_IMAGE=agno-sandbox:local .venv/bin/python cookbook/frameworks/sandbox/docker/replace_computer.py
```

The example clones a deterministic local Git fixture, edits tracked code, runs its tests, and creates ignored/untracked files and a native-state fixture. It captures one immutable checkpoint, destroys compute and its volumes, restores into generation 2, reruns the application tests, then retrieves an artifact after all compute is gone. No network or model credentials are required.

`CheckpointTransfer` is the provider-neutral protocol a coordinator depends on: sync/async capture returning a `CheckpointRef`, restore returning the manifest state, and the `CheckpointStore` it uses. Only the transport differs per provider; the archive format, exclusions and store are shared. `DockerCheckpointTransfer` is its Docker implementation and provides sync/async capture and restore. Capture pauses compute for two bounded raw archive exports, resumes it, then validates and uploads the combined archive. Docker never extracts an untrusted archive on the service host. Restore verifies the immutable checkpoint, requires an empty computer, and writes directly into the writable managed volumes while preserving UID 1000 access. Failure after partial restoration stops that generation. The managed roots retain their configured ownership/permissions; permissions beneath the roots are restored.

Plain container tmpfs is rejected by the transport: Docker can return a successful but empty copy for it. The provider now creates labeled, bounded, daemon-visible tmpfs volumes and verifies their configuration on reuse. Destruction removes only matching owned volumes, including recovery after a lost container-removal response. A failed create before a container exists removes its unmounted volumes, so a corrected configuration can retry the same generation; a coordinator crash in that window can still leave labeled empty volumes for reconciliation. A paused generation is never resumed implicitly: `create` and `exec` reject it, because a warm pause looks the same as an interrupted capture or a partial restore. Only the caller that paused it calls `resume`; anyone else uses `stop` or `destroy`, then a new generation. These volumes still provide no host-loss durability; the external checkpoint store does.

The caller must hold exclusive generation ownership and finish/drain the SDK before capture. Applications requiring logical database backups need an explicit quiesce/backup procedure; pausing processes only establishes a filesystem capture boundary. No nested-container or anonymous-volume data is included. Current capture uses local staging space for raw and combined archives in the coordinator's object directory; provision several times the checkpoint byte limit per concurrent capture. A transfer is bounded to 120 seconds per root. These limits intentionally fail finalization rather than publish an incomplete recovery point.

The known Codex `auth.json` and Claude `.credentials.json` paths are excluded by default. These defaults are not a secret scanner: use explicit exclusions or keep other credentials outside durable roots. Passing `exclude` replaces the default list. Keep native credentials provisioned separately for restored compute. Atomic run/conversation/checkpoint publication belongs to the coordinator (see How a turn completes).

Archive validation stays strict: absolute or root-escaping symlinks and special files such as FIFOs fail capture, and the error names the offending path. Virtual environments usually link `bin/python` to the image interpreter by absolute path, so exclude them and recreate them after restore from the project's lock file:

```python
ref = transfer.capture(handle, state=state, exclude=(*DEFAULT_NATIVE_EXCLUSIONS, "workspace/.venv"))
...
transfer.restore(new_handle, ref)
sandbox.exec(new_handle, ["sh", "-c", "cd /workspace && python -m venv .venv && .venv/bin/pip install -r requirements.txt"])
```

Reinstalling needs network access or a local package source, since sandbox networking defaults to `none`. Exclusions are never inferred, so dependencies are not dropped silently.

## Opening a run's checkpoint on the host

```bash
AGNO_SANDBOX_IMAGE=agno-sandbox:local .venv/bin/python cookbook/frameworks/sandbox/docker/open_checkpoint.py
```

Two fixture turns of one session through `FixtureAgent`, then each run's checkpoint opened on the host through the agent and restored to a directory. No model credentials are required.

`agent.checkpoint_store` is the `CheckpointStore` the agent's turns write to: the sandbox's `checkpoints=` store, else the host-local default, which is refused while a durable queue worker is active, exactly as the coordinator refuses it. `agent.open_run_checkpoint(run_id)` and `aopen_run_checkpoint` read the committed reference from the run row, have the store verify the object, and yield the archive path for the duration of the context; `CheckpointArchive.restore(path, destination)` extracts it. As with `get_session`, the sync form takes a sync database and refuses an async one, whose pooled connections belong to the loop that first used them. The restored directory holds `workspace/`, the agent's working directory as the turn left it, with the pinned checkout under `workspace/repository` when the agent has `repository=` configured, and `native/`, the harness home, less the credential files excluded at capture. A run that is unknown, belongs to another agent, is not `COMPLETED` or committed no checkpoint is refused with a `ValueError`; an object that retention has removed raises `CheckpointObjectNotFound`.

This is the extraction path for a host process that needs a turn's results after its computer is gone, such as turning an engineer's edits into a patch: open the run's checkpoint, restore it, and diff `workspace/` against the starting tree. The reference on the run row is the one the turn published atomically with its result, so the files always match the run.

## Native recovery: the sandbox never runs a turn on state it cannot verify

```bash
.venv/bin/python cookbook/frameworks/sandbox/docker/native_recovery.py
```

A harness turn continues its own native conversation from files under `/runtime/native`. After a cold replacement those files come back from a checkpoint, and three guards make sure a restore that did not land whole cannot pass as a finished turn. First, the caller passes the native id it committed for the session as `native_session_id` on `start`; before the model runs, the runtime checks that the local database records exactly that conversation and otherwise reports an execution error with reason `native_state_missing`. This is the only check that catches a lost database, since without a session row the adapter would treat the turn as a new conversation. Second, the runtime constructs the adapters with `require_native_resume=True`, so when the SDK cannot resume the recorded native session the turn errors and the stored id is kept, instead of the laptop fallback of starting a new conversation with the chat history pasted into the prompt. Third, `strict_persistence=True` makes a failed local write fail the turn, and the runtime reads its own run row back before returning a result. Ordinary SDK users keep the fallback defaults unless they enable these options.

The example walks the whole path on one Claude session, through five generations of the same container. Turn 1 runs, the session is checkpointed with `DockerCheckpointTransfer`, and the container is destroyed. Generation 2 is restored from the checkpoint and turn 2, with the committed native id as its expectation, recalls the conversation: the cold path working. Generation 3 is created with the restore skipped, standing in for a restore that did not land, and a turn without an expectation starts a new native session, answers NONE and reports COMPLETED: the old outcome, a fork a coordinator could not detect. Generation 4, restore skipped again, is refused before the model runs with `native_state_missing` when the committed id is passed. Generation 5 is the coordinator's reaction: replace the generation, restore the same checkpoint, start again with the same expectation, and the session is whole. A coordinator derives the expectation from the native id it published with the last committed checkpoint and leaves it unset for a session's first turn.

## AgentOS API execution

`agentos.py` registers a `ClaudeAgent` or `CodexAgent` with `sandbox=DockerSandbox(...)`, a durable Postgres queue and shared Redis cancellation/event transport. The agent builds its coordinator from the AgentOS `db` on first use; there is no store or coordinator to construct. `DockerSandbox(checkpoints=...)` names the checkpoint storage (the host-local default `~/.agno/sandbox/checkpoints` is refused once a queue worker is active, since another replica may run the next attempt), `env=` adds variables over the harness's model API key forwarded from the service environment, and `execution_timeout=` bounds one turn. Foreground, streaming and background API requests all submit to the queue; losing the HTTP connection does not cancel the worker. Independent sessions run concurrently; overlapping turns in one session wait without consuming attempts. Direct Python `run`/`arun` use the coordinator's Postgres fence. A direct turn that is interrupted (the process exits, or the call is cancelled) leaves the session busy for new run ids; `agent.cancel_run(run_id)` with the interrupted run's id retires its computer and frees the session. Python background submission requires the active AgentOS queue.

Build the runtime image with `build_image.py`, install `psycopg[binary]`, `redis`, `docker` CLI, `fastapi` and `uvicorn` in the service environment, and configure:

```bash
export SANDBOX_DATABASE_URL=postgresql+psycopg://ai:ai@localhost:5532/ai
export SANDBOX_REDIS_URL=redis://localhost:6379/0
export SANDBOX_CHECKPOINT_DIRECTORY=/absolute/path/to/durable/shared/checkpoints
export SANDBOX_RUNTIME_IMAGE=agno-sandbox:local
export SANDBOX_HARNESS=fixture
.venv/bin/python cookbook/frameworks/sandbox/docker/agentos.py
```

The fixture harness (`agno.sandbox.fixture.FixtureAgent`) makes no model calls. For a real harness select `claude` or `codex` and configure its model API key. The example uses `network="isolated"` for those harnesses so they can reach their model API; customer network policy must control its egress. Every replica must reach the same Docker daemon, checkpoint storage, Postgres and Redis and use identical runtime configuration. Multiple independent Docker daemons are not interchangeable for an active computer. Local checkpoint directories do not provide host-loss durability unless backed by shared durable storage.

```bash
curl -X POST http://localhost:7777/agents/coder/runs \
  -H 'Idempotency-Key: first-turn' \
  -F session_id=example -F message='Create a small application and test it' \
  -F stream=false -F background=true
```

Keep the returned run ID. Reconnect with `POST /agents/coder/runs/{run_id}/resume` using form fields `session_id` and optionally `last_event_index`; cancel with `POST /agents/coder/runs/{run_id}/cancel?session_id=example`. Reusing an idempotency key requires the same session ID, input and options; the response mode is not part of the key, so reusing it with a different `stream` or `background` value returns the original run in the mode of the new request. Conflicting submissions return 409. Streaming terminal success follows the durable checkpoint commit. Retained indexed events support replay after the live Redis view expires; content deltas follow the agent's `events_to_skip` policy.

Agent settings travel to the sandbox as JSON, including structured-output schemas; callbacks, native option objects (`options`, `client_options`) and host paths (`cwd`, `codex_bin`) are rejected when the agent is constructed. Running a native `Agent` inside a sandbox is not supported yet: `Agent(sandbox=...)` raises. Images and files are accepted (see Attachments); audio and video inputs, step replay/fork, version-pinned instances and arbitrary per-turn SDK options are rejected. Do not use the ordinary session deletion API to retire sandbox resources; coordinated lifecycle/retention is a separate follow-up. A failed checkpoint upload retries finalization without repeating the model. If the configured queue attempts are exhausted, compute is removed and the turn fails visibly while retaining the previous checkpoint. External effects can still repeat after execution crashes and need application idempotency.
