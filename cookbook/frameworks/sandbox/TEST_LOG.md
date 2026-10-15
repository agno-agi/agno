# Sandbox test log

### docker_execution.py

**Status:** PASS

**Description:** Real Docker: create, workspace write/read, reuse, deletion. Credential-free local infrastructure only.

**Result:** Passed on 11 October 2026 with `python:3.12-slim`, resolved digest `python@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`. Used the established `.venvs/claude-dx-validation` environment. No model calls, hosted-provider calls or clean-wheel install performed.

---

### sandbox regression tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/sandbox`: 17 tests covering input validation, explicit environment, deterministic identity, lost creation response, ownership, command limits, failure cleanup and sync wrappers. `libs/agno/tests/integration/sandbox/test_docker.py`: 5 tests using real local containers, including non-root/read-only/no-mount/network configuration, file reuse, exit codes, timeout, output limits, cancellation, concurrent creation/deletion.

**Result:** 17 unit tests and 5 real-container tests passed. Initial real deletion race failed when Docker returned “removal already in progress”; fixed by bounded reconciliation, then the complete suite passed. Required formatting and validation passed. This evidence establishes sandbox primitives, not durable AgentOS session recovery or live SDK compatibility.

---

### warm_reuse.py and pause/resume regressions

**Status:** PASS

**Description:** `pause`/`resume` added to the `Sandbox` contract and `DockerSandbox`. `create` refuses a paused generation, because only the caller that paused it knows its files are whole; `resume` is the explicit way back. Unit cases cover pause then create refused and resume returning the same container, resume only from paused, stop and destroy still taking the cold path from paused, and the not-implemented default for providers without a native pause. One real Docker case writes a file, pauses, confirms exec and create are refused, resumes with the file intact, then stops from paused and confirms the generation cannot restart.

**Result:** 36 sandbox unit tests and 7 real Docker cases with `python:3.12-slim` passed. The cookbook passed: the background counter advanced from 7 to 13 across pause and resume, exec and create were refused while paused, create after stop was refused, and generation 2 started empty. `docker_execution.py` passed. `test_command_runner_retains_exit_status_and_bounds_output` failed once with an unrelated intermittent error and passed on five reruns.

---

### checkpoint_files.py and checkpoint regressions

**Status:** PASS

**Description:** Capture conversation metadata, native files and ignored/untracked workspace bytes; upload to an immutable object directory; delete source roots; restore through another store instance. 54 checkpoint tests cover checksums, corruption, missing objects, concurrent upload, partial cleanup, limits, path traversal, hardlink/device rejection, composed symlink escape/cycles, oversized PAX metadata, cancellation draining, credential exclusion through a hardlink and through a root-escaping exclusion, restored timestamps, and cleanup after a failed rename that neither follows a link out of the staged tree nor hides the cause.

**Result:** The cookbook and all 54 checkpoint tests passed on Python 3.9 through 3.14. This layer's files are format- and lint-clean, and type checking reports no new findings. Actual filesystem operations were exercised; no Docker-to-checkpoint transport, live SDK, production shared filesystem or host-loss guarantee was tested by this layer.

---

### checkpoint store protocol, compression and limit symmetry

**Status:** PASS

**Description:** `CheckpointStore` with `FileCheckpointStore` as its first implementation, managed read access through `open_archive`, and gzip-compressed archives by default. 106 checkpoint tests cover the earlier surface and, beyond it: both stored representations round-tripping, and either one read back whatever the reader's own setting is; stored bytes that do not record when a capture ran; two captures of one tree deduplicating to a single object; malformed and hostile compressed archives; expansion stopping at the limit before a whole archive is written; overlapping durable roots refused before anything is written; an absent object raising `CheckpointObjectNotFound` through every sync and async access, while permission, checksum, size and limit failures keep their own types; idempotent deletion; independent lifetimes for repeated and concurrent access, released after a consumer exception and under cancellation; a capture refused when its expanded archive would exceed the limit restore applies to it; an archive whose expanded stream exactly fits still captured and still restored; and an opened object staying readable while retention deletes it.

**Result:** The cookbook and all 106 checkpoint tests passed on Python 3.9, 3.10, 3.11, 3.12, 3.13 and 3.14, with 36 provider tests alongside them. A capture of one unchanged tree produces identical object bytes in both representations on every one of those interpreters, but those bytes differ between 3.9 and 3.12 and later, so objects deduplicate within an interpreter version rather than across a mixed fleet. This layer's files are format- and lint-clean, and type checking reports no new findings. Actual filesystem operations were exercised; no Docker-to-checkpoint transport, live SDK, production shared filesystem or host-loss guarantee was tested by this layer.

---

### runtime_journal.py and runtime protocol acceptance

**Status:** PASS

**Description:** 19 new runtime/client tests cover duplicate dispatch, one-writer locking, event replay, dead-worker uncertainty, incomplete frames, execution timeout, protocol/identity validation, sync/async clients, poll cancellation and a final-event/completion race. All 64 sandbox unit tests passed on Python 3.12 and Python 3.9. Real Docker: 11 combined provider/runtime cases plus one SDK-construction case passed; the reconnect cookbook passed. The construction check instantiates both adapters without authenticating or calling models.

**Result:** Runtime image `sha256:616c3e78f2e95c6e81eda400222ec142ebfffa2383412fcede3a97f966b42317`, Claude SDK 0.2.165, Codex SDK 0.162.1, SQLAlchemy 2.0.52. Required scripts passed in the established validation environment. The initial image build hit an HTTP Debian mirror checksum mismatch; switching the official mirror to HTTPS resolved it with verification retained. The initial SDK-construction assertion inspected a nullable configuration field instead of the engine; corrected the assertion and reran successfully. No live model calls, hosted provider calls or full AgentOS sandbox durability acceptance.

