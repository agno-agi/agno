# Amazon Bedrock AgentCore Runtime

`AgentCoreSandbox` runs each turn in an AgentCore microVM instead of a local container. The agent, the queue and the database stay wherever AgentOS runs; only the turns move to AWS. The same runtime image serves both providers.

## Getting started

These steps create AWS resources and billable compute. You need an AWS profile that can create ECR repositories, IAM roles and AgentCore runtimes, in a region where AgentCore and the Claude models on Bedrock are available.

1. Install the extra and sign in:

   ```bash
   pip install "agno[agentcore-sandbox]"
   export AWS_PROFILE=... AWS_REGION=us-east-1
   ```

2. Deploy the runtime once. The script builds the ARM64 image from this folder's parent `Dockerfile`, pushes it to ECR, creates an execution role that may pull the image and call Claude models on Bedrock, creates a runtime with public egress and no session storage, and prints the runtime ARN together with the runtime's `maxLifetime`, which `AgentCoreSandbox(lifetime=...)` must not exceed:

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_setup.py deploy --name agno-sandbox
   export AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:...:runtime/agno_sandbox-...
   ```

   Without permission to create the repository or the role, have an administrator create them with the trust and policy from `create_role` in the script, and pass `--repository` and `--role-arn`; add `--skip-build` with `--tag` to deploy an image already pushed.

3. Smoke test without a model, then with one:

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_session.py                  # fixture, no model calls
   .venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_session.py --harness claude # Bedrock via the execution role
   ```

4. Swap the provider on your agent. Nothing else about the agent changes. Claude authenticates to Bedrock through the runtime's execution role, so no Anthropic key enters the microVM; Codex still needs `OPENAI_API_KEY` in `env`:

   ```python
   from agno.sandbox.agentcore import AgentCoreSandbox
   from agno.sandbox.checkpoint import FileCheckpointStore

   sandbox = AgentCoreSandbox(
       os.environ["AGENTCORE_RUNTIME_ARN"],
       env={"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1"},
       checkpoints=FileCheckpointStore(shared_path),
   )
   agent = ClaudeAgent(id="coder", db=db, sandbox=sandbox)
   ```

   `sandbox_claude_agentcore.py` is this agent run directly, two turns on a new session.

5. Serve it through AgentOS with a durable queue. Run Postgres and Redis, then `sandbox_claude_agentcore_agentos.py`; it submits every API request to the queue, so a dropped connection does not cancel a turn. Point `checkpoints=` at storage every replica can read, such as `S3CheckpointStore` (set `AGNO_SANDBOX_CHECKPOINT_BUCKET`): with a queue, any replica may run the next attempt, and AgentOS refuses the host-local default at startup. Give each AgentOS deployment that shares a database its own job table or deployment id, or their workers claim each other's jobs for agents with the same id.

6. Tear down when you are done, since the runtime is billable:

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_setup.py teardown --name agno-sandbox
   ```

What to expect: each session is a Firecracker microVM with 2 vCPU and 8 GiB. The first turn boots one and later turns resume it while it is warm; a turn after the warm window, or after a cancel or failure, boots a fresh microVM restored from the checkpoint, a cold start of several seconds. `warm_turns.py --provider agentcore` in the parent folder shows both paths with timings. The runtime's network mode is public egress; invocations are still authenticated by IAM, so scope the calling credentials. Code inside the sandbox can use the runtime's execution role, which is why the setup script limits it to Claude models. Checkpoints move in 8 MiB chunks through invocations, so very large workspaces are slow to capture and restore.

## Cookbooks

`sandbox_claude_agentcore.py` is the same agent with `sandbox=AgentCoreSandbox(runtime_arn, env=...)`, so each turn runs in an AgentCore microVM instead of a local container. Claude reaches Bedrock through the runtime's execution role: the sandbox's `env` sets `CLAUDE_CODE_USE_BEDROCK` and `AWS_REGION`. With that flag set, the harness does not forward `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` from the host, so no API key goes into the microVM. Deploy the runtime with `agentcore_setup.py` and set `AGENTCORE_RUNTIME_ARN` first.

`sandbox_claude_agentcore_agentos.py` serves that agent through AgentOS with a durable queue, as `sandbox_claude_agentos.py` does for Docker. AgentOS, the queue and the database stay on your host; only the turns run on AgentCore.

## How the provider works

```bash
export AWS_PROFILE=staging AWS_REGION=us-east-1
.venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_setup.py deploy --name agno-sandbox
export AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:...:runtime/agno_sandbox-...
.venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_session.py                    # fixture, no model calls
.venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_session.py --harness codex    # forwards OPENAI_API_KEY
.venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_session.py --harness claude   # Bedrock via the execution role
.venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_session.py --harness codex --replace  # turn 2 on a restored microVM
.venv/bin/python cookbook/frameworks/sandbox/agentcore/agentcore_setup.py teardown --name agno-sandbox
```

These create AWS resources and billable compute. Install `agno[agentcore-sandbox]`. `agentcore_setup.py` builds the ARM64 image from the same `Dockerfile` that Docker uses, pushes it to a new ECR repository, creates an execution role that may call Claude models on Bedrock, and creates a PUBLIC runtime without session storage. It prints the runtime ARN and the runtime's `maxLifetime`; keep `AgentCoreSandbox(lifetime=...)` at or below it, or AgentCore ends the microVM first. Code in the sandbox can use the execution role, so it can call any model the role allows. Without permission to create ECR repositories or IAM roles, pass ones an administrator created with `--repository` and `--role-arn`, and add `--skip-build` with `--tag` to deploy an image already pushed. Teardown with the same flags leaves them in place.

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
| Files | On the microVM's disk. AgentCore session storage is NFS, where SQLite cannot open a database and POSIX locks fail, so it is not used. |
| Credentials | Codex logs in with `OPENAI_API_KEY` only when no stored login matches it: checkpoints exclude `auth.json`, so a restored computer logs in again, and a ChatGPT login the user set up is kept. Code in the sandbox can use the runtime's IAM role through the metadata service. Give the role only the model access the harness needs. The runtime server shares the agent's UID, so its token does not separate the two; the agent could already write the runtime journal. |
| Limits | Commands run for at most 3,500 seconds; the command client waits up to an hour and three minutes for the result, which leaves room for AgentCore's 3,600-second cap. Argv and stdin go in a staged request of at most 12 MiB once encoded. Checkpoints are limited to 2 GiB, and the provider refuses a larger `CheckpointLimits.max_bytes` when the transfer is built. Export and import wait on the same long-timeout client, since the computer allows them 14 minutes. At the claimed lifetime the computer refuses work, ends the agent's processes and exits the entrypoint. `/tmp` is not size-limited, so a runaway command can fill the microVM's own disk. |
| Bursts | The default quota is 25 new sessions per second per account. The provider retries throttled calls with jitter; `agentcore_load.py` completed 497 of 500 simultaneous sessions, so pace larger bursts or raise the quota. Set `max_connections` to the number of sessions one process serves at once. With 1,000 sessions alive at once from one host every call succeeded; at 2,000, AWS's load balancer in front of AgentCore answered most calls with an HTML 403 before they reached the service, so spread that many sessions across hosts. |

