# Test log: AgentCore cookbooks

### agentcore_session.py

**Status:** PASS (fixture, codex, claude)

**Description:** `AgentCoreSandbox` against a runtime deployed by `agentcore_setup.py` in the staging AWS account, us-east-1. Two turns on one generation. Turn 2 looks the sandbox up again with `create` and must get the same microVM. With Codex, turn 1 is told the codeword BLUE-HERON and told not to write it to any file; turn 2 is asked for it.

**Result:** On 14 October 2026 the fixture run completed both turns on the same microVM and left `fixture-effects.txt` and `fixture-env.txt` in the workspace. The Codex run completed both turns: turn 2 answered "The codeword was `BLUE-HERON`" and added `test_primes.py`, whose two tests passed against the `primes.py` from turn 1. Live runs on an earlier version found that Codex fails without `CODEX_HOME` and ignores `OPENAI_API_KEY` without a stored login; the runtime now creates the directory and logs in. The Claude run used Bedrock through the runtime's execution role with no API key, model `us.anthropic.claude-sonnet-5`. It first failed with an AWS Marketplace subscription error until the account's Anthropic use case form was submitted. After that both turns completed: turn 2 answered "The codeword is BLUE-HERON" and added `test_primes.py`, whose five tests passed.

Local container checks of `agentcore_server`: the guard refuses commands before a claim with exit code 125, a second claim with different identity is refused, start and a long poll reach the runtime server, the long poll returned when the 2 second fixture finished, commands run as UID 1000 in `/workspace` with staged stdin and `HOME=/runtime`, the staged input is deleted, and the agent cannot read the claim.

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

### sandbox_claude_agentcore.py

**Status:** PASS

**Description:** The `sandbox_claude.py` agent with `sandbox=AgentCoreSandbox(runtime_arn, env={"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": ...})` on the staging runtime, local Postgres, `us.anthropic.claude-sonnet-5` through the runtime's execution role, and no API key in the process environment. Two turns on a new session, each on a new generation: the coordinator looks the generation up with `afind`, creates it, restores the last checkpoint, runs the turn, captures and stops the microVM.

**Result:** Passed in 40.7 s for both turns. Turn 1 wrote and ran hello.py and replied "hello"; turn 2, on a fresh microVM restored from turn 1's checkpoint, replied "hello.py". Both runs COMPLETED. 353 sandbox unit tests pass, including `afind` against a fresh, a claimed, a stopped and a retired microVM, and `peek` against the real server code.

---

### sandbox_claude_agentcore_agentos.py

**Status:** PASS

**Description:** The AgentCore agent served by AgentOS with a durable queue (local Postgres and Redis) and an explicit checkpoint store, driven over HTTP against the staging runtime with `us.anthropic.claude-sonnet-5` through Bedrock and no API key. Turn 1 was a streamed submission; turn 2 a background submission with `stream=false`, polled to completion.

**Result:** Passed. Turn 1 streamed RunStarted, two tool calls, content and RunCompleted with "hello". Turn 2 ran on a new microVM restored from turn 1's checkpoint, COMPLETED, and replied "hello.py". The server log had no errors or warnings.

### warm_turns.py --provider agentcore

**Status:** PASS

**Description:** Four fixture turns of one session through the coordinator on the agno_sandbox_proto runtime in the staging account, with provider creates and transfer restores counted per turn.

**Result:** Passed: turn 1 cold 8.2s, turn 2 warm 3.3s on the same microVM with nothing restored, turn 3 warm 3.4s, turn 4 cold 6.5s on a new microVM restored from turn 3's checkpoint after the shortened warm window ended. The checkpoint held all four turns and the retire call stopped the microVM. The same two turns on the committed branch head were cold both times, 5.8s for turn 2 with a restore and a new generation. Full results for both providers are in docker/TEST_LOG.md.

---

### agentcore_session.py --resume and session storage regressions

**Status:** PASS

**Description:** Warm resume from AgentCore session storage for a microVM that has ended, which the coordinator's warm window does not cover. A spike on a throwaway staging runtime first found that the session storage mount enforces no permissions (UID 1000 read a root 0600 file, rewrote a root-only claim, renamed a root 0700 directory and chowned files to root), that every file on it appears owned by root, that SQLite fails there with "database is locked" and `lockf` with ENOLCK, that it survives a stop and is emptied by a runtime update, and that AgentCore sets `NoNewPrivs` on the container and every command, so a setuid file on it gives nothing. The design follows from that. The managed roots stay on local disk, each capture keeps a copy of its archive on the mount through a UID 1000 child, and `AgentCoreCheckpointTransfer.aresume` claims a replacement microVM with a fresh incarnation and imports the copy only when its SHA-256 and size match the reference. 12 unit cases cover the kept copy, a resume, a tampered, deleted, linked or stale copy, a resume reaching a still-running generation, a retired replacement, a runtime that never starts, no session storage, a copy that cannot be written, and the original configuration. Breaking each new check in turn failed at least one test, except the early size check, which only short-cuts the hash check.

**Result:** Ported onto the provider layout that ships with the coordinator: 559 sandbox unit tests pass, 6 skipped. The live runs below were made before the port, on a staging runtime deployed with `agentcore_setup.py deploy --session-storage`, and have not been repeated since. The fixture session resumed and was ready for turn 2 in 1.1 s. Claude on Bedrock recalled the codeword after a resume, ready in 1.3 s, against 2.1 s for `--replace` with a 60 KB checkpoint. With a 200 MB file in the workspace, resume was ready in 2.8 s and cold restore in 37.9 s, and the file came back whole both ways. The runtime and its image tag were deleted afterwards.

---