---

### warm_reuse.py and pause/resume regressions

**Status:** PASS

**Description:** `pause`/`resume` added to the provider contract and `DockerSandbox`; `create` refuses a paused generation so only its owner resumes it. Four unit cases cover pause then create refused and resume returning the same container, resume only from paused, stop and destroy still taking the cold path from paused, and the not-implemented default for providers without a native pause. One real Docker case writes a file, pauses, confirms exec and create are refused while paused, resumes with the file intact, then stops from paused and confirms the generation cannot restart. The cookbook adds a background counter to show the frozen process continuing after resume.

**Result:** 100 sandbox unit tests passed on Python 3.12; 7 real Docker provider cases and 7 real runtime cases passed with `python:3.12-slim` and the rebuilt runtime image. The cookbook passed: counter advanced from 6 to 11 across pause and resume, exec while paused refused with the provider's message, create after stop refused, generation 2 started empty. Docker daemon probe confirmed `stop` succeeds on a paused container. No model calls. The coordinator still destroys after every turn; wiring the warm path there is tracked separately.

---

### claude_runtime.py: live two-turn Claude session with a pause

**Status:** PASS

**Description:** Container from `agno-sandbox:local` on `bridge` networking with only `CLAUDE_CODE_OAUTH_TOKEN` forwarded. Turn 1 through `SandboxRuntimeClient` with `sdk="claude"`, `claude-sonnet-4-6`, `bypassPermissions`, tools Read/Write/Bash: Claude wrote `hello.py`, ran it and answered `hello`; Write and Bash tool events and the content arrived through the poll cursor. `/runtime/native` held `.claude`, `.claude.json` and `history.db` after the turn. The container was paused, resumed explicitly, and turn 2 asked without tools what the previous turn did.

**Result:** Turn 1 COMPLETED with content `hello`. Turn 2 COMPLETED with "I created `/workspace/hello.py`, which printed `hello`." and the same Claude session id `a4dd9994-...` on the local session row, so the native session resumed rather than restarting. Two live model calls. The container was destroyed at the end; no credential left the host except into that container's environment.

---

### create no longer resumes a paused generation

**Status:** PASS

**Description:** Reviewed the restore sequence in the checkpoint transfer and the coordinator's provisioning order: a container is bound to the session lease only after restore completes, so a restore that died halfway leaves an unbound paused container. A `create` that revived any paused container would hand such a container back as healthy. `create` now raises "paused; resume it or destroy it" and `resume` is the only way back to running. Reproduced the hazard on a real container before the change: paused, half-copied, then `create` returned it running with incomplete roots.

**Result:** Unit and real Docker cases updated for the explicit resume; both Claude cookbooks and the warm-reuse cookbook call `resume`. 100 sandbox unit tests and 7 real Docker provider cases passed after the change; the warm-reuse cookbook passed with the refused `create` printed. The warm Claude cookbook was re-run live and passed with the explicit resume (same native session id across turns); the cold Claude cookbook does not pause and was re-linted only.

---

### Runtime served over HTTP, long-poll, and the transport load comparison

**Status:** PASS

**Description:** The runtime gains a `serve` operation, a stdlib threaded HTTP server run as the container entrypoint with `POST /start`, `POST /poll` and `GET /health` over the same JSON and journal, plus a `wait` long-poll on both transports. `DockerSandbox(runtime_port=...)` publishes the port on the host loopback, waits for `/health` on create, and routes `rpc` over a pooled `httpx` client with no daemon call per request; without a port, `rpc` falls back to spawning the runtime over exec. `SandboxHandle` carries `runtime_url`. The client goes through `rpc` and long-polls by default (10 s, cap 30 s). Two fixes found while measuring: the stdlib server's reverse DNS lookup on bind stalled five seconds per server (skipped), and headers and body written as two segments hit the delayed-ACK stall (TCP_NODELAY set).

**Result:** 110 sandbox unit tests passed in 3 s, including an in-process runtime server (health, idempotent start, conflict, long-poll returning on journal growth, malformed and oversized requests), stdin long-poll, the Docker HTTP path over a mock transport (publish args, serve entrypoint, label, readiness, failures leaving compute alone, zero daemon calls per request, exec fallback) and configuration validation. Runtime integration cases run over both transports: 15 passed, 1 skipped (exec-only skip of the long-poll case). Docker provider cases: 7 passed. `runtime_journal.py`, `warm_reuse.py` and the live `claude_runtime.py` over HTTP passed. `runtime_transport_load.py` with 8 concurrent 3 s fixture turns on Docker Desktop for Mac:

| transport | requests/turn | daemon calls/turn | idle poll p50 |
|---|---|---|---|
| exec, poll loop (previous behaviour) | 9.0 | 18.0 | 151 ms |
| exec, long-poll | 2.0 | 4.0 | 138 ms |
| http, long-poll | 2.0 | 0.0 | 1.7 ms |

No model calls in the load run. Requests and daemon calls per turn are what scale with concurrent users; at 1,000 concurrent turns the poll loop would put thousands of exec spawns per second through one dockerd, while HTTP keeps the daemon off the hot path entirely.

---

### Runtime server token and advertised host

**Status:** PASS

**Description:** The HTTP transport assumed the daemon and the replica share a machine: the port was published and advertised on `127.0.0.1`, so a replica on another host sharing a remote daemon would never reach it and `create` would fail waiting for health. `DockerSandbox` gains `runtime_host` (published on and advertised as that address, part of the config digest) and every container a per-container bearer token: generated at create, passed through the private env file, read back from the container environment onto `SandboxHandle.runtime_token` (kept out of repr), sent on every request including the readiness check, and required by the server for every path. A user env entry with the token name is refused.

