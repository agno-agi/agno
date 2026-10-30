# E2B

`E2BSandbox` runs each turn in an E2B microVM instead of a local container. The agent, the queue and the database stay wherever AgentOS runs; only the turns move to E2B. The E2B API key stays on the host; only the env you configure, such as the model key, enters the computer.

## Getting started

These steps use E2B build minutes and billable compute. You need an E2B account and its API key.

1. Install the extra and set the key:

   ```bash
   pip install "agno[e2b-sandbox]"
   export E2B_API_KEY=...
   ```

2. Build the template once. It installs the same packages as the Docker image in `../Dockerfile` from this checkout's package sources, makes `/workspace` and `/runtime` private to E2B's `user`, and creates the root-only directory checkpoints pass through. CPU and memory are fixed here, 2 vCPU and 4 GiB by default:

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/e2b/e2b_template.py --name agno-sandbox
   ```

3. Smoke test without a model, then with one:

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/e2b/e2b_session.py                   # fixture, no model calls
   .venv/bin/python cookbook/frameworks/sandbox/e2b/e2b_session.py --harness claude  # forwards ANTHROPIC_API_KEY
   ```

4. Swap the provider on your agent. Nothing else about the agent changes; the harness forwards `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (Claude) or `OPENAI_API_KEY` (Codex) from the host:

   ```python
   from agno.sandbox.checkpoint import FileCheckpointStore
   from agno.sandbox.e2b import E2BSandbox

   sandbox = E2BSandbox("agno-sandbox", runtime_port=8765, checkpoints=FileCheckpointStore(shared_path))
   agent = ClaudeAgent(id="coder", db=db, sandbox=sandbox)
   ```

5. Serve it through AgentOS with a durable queue: run Postgres and Redis, then `sandbox_claude_e2b_agentos.py`. Point `checkpoints=` at storage every replica can read; with a queue, any replica may run the next attempt.

## Cookbooks

| File | What it shows |
|---|---|
| `e2b_template.py` | Builds the E2B template the provider runs. |
| `e2b_session.py` | Two turns of one session through the raw provider and runtime client. `--pause` takes the warm path, `--replace` the cold path through a checkpoint, `--runtime-port` the runtime server transport. |
| `sandbox_claude_e2b.py` | `ClaudeAgent(sandbox=E2BSandbox(...))` run directly: two turns, each on a fresh computer restored from the last checkpoint. |
| `sandbox_claude_e2b_agentos.py` | The same agent behind AgentOS with a durable queue, using the runtime server transport. |
| `e2b_load.py` | Load test: concurrent sessions through create, three runtime transports, pause/resume and checkpoint capture/restore, with latencies and E2B API calls per turn. |

## How the provider works

`E2BSandbox(template, namespace=...)` implements the same `Sandbox` contract as `DockerSandbox`.

**Identity.** E2B assigns random sandbox IDs, so each generation carries its namespace, agent, session, generation and configuration digest as E2B metadata, and `create` and `find` look it up by that metadata. A create whose reply was lost is found again; if two computers ever exist for one generation, the oldest is kept and the others are killed. The E2B SDK never resends a create, so duplicates need a lost reply followed by a retry. E2B's listings lag a create by up to a second and successive ones can disagree, so create waits until a listing shows its new computer, decides from that listing, and kills its computer if none does within ten seconds, or if listing, hardening or the runtime server start fails or the create is cancelled. The provider also remembers the computer it handed out for each generation and checks it directly when a listing leaves it out. E2B has no atomic allocation, so creates of one generation run one at a time within a provider, and processes must not create the same generation at once; `SandboxCoordinator` allocates under the session's lease, which guarantees this.

**Privileges.** Commands run as E2B's `user` in `/workspace`, with `/runtime` as its home. E2B gives that user passwordless sudo after the template's own build steps, so `create` strips every setuid bit as root and checks none remain before anything runs as `user`; a computer that cannot be hardened is killed. Checkpoint archives pass through `/var/lib/agno-sandbox`, which only root can read.

**Runtime transport.** Without `runtime_port`, every runtime start and poll runs `python -m agno.sandbox.runtime` as a command, as `DockerSandbox` does by default. With `runtime_port`, create starts the runtime server inside the computer and start/poll go to its public E2B URL, `https://<port>-<sandbox id>.e2b.app`, with a bearer token generated per computer. The token is stored in the computer's E2B metadata, so any replica holding the E2B API key can talk to the server; it is given only to the server process, not to commands.

**Lifecycle.** `lifetime` is the E2B timeout: E2B kills a running computer when it passes, and a turn still running dies with it. `execution_timeout` must be shorter and defaults to 900 seconds or half the lifetime. Pause keeps memory, files and processes, takes under a second, and does not count against the lifetime; resume restarts it. Create never resumes a paused generation and E2B never resumes it on its own (`auto_resume` is off). Stop and destroy both kill the computer, which keeps nothing.

**Commands.** The E2B command API has no stdin, so the runner's request is staged as a file first and deleted by the command. A lost connection does not end a command inside the computer, so an uncertain command outcome, a timeout or an output overflow kills the computer, as with Docker. Runtime start and poll leave compute alone on failure.

**Checkpoints.** `E2BCheckpointTransfer` implements the same `CheckpointTransfer` protocol as `DockerCheckpointTransfer`. Root stops the agent user's processes so files hold still, and a child dropped to `user` runs the shared `CheckpointArchive.capture` into the root-only directory. The archive streams to the host through the E2B file API over HTTP/1.1, since the SDK's HTTP/2 client drops E2B file streams after a few megabytes, and is validated, including its exclusions, before it is stored. Restore validates the stored archive, uploads it, and a child dropped to `user` restores it into the empty roots. A failed restore kills the computer.

Differences from Docker:

| Behavior | E2B |
|---|---|
| Identity | Random IDs, found again by metadata. Duplicates from a lost create reply are killed, keeping the oldest. |
| Pause | Native, keeps memory and processes, about one to two seconds each way. Not tied to one host. A warm computer the coordinator keeps between turns is a paused sandbox, which E2B does not expire. |
| Lifetime | Enforced by E2B. Plans cap it, one hour on Hobby and 24 hours on Pro. |
| Resources | Fixed by the template build (`--cpus`, `--memory-mb`), not per sandbox. |
| Network | Internet egress on by default (`allow_internet_access`). The runtime port is public and protected by its bearer token. |
