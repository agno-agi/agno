# Modal

`ModalSandbox` runs each turn in a Modal sandbox instead of a local container. The agent, the queue and the database stay wherever AgentOS runs; only the turns move to Modal. The runtime image is built on Modal from the same `Dockerfile` that Docker and AgentCore use.

## Getting started

These steps create billable Modal compute.

1. Install the extra and sign in:

   ```bash
   pip install "agno[modal-sandbox]"
   modal token new
   ```

2. Smoke test without a model, then with one. The first run builds the image on Modal, which takes a few minutes; later runs reuse the cached build:

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/modal/modal_session.py                            # fixture, no model calls
   .venv/bin/python cookbook/frameworks/sandbox/modal/modal_session.py --harness claude           # forwards ANTHROPIC_API_KEY
   .venv/bin/python cookbook/frameworks/sandbox/modal/modal_session.py --harness codex --replace  # turn 2 on a restored sandbox
   ```

3. Swap the provider on your agent. Nothing else about the agent changes:

   ```python
   from agno.sandbox.checkpoint import FileCheckpointStore
   from agno.sandbox.modal import ModalSandbox

   sandbox = ModalSandbox(
       "registry.example.com/agno-sandbox:1",  # or a modal.Image
       checkpoints=FileCheckpointStore(shared_path),
   )
   agent = ClaudeAgent(id="coder", db=db, sandbox=sandbox)
   ```

   `sandbox_claude_modal.py` is this agent run directly, two turns on a new session.

4. Serve it through AgentOS with a durable queue. Run Postgres and Redis, then `sandbox_claude_modal_agentos.py`. Point `checkpoints=` at storage every replica can read, such as `S3CheckpointStore` or `PostgresCheckpointStore`: with a queue, any replica may run the next attempt. The cookbook uses S3 when `AGNO_SANDBOX_CHECKPOINT_BUCKET` is set.

## Cookbooks

| Cookbook | What it shows |
|---|---|
| `modal_image.py` | Builds the shared runtime image on Modal from the parent `Dockerfile`, sending only the package sources. The other cookbooks import it. |
| `modal_session.py` | Two turns of one session through the runtime client. By default turn 2 calls `create` again and gets the same sandbox; `--replace` captures a checkpoint, destroys the sandbox and restores generation 2 on a fresh one. Real harnesses must recall a codeword only the conversation holds. |
| `sandbox_claude_modal.py` | The same agent as `docker/sandbox_claude.py` with `sandbox=ModalSandbox(...)`. |
| `sandbox_claude_modal_agentos.py` | That agent served through AgentOS with a durable queue. |
| `modal_load.py` | Many concurrent sessions, each created, run through one fixture turn and one command, and destroyed. `--sessions`, `--turn-seconds` and `--create-rate` shape the burst. |

`warm_turns.py --provider modal` in the parent folder shows the warm and cold paths with timings.

## How the provider works

`ModalSandbox(image, app_name="agno-sandbox", namespace=...)` implements the same `Sandbox` contract as `DockerSandbox`. Every generation is a Modal sandbox in one Modal app, named after its namespace, agent, session and generation, so `create` is idempotent and finds a sandbox again after a lost reply. Tags on the sandbox record the identity and a digest of the configuration, and a generation created with other settings is refused. `env` is passed to Modal as a secret.

A string image is pulled from a registry with its entrypoint cleared; a `modal.Image` is used as given. The image must provide `python` with this package installed, `tar` and `setpriv`. At create, the provider makes `/workspace` and `/runtime` for UID 1000, and every command runs as that user through `setpriv`; pass `uid=None` to run as root. Commands go through Modal exec using the same bounded runner as Docker, and the runtime's start and poll requests use exec as well.

`ModalCheckpointTransfer` implements the same `CheckpointTransfer` protocol as `DockerCheckpointTransfer`. Capture streams a tar of `/workspace` and `/runtime/native` out over exec stdout, bounded by the archive's byte limit, and the host repacks and validates it with the same code Docker uses before storing it. Restore validates the stored archive on the host, checks that the generation is empty, and streams a repacked tar per root back in. A failed restore terminates the sandbox.

Differences from Docker:

| Behavior | Modal |
|---|---|
| Stopped generation | Stop and destroy both terminate the sandbox; Modal keeps nothing. Modal frees the name once a sandbox ends, so `create` cannot tell an ended generation from a new one. A provider object refuses to recreate a generation it stopped itself; other replicas rely on the coordinator, which moves to a new generation after any loss. |
| Pause | Not supported. A warm sandbox stays running between turns until its window ends or Modal's timeout ends it. Only `sweep_warm` on a running coordinator or `retire_computer` removes it earlier, so a process that exits after a turn, such as a stopped AgentOS server, leaves it running and billed for up to `lifetime`. Lower `lifetime` or retire the session's computer before exiting. |
| Lifetime | `lifetime` (default 3600 seconds) is Modal's sandbox timeout. A turn still running at the deadline dies with the sandbox. `execution_timeout` must be shorter, and the coordinator only resumes a warm sandbox with room left for another turn. |
| Capture | Modal cannot freeze a sandbox, so capture relies on the coordinator having drained the turn. |
| Network | Egress is open by default. `block_network=True` blocks it; `outbound_domain_allowlist` limits it to named domains, which must include the model API. |
| Transport | Every start and poll is a Modal exec, which costs more than Docker's published runtime port. |