**Result:** Unit cases cover token generation and read-back, requests carrying the header and a stale token refused, the server returning 401 without or with a wrong token and 200 with the right one, `runtime_host` publishing and advertising the daemon host's address, validation of bad hosts, and the three configurations yielding distinct digests. Integration: an anonymous request to a live container's server is refused with 401 and the owner's request answers 200; all runtime cases pass over both transports. No change to the load numbers.

---


### Token scope, server supervisor, and the no-stop exec fallback

**Status:** PASS

**Description:** Three updates from the review of #11034. The control token used to sit in the container environment, where every worker and therefore every tool the agent runs inherited it; the server now reads it once and removes it from its own environment, and workers are spawned without it. The HTTP server used to be the container's main process, so a server crash would have stopped the container mid-turn; the main process is now `python -m agno.sandbox.runtime supervise`, which runs the server as a child, restarts it with backoff, and stops on `SIGTERM` while workers run detached. The exec fallback for `rpc` used to go through plain `aexec`, which stops the container on a timed-out or lost reply; it now runs the fixed runtime argv through the shared executor with stopping disabled, so a lost control reply leaves compute alone on both transports, while arbitrary `exec` keeps the stop rule. README documents the token's real scope (same-UID caveat, separate UID as follow-up), the supervisor, the fallback rule, and that `runtime_port`/`runtime_host` are in the config digest, so flipping a default is a migration.

**Result:** Unit: the worker is spawned with an env lacking the token and keeping everything else; `_take_token` returns the token, removes it, and warns when absent; the supervisor restarts a crashed child once with a 0.4 s backoff and terminates the running child on `SIGTERM`; the Docker entrypoint is `supervise`; the fallback passes `stop_on_failure=False`; a timeout or `SandboxError` on an exec-path `rpc` never calls `stop`, while the same failure on `exec` does. 118 sandbox unit tests pass. Integration against the rebuilt `agno-sandbox:local`: the fixture writes the `AGNO_SANDBOX*` names it sees into the workspace and the token is absent on both transports; killing the server process mid-turn with `SIGKILL` leaves the turn running, the supervisor brings the server back, and the turn finishes exactly once (HTTP transport; skipped on exec). 19 passed, 3 skipped.

---

### runtime_resilience.py

**Status:** PASS

**Description:** Live demonstration of the three boundaries above on `agno-sandbox:local`, printing each event with its cursor and elapsed time. A fixture turn reports the `AGNO_SANDBOX*` variables it can see; a turn streaming eight events over four seconds (the fixture now takes a `steps` option) has the runtime server killed with `SIGKILL` after its second event; a control request on the exec transport is forced to time out. Failure messages that used to end in an empty string now name the cause (`Server disconnected`, `ConnectError`, `timed out`).

**Result:** The turn saw `AGNO_SANDBOX_TEST_RUNTIME` only, no token. After the kill, four polls failed over about 0.4 s while the supervisor restarted the server, then events 3 through 8 arrived from cursor 270 onward; all eight arrived exactly once and the effects file lists each run once. The timed-out control request raised `SandboxError`, the container stayed `running`, and the same turn then streamed its event and finished.

---

### Isolated network per namespace

**Status:** PASS

**Description:** `network="isolated"` makes the provider create and own one bridge per namespace, `agno-<namespace>`, with `com.docker.network.bridge.enable_icc=false`, labelled with the namespace. Containers join it; `destroy` leaves it; `remove_network` deletes it; a same-named network without the label is refused; a creation race resolves on the name. The harness cookbooks and the HTTP-transport live fixture moved from Docker's default `bridge` to it. README documents the host-services and address-pool caveats.

**Result:** Unit: network created once per namespace and joined by the container, kept on destroy, creation race treated as success, foreign network refused for create and remove, remove touches only the namespace bridge, `isolated` and `bridge` yield distinct digests, unsafe namespaces hash the network name. 122 sandbox unit tests pass. Integration on `agno-sandbox:local`: all runtime cases pass over HTTP on the isolated network; two sandboxes in one namespace cannot open each other's runtime port on `isolated` while the same connection succeeds on `bridge`, and the host still reaches both through loopback. 21 passed, 3 skipped. `runtime_resilience.py` runs end to end on the isolated network and removes it.

---

### Token exposure inside the container, re-measured

**Status:** PASS

**Description:** Review of #11040 pointed out that popping the token in the server and withholding it from workers still left it readable: `docker exec` inherits the container environment, the supervisor and PID 1 keep it, and `/proc/<pid>/environ` shows a process's exec-time environment regardless of later `os.environ` changes. Measured live before the change: present in a host-run shell, in PID 1, in the supervisor, and in the serving process's environ. Changes: the supervisor pops the token and hands it to the server on stdin with `--token-stdin`, spawning it with an environment that lacks the variable; every `docker exec` from the host passes `--env AGNO_SANDBOX_RUNTIME_TOKEN=` so host-run commands see it blank. README now states exactly where the token remains: PID 1 and the supervisor's exec-time environment, same-UID readable, closed only by a separate UID for the server.

**Result:** Measured after the change, per process in a served container: PID 1 token, supervisor token, server clean, host-run shell sees the variable empty. Unit: the server reads the token from stdin; the supervisor spawns the server with the token on stdin and not in its env and drops its own copy; `exec` blanks the variable only when a server is configured. Integration on the rebuilt image: a host-run shell sees the variable absent, the serving process's environ is clean, and the token still authorises a turn. 125 unit, 22 integration passed, 4 skipped.

---

### Isolated network reworked: one per host, pinned subnet

**Status:** PASS

**Description:** Review of the per-namespace network pointed out that unpinned bridges draw from Docker's default address pools, which run out at a few dozen networks per host, and that with inter-container traffic off a shared network isolates just as well. The provider now creates one network per host, `agno-sandbox`, labelled as Agno-managed, with `--subnet` pinned to `DockerSandbox(subnet=...)`, default `172.30.0.0/22`. A subnet overlap from the daemon, a subnet different from the existing network's, and a same-named network without the label each raise a `SandboxError` naming the fix. `remove_network` returns whether it removed the network and leaves it when sandboxes are attached. A container create that fails because the network was removed behind the provider recreates it and retries once. Cookbooks no longer remove the network, since it is host infrastructure shared with anything else running sandboxes.

**Result:** Unit: one network created and shared by two namespaces with the subnet, ICC option and label on the create call and no namespace label; creation race resolved on the name; foreign network refused for create and remove; subnet mismatch and overlap raise clear errors; a network removed behind the provider is recreated with one retry; removal returns False when in use or absent and True when removed; subnet validation rejects non-CIDR, host bits set, IPv6 and smaller than /30. 127 sandbox unit tests pass. Live on this host, which already has twelve default-pool networks: a subnet inside docker0's range is refused with the overlap message; two namespaces attach to the one `agno-sandbox` network at `172.30.0.0/22` with ICC off; removal while in use returns False; a provider configured for `10.77.0.0/22` is refused with the mismatch message; removal when empty returns True and leaves nothing. Integration: 22 passed, 4 skipped, with sandbox addresses asserted to come from the pinned subnet and the sandbox-to-sandbox block still holding.

---

### runtime_journal.py and runtime protocol acceptance

**Status:** PASS

**Description:** 19 new runtime/client tests cover duplicate dispatch, one-writer locking, event replay, dead-worker uncertainty, incomplete frames, execution timeout, protocol/identity validation, sync/async clients, poll cancellation and a final-event/completion race. All 64 sandbox unit tests passed on Python 3.12 and Python 3.9. Real Docker: 11 combined provider/runtime cases plus one SDK-construction case passed; the reconnect cookbook passed. The construction check instantiates both adapters without authenticating or calling models.

**Result:** Runtime image `sha256:616c3e78f2e95c6e81eda400222ec142ebfffa2383412fcede3a97f966b42317`, Claude SDK 0.2.165, Codex SDK 0.162.1, SQLAlchemy 2.0.52. Required scripts passed in the established validation environment. The initial image build hit an HTTP Debian mirror checksum mismatch; switching the official mirror to HTTPS resolved it with verification retained. The initial SDK-construction assertion inspected a nullable configuration field instead of the engine; corrected the assertion and reran successfully. No live model calls, hosted provider calls or full AgentOS sandbox durability acceptance.

---

### replace_computer.py and checkpoint transfer

**Status:** PASS

**Description:** The cookbook clones a local Git fixture, edits code, runs tests, captures ignored/untracked files and native-state fixtures, destroys compute, restores generation 2, reruns tests, and retrieves an artifact after all compute is gone. 71 sandbox unit tests passed on Python 3.12 and 3.9. The combined 16 real Docker tests cover provider/runtime behavior plus replacement recovery, failure cleanup, stopping a partial restore and a 40 MiB archive beyond the command-output limit.

**Result:** Both required scripts and the cookbook passed. Two real probes established that ordinary container tmpfs produces an empty successful daemon copy, while Docker-managed bounded tmpfs volumes preserve data. The provider now uses the latter and the transport rejects the former. A first restore failed against the read-only container root; restore now targets the writable volumes directly. A synthetic tar fixture initially gave directories non-traversable permissions; corrected the fixture. No live SDK conversation, paid provider, host-loss shared-storage deployment or atomic AgentOS terminal commit was certified.

---

### runtime control transport recovery

**Status:** PASS

**Description:** Runtime start/poll now use a restricted provider RPC operation. A lost control response leaves the session computer available to its current coordinator; arbitrary shell commands retain stop-on-failure behavior. A real-container regression discards a poll response, reconnects through another client and verifies exactly one fixture effect.

**Result:** 74 sandbox unit tests passed on Python 3.12 and 3.9; all 17 real Docker provider/runtime/transfer cases passed. Required scripts passed. This fixes an integration risk where a stale polling request could stop compute during another coordinator's checkpoint. No live model or hosted-provider calls.

---

### warm_reuse.py and pause/resume regressions

**Status:** PASS

**Description:** `pause`/`resume` added to the provider contract and `DockerSandbox`; `create` refuses a paused generation so only its owner resumes it. Four unit cases cover pause then create refused and resume returning the same container, resume only from paused, stop and destroy still taking the cold path from paused, and the not-implemented default for providers without a native pause. One real Docker case writes a file, pauses, confirms exec and create are refused while paused, resumes with the file intact, then stops from paused and confirms the generation cannot restart. The cookbook adds a background counter to show the frozen process continuing after resume.

**Result:** 100 sandbox unit tests passed on Python 3.12; 7 real Docker provider cases and 7 real runtime cases passed with `python:3.12-slim` and the rebuilt runtime image. The cookbook passed: counter advanced from 6 to 11 across pause and resume, exec while paused refused with the provider's message, create after stop refused, generation 2 started empty. Docker daemon probe confirmed `stop` succeeds on a paused container. No model calls. The coordinator still destroys after every turn; wiring the warm path there is tracked separately.

---

### claude_runtime.py: live two-turn Claude session with a pause

**Status:** PASS

**Description:** Container from `agno-sandbox:local` on `bridge` networking with only `CLAUDE_CODE_OAUTH_TOKEN` forwarded. Turn 1 through `SandboxRuntimeClient` with `sdk="claude"`, `claude-sonnet-4-6`, `bypassPermissions`, tools Read/Write/Bash: Claude wrote `hello.py`, ran it and answered `hello`; Write and Bash tool events and the content arrived through the poll cursor. `/runtime/native` held `.claude`, `.claude.json` and `history.db` after the turn. The container was paused, resumed explicitly, and turn 2 asked without tools what the previous turn did.

**Result:** Turn 1 COMPLETED with content `hello`. Turn 2 COMPLETED with "I created `/workspace/hello.py`, which printed `hello`." and the same Claude session id `a4dd9994-...` on the local session row, so the native session resumed rather than restarting. Two live model calls. The container was destroyed at the end; no credential left the host except into that container's environment.

---

### create no longer resumes a paused generation

**Status:** PASS

**Description:** Reviewed the restore sequence in the checkpoint transfer and the coordinator's provisioning order: a container is bound to the session lease only after restore completes, so a restore that died halfway leaves an unbound paused container. A `create` that revived any paused container would hand such a container back as healthy. `create` now raises "paused; resume it or destroy it" and `resume` is the only way back to running. Reproduced the hazard on a real container before the change: paused, half-copied, then `create` returned it running with incomplete roots.

**Result:** Unit and real Docker cases updated for the explicit resume; both Claude cookbooks and the warm-reuse cookbook call `resume`. 100 sandbox unit tests and 7 real Docker provider cases passed after the change; the warm-reuse cookbook passed with the refused `create` printed. The warm Claude cookbook was re-run live and passed with the explicit resume (same native session id across turns); the cold Claude cookbook does not pause and was re-linted only.

---


### Strict native recovery and local persistence

**Status:** PASS

**Description:** Missing Claude/Codex native state fails without starting another conversation; new sessions still start normally. Failed local writes cannot emit terminal success. Runtime readback checks include a real SQLite round trip, with empty-event normalization handled by the RunOutput serializer.

**Result:** 575 combined external-agent/sandbox unit cases passed on Python 3.12; 8 real Docker runtime cases passed with the rebuilt image, including installed SDK construction with both strict flags. No authenticated model calls. The combined suite emitted an aiosqlite background-thread teardown warning from an existing async test environment; the focused runtime tests passed without it. Required scripts passed.

---

### native_recovery.py and the expectation check

**Status:** PASS

**Description:** The strict native recovery change ported onto the base branch, plus the missing guard: `native_session_id` on `start`, checked by the runtime against the local database before the model runs and reported as `execution_error` with reason `native_state_missing`. Without it a lost local database was indistinguishable from a new session and produced a completed turn on a fresh conversation, measured live earlier with both SDKs.

**Result:** Unit: agent and sandbox suites 795 passed, including the expectation matrix (match runs, null runs, missing or different native id refused without a model call), the worker's reason field, and request validation. Live on the branch image with real Claude: continuity with the expectation set; a wrong expectation refused in 0.4 s; the database deleted then refused in 0.4 s with the committed id; a fresh turn without an expectation allowed; a read-only database refused before the model. Real Codex: thread files deleted with the database kept ends the run with status ERROR and the stored thread id intact; the database deleted with the committed id is refused with `native_state_missing`. `native_recovery.py` walks five generations of one session: checkpoint and destroy, a restore that lands and recalls the word, a skipped restore answering NONE as COMPLETED without an expectation, the same skipped restore refused with `native_state_missing` when the committed id is passed, and the retry that restores the same checkpoint into a fresh generation and recalls the word again. 21 s end to end with real Claude.

---

### agentcore_session.py

**Status:** PASS (fixture, codex, claude)

**Description:** `AgentCoreSandbox` against a runtime deployed by `agentcore_setup.py` in the staging AWS account, us-east-1. Two turns on one generation. Turn 2 looks the sandbox up again with `create` and must get the same microVM. With Codex, turn 1 is told the codeword BLUE-HERON and told not to write it to any file; turn 2 is asked for it.

**Result:** On 14 October 2026 the fixture run completed both turns on the same microVM and left `fixture-effects.txt` and `fixture-env.txt` in the workspace. The Codex run completed both turns: turn 2 answered "The codeword was `BLUE-HERON`" and added `test_primes.py`, whose two tests passed against the `primes.py` from turn 1. Live runs on an earlier version found that Codex fails without `CODEX_HOME` and ignores `OPENAI_API_KEY` without a stored login; the runtime now creates the directory and logs in. The Claude run used Bedrock through the runtime's execution role with no API key, model `us.anthropic.claude-sonnet-5`. It first failed with an AWS Marketplace subscription error until the account's Anthropic use case form was submitted. After that both turns completed: turn 2 answered "The codeword is BLUE-HERON" and added `test_primes.py`, whose five tests passed.

Local container checks of `agentcore_server`: the guard refuses commands before a claim with exit code 125, a second claim with different identity is refused, start and a long poll reach the runtime server, the long poll returned when the 2 second fixture finished, commands run as UID 1000 in `/workspace` with staged stdin and `HOME=/runtime`, the staged input is deleted, and the agent cannot read the claim.

---

### Review fixes: restore race and one fewer call per command

**Status:** PASS

**Description:** Two findings from reviewing the whole PR. A restore set its importing flag after releasing the lifecycle lock. A repeated create arriving in that gap took the restoring marker for an interrupted restore and marked the computer failed. The restore then completed, but every later turn was refused. The flag is now set under the same lock. Separately, `aexec` looked the computer up with `describe` before staging its input. Staging already names the handle's incarnation and the server refuses a mismatch, so that lookup cost one invocation per command for nothing. It is gone.

**Result:** 307 sandbox unit tests pass. A new test runs a repeated claim at the moment the import releases the lock, and fails when the flag is set after the lock again. Twenty-one mutations that invert the provider's and server's safety checks all fail at least one test. On staging the hardening checks passed, and `agentcore_session.py --replace` recalled the codeword with Codex and Claude and passed with the fixture harness.

---

### One package per provider

**Status:** PASS

**Description:** Kaustubh asked to separate the protocols from their implementations. `transfer.py` now holds only the `CheckpointTransfer` protocol and `DEFAULT_NATIVE_EXCLUSIONS`. Docker moved to `agno.sandbox.docker` with `sandbox.py` and `transfer.py`. AgentCore moved to `agno.sandbox.agentcore` with `sandbox.py`, `transfer.py` and `server.py`. Imports from the packages are unchanged except `DockerCheckpointTransfer`, which now comes from `agno.sandbox.docker`. The image entrypoint is now `python -I -m agno.sandbox.agentcore.server serve`. The AgentCore package loads its classes on first use, so starting the server does not import the provider and does not trigger the double-import warning from `-m`.

**Result:** 306 sandbox unit tests pass, including a new test that runs the server with `-W error` and checks that importing the package leaves the provider unloaded. The Docker integration suite passed on the rebuilt image, with 34 passed and 5 skipped for the other transport. On staging the hardening checks passed, and `agentcore_session.py --replace` recalled the codeword with Codex and Claude and passed with the fixture harness.

---

### AgentCore deploy flags and one image

**Status:** PASS

**Description:** Review requests from Kaustubh. `agentcore_setup.py` takes `--repository`, `--role-arn` and `--skip-build`, so an account without permission to create ECR repositories or IAM roles can deploy into ones an administrator made. `Dockerfile.agentcore` is gone: the one `Dockerfile` has the AgentCore server as its entrypoint, and `DockerSandbox` overrides the user, entrypoint and working directory at create. Docstrings and the README now cover the cost of `get` on an ended session, the lifetime deadline, and the failed polls during an export.

**Result:** 305 sandbox unit tests pass. The image built from the one Dockerfile passed the Docker integration suite: 34 passed, and the 5 skipped cases target the other transport. On staging, a deploy with `--repository` and `--role-arn` built and pushed that image into the existing repository and created no IAM role. A second deploy of the same tag with `--skip-build` updated the runtime without building, and `--skip-build` without `--tag` is refused. On that image the hardening checks passed and `agentcore_session.py --replace` recalled the codeword with Codex and Claude, and the fixture harness passed.

---

### AgentCore adversarial review fixes

**Status:** PASS

**Description:** Three review cycles over the whole provider, the third with Codex as a second model. Fixes from the last cycle:
- A handle that reaches an unclaimed replacement microVM retires it, so a racing create cannot claim it. A handle that arrives during a first claim gets "busy" instead.
- A repeated create no longer waits on the server lock. It skips the runtime health check during a capture or restore, and restarts the runtime only after three misses.
- Transfer children are killed after 840 seconds. Export and import use the long-timeout client.
- The freeze leaves processes the agent stopped itself alone.
- `_remove` works on a failed computer.
- Runtime replies are never followed through a redirect or a proxy, and are read only up to 4 MiB.
- A stale handle that fails `arestore` no longer stops the computer that now holds the session.
- The provider refuses checkpoint limits above 2 GiB.
- Codex logs in only when no stored login matches the key.

**Result:** After rebasing onto #10975 with #11053, 305 sandbox unit tests pass with this branch on `PYTHONPATH`. After redeploying the staging runtime, the live checks passed. The agent gets `Forbidden` on port 8080 and cannot read the control directory. 8 MiB of stdin arrived intact. A 150-second command finished and the computer stayed claimed. `agentcore_session.py --replace` recalled the codeword on a restored microVM with Codex and Claude, and the fixture harness passed.

---

### AgentCore review fixes: stdin limit, staging failures, claim ordering

**Status:** PASS

**Description:** Three edge cases found in review. Stdin up to the documented 8 MiB was base64 encoded into the runner request and then hex encoded for staging, so anything over about 6 MiB passed the client check, was refused by the server, and stopped the computer. A failed staging upload stopped compute although nothing had run. A claim wrote `claim.json` before the runtime server was healthy, so after a failed start a retry matched the claim and reported success with no runtime.

**Result:** The client and server now share one 12 MiB staged request limit, staging uses base64, and the client refuses oversized argv or stdin before sending anything. Only the command step stops compute. The claim file is written after the runtime answers its health check; a failed start kills the supervisor's process group and leaves the computer unclaimed, and a repeated claim restarts an unhealthy runtime. Five new unit tests cover these, and 266 sandbox unit tests pass. Live on the staging runtime: an 8 MiB stdin reached `sha256sum` intact, a 12 MiB argv was refused before sending and the computer kept running, a repeated create returned the same computer, and the fixture session with `--replace` passed.

---

### agentcore_session.py --replace

**Status:** PASS (fixture, codex, claude)

**Description:** The cold path on AgentCore in the staging account after rebasing onto #10979. Turn 1 runs on generation 1; `AgentCoreCheckpointTransfer` captures it to a `FileCheckpointStore`; the microVM is destroyed; generation 2 is created on a fresh microVM and restored; turn 2 runs there. Real harnesses must recall a codeword from turn 1 that was never written to a file.

**Result:** On 14 October 2026 all three passed. Fixture: 458 byte checkpoint, both turns completed. Codex: 375,193 byte checkpoint with the plugin cache excluded; turn 2 on the restored microVM answered "The codeword was `BLUE-HERON`" and added a passing `test_primes.py` next to the restored `primes.py`. Claude through Bedrock: 62,007 byte checkpoint; turn 2 answered "The codeword you asked me to remember is BLUE-HERON" and its five new tests passed.

Unit: a round trip through the real server operations on temporary directories, with 1,000 byte chunks, restores files and a relative symlink, leaves `auth.json` and the Codex `.tmp` cache behind, and leaves no transfer objects; restoring into a used computer is refused and stops it. 261 sandbox unit tests pass, including the 14 Docker transfer tests after the shared host-side code moved into a base class.

---

### agentcore_load.py

**Status:** PASS with documented throttling

**Description:** Concurrent sessions against the staging runtime. Each session is created, runs a 5 second fixture turn, runs one command and is destroyed, all at once.

**Result:** On 14 October 2026:

| Sessions | Completed | Create p50 / p90 | Turn p50 | Command p50 | Destroy p50 | Total time |
|---|---|---|---|---|---|---|
| 20 | 20 | 4.3 s / 14.4 s | 5.35 s | 0.95 s | 0.24 s | 21 s |
| 100 | 98 | 18.7 s / 19.6 s | 5.41 s | 0.95 s | 0.24 s | 27 s |
| 250, no throttling retry | 235 | 24.9 s / 26.9 s | 5.39 s | 0.89 s | 0.22 s | 34 s |
| 250, throttling retried | 249 | 26.3 s / 28.2 s | 5.40 s | 0.87 s | 0.21 s | 44 s |
| 500, 8 attempts | 499 | 37.1 s / 38.5 s | 5.40 s | 0.87 s | 0.21 s | 59 s |
| 500, 10 attempts | 497 | 39.2 s / 41.1 s | 5.40 s | 0.87 s | 0.21 s | 70 s |

Only creation slows with load: 500 sessions came up at about 13 per second, under the default quota of 25 new sessions per second. Turns, commands and destroys stayed flat at every size. The first runs failed creates with `ThrottlingException` and one poll and one stop with HTTP 502. The provider now retries throttling for every call with jittered backoff, and retries server errors for invocations and stops, which are idempotent; it never retries a command after a server error. The remaining failures at 500 are creates that stayed throttled for all attempts, so bursts above a few hundred need paced creates or a quota increase. The 100-session run also had one client-side TLS error from opening about a hundred connections at once from one laptop.

Paced at 20 creates per second with two-minute turns: 1,000 of 1,000 sessions completed with all 1,000 alive at once (create p50 32.7 s, turn p50 120.5 s, command p50 0.88 s, destroy p50 0.22 s). At 2,000, all sessions were created and alive at once, then from about two minutes in most calls failed with HTTP 403. The response came from `server: awselb/2.0` with an HTML body and no AWS request ID, and AgentCore's own metrics recorded no errors, so a load balancer in front of the service rejected traffic from the one client IP. A second 2,000 run reproduced it. The 1,782 and 1,818 sessions left undestroyed ended on their own about 15 minutes after their claims, as `ActiveSessionCount` showed.

---

### AgentCore sandbox contract tests

**Status:** PASS

**Description:** `libs/agno/tests/unit/sandbox/test_agentcore.py`: 11 tests against a fake data plane covering constructor validation, deterministic and idempotent create, refusal of changed configuration, no return of a stopped generation, release of unclaimed replacement compute, staged stdin through the guard, stop on guard refusal and uncertain commands, RPC failures that leave compute alone, retry of rejections that AgentCore returns before running anything, retry of server errors for idempotent invocations only, no retry of a command after a server error, and unsupported pause.

**Result:** 235 sandbox unit tests pass with this branch on `PYTHONPATH`. Without it, `test_sandbox_import_does_not_load_agent_runtime` starts a fresh interpreter that imports agno from another checkout.

---

### session_computer.py

**Status:** PASS

**Description:** Three runs on one session through the public coordinator API, real Docker and local Postgres 18, fixture runtime. After each turn the example reads back, with public calls only, the run row (`db.get_run`), the session (`db.get_session`) and the checkpoint opened from the checkpoint store.

**Result:** Passed. Turn 1 ran on generation N with a checkpoint whose workspace held turn 1; turn 2 ran on generation N+1, restored it, passed the native conversation check, and its checkpoint held turns 1 and 2. Retrying turn 2 returned the stored result, and the session still pointed at the same checkpoint. Store and coordinator integration suites: 96 passed, 2 skipped (cancellation tests that apply to PostgresDb only). These runs used a local-only workaround for Docker 27.4, where restoring with `docker cp --archive` fails with `getent unable to find entry "1000:1000"` (as does `feat/sandbox`'s own `test_transfer.py`): a passwd entry for uid 1000 in the image and a numeric `--user`. It is not part of the change.
---

### resume_after_disconnect.py

**Status:** PASS

**Description:** A ten-second fixture turn whose caller task is cancelled after five seconds, then a second coordinator asks for the same run id and input. The example opens the committed checkpoint and counts the run id in the workspace, which the fixture appends once per execution.

**Result:** Passed: the second coordinator returned COMPLETED after 11.0s, and the committed workspace recorded the turn once, so its work ran once across both coordinators. An earlier version with a six-second turn and a three-second disconnect judged reattachment by elapsed time; that was unreliable, because a disconnect during container setup lets the second coordinator start the turn itself. Same Docker workaround as above.
---

### cancel_turn.py

**Status:** PASS

**Description:** Turn 1 completes; turn 2 (six seconds) is cancelled after three seconds with `acancel_run`; turn 3 runs on the same session. Same environment and Docker workaround as above.

**Result:** Passed: turn 2 ended CANCELLED and turn 3 completed from turn 1's checkpoint, passing the native conversation check against turn 1's id. The coordinator does not register runs with the cancellation manager, so the cancel logs "not yet registered, storing cancellation intent"; the stored intent is honored.

---

Coordinator review follow-up: native transcript-mirror warnings and lost pre-checkpoint compute cannot publish success or trigger model execution retries. Tool audit history is retained on failure. Runtime output cannot replace the original submitted input or trusted service metadata. Added 2 real mirror-warning cases and 2 metadata/input boundary cases; final store suite: 32 passed. Focused finalization/mirror cases: 4 passed. Required scripts passed again.

### agentos.py and durable API integration

**Status:** PASS

**Description:** `ClaudeAgent`/`CodexAgent(sandbox=DockerSandbox(...))` served by AgentOS with a durable Postgres queue and Redis, using the credential-free `FixtureAgent`. The agent builds its coordinator from the AgentOS `db`; no store, coordinator or setup call appears in the cookbook. Ran the cookbook server and sent a foreground turn (COMPLETED, checkpoint recorded) then a streamed second turn on the same session (RunContent, RunCompleted after restoring the first turn's checkpoint).

**Result:** `test_agentos.py` 12 passed (foreground, background, streaming, idempotency, same-session admission, retained replay, finalization-only retry, active and between-attempt cancellation, retry exhaustion, SDK background, missing queue, detached SDK cancel). `test_coordinator.py` 32 passed and `test_postgres.py` 55 passed, 1 skipped, both adapters. Docker 27.4 needed the same local-only workaround as the coordinator PR (passwd entry for uid 1000 in the image, numeric `--user`), not committed. No model calls.

---

### sandbox_claude.py

**Status:** PASS

**Description:** The smallest sandboxed agent: a ClaudeAgent with PostgresDb and sandbox=DockerSandbox(image), two turns on a new session, no AgentOS. Real Docker, local Postgres, claude-sonnet-4-6 authenticated with CLAUDE_CODE_OAUTH_TOKEN forwarded from the process environment.

**Result:** Passed. Turn 1 wrote and ran hello.py and replied "hello"; turn 2, on a fresh container restored from turn 1's checkpoint, named the file. Both runs COMPLETED. print_response on the same agent also renders both turns and their status line.

---

### sandbox_claude_agentos.py

**Status:** PASS

**Description:** The same agent served through AgentOS with a durable queue (Postgres and Redis) and an explicit checkpoint store, driven over HTTP: a background submission polled to completion, then a streamed second turn on the same session.

**Result:** Passed. The background turn COMPLETED with a checkpoint on the run row; the streamed turn returned four events ending in RunCompleted with the file name from turn 1; no containers were left running and the server log had no errors.

---

### sandbox_claude_agentcore.py

**Status:** PASS

**Description:** The `sandbox_claude.py` agent with `sandbox=AgentCoreSandbox(runtime_arn, env={"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": ...})` on the staging runtime, local Postgres, `us.anthropic.claude-sonnet-5` through the runtime's execution role, and no API key in the process environment. Two turns on a new session, each on a new generation: the coordinator looks the generation up with `afind`, creates it, restores the last checkpoint, runs the turn, captures and stops the microVM.

**Result:** Passed in 40.7 s for both turns. Turn 1 wrote and ran hello.py and replied "hello"; turn 2, on a fresh microVM restored from turn 1's checkpoint, replied "hello.py". Both runs COMPLETED. 353 sandbox unit tests pass, including `afind` against a fresh, a claimed, a stopped and a retired microVM, and `peek` against the real server code.

---

### sandbox_claude_agentcore_agentos.py

**Status:** PASS

**Description:** The AgentCore agent served by AgentOS with a durable queue (local Postgres and Redis) and an explicit checkpoint store, driven over HTTP against the staging runtime with `us.anthropic.claude-sonnet-5` through Bedrock and no API key. Turn 1 was a streamed submission; turn 2 a background submission with `stream=false`, polled to completion.

**Result:** Passed. Turn 1 streamed RunStarted, two tool calls, content and RunCompleted with "hello". Turn 2 ran on a new microVM restored from turn 1's checkpoint, COMPLETED, and replied "hello.py". The server log had no errors or warnings.

---

### agentcore_session.py --resume and session storage regressions

**Status:** PASS

**Description:** Warm resume from AgentCore session storage. A spike on a throwaway staging runtime first found that the session storage mount enforces no permissions (UID 1000 read a root 0600 file, rewrote a root-only claim, renamed a root 0700 directory and chowned files to root), that every file on it appears owned by root, that SQLite fails there with "database is locked" and `lockf` with ENOLCK, that it survives a stop and is emptied by a runtime update, and that AgentCore sets `NoNewPrivs` on the container and every command, so a setuid file on it gives nothing. The design follows from that: the managed roots stay on local disk, each capture keeps a copy of its archive on the mount through a UID 1000 child, and `AgentCoreCheckpointTransfer.aresume` claims a replacement microVM with a fresh incarnation and imports the copy only when its SHA-256 and size match the reference. 12 new unit cases cover the kept copy, a resume, a tampered, deleted, linked or stale copy, a resume reaching a still-running generation, a retired replacement, a runtime that never starts, no session storage, a copy that cannot be written, and the original configuration. Breaking each new check in turn failed at least one test, except the early size check, which only short-cuts the hash check.

**Result:** 319 sandbox unit tests pass. Live on a staging runtime deployed with `agentcore_setup.py deploy --session-storage`: the fixture session resumed and was ready for turn 2 in 1.1 s; Claude on Bedrock recalled the codeword after a resume, ready in 1.3 s, against 2.1 s for `--replace` with a 60 KB checkpoint; with a 200 MB file in the workspace, resume was ready in 2.8 s and cold restore in 37.9 s, and the file came back whole both ways. The runtime and its image tag were deleted afterwards.

---
