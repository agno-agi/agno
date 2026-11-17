# Agent 37

`Agent37Sandbox` runs each turn in an [Agent 37](https://www.agent37.com/docs) instance instead of a local container. The agent, the queue and the database stay wherever AgentOS runs; only the turns move to Agent 37. Everything goes through Agent 37's REST API with your workspace key, so there is nothing to install beyond `agno`.

## Getting started

These steps create billable compute. You need an Agent 37 workspace with a funded wallet and an API key from its dashboard.

1. Export the key:

   ```bash
   export AGENT37_API_KEY=sk_live_...
   ```

2. Smoke test without a model. The default `agent37-base` template needs no setup:

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/agent37/agent37_execution.py
   ```

3. Build the runtime template once. A sandboxed agent needs an image that carries this package and the harness SDK. The script sends the public package sources and the parent folder's `Dockerfile` to Agent 37, which builds the image in its cloud, so no local Docker or registry is needed. It then sets the template's entrypoint to `sleep infinity`: the image's own entrypoint is the AgentCore server, and an Agent 37 instance only needs a main process that stays up.

   ```bash
   .venv/bin/python cookbook/frameworks/sandbox/agent37/agent37_setup.py deploy --name agno-sandbox
   export AGENT37_TEMPLATE=agno-sandbox
   .venv/bin/python cookbook/frameworks/sandbox/warm_turns.py --provider agent37   # fixture, no model calls
   ```

   The instance runs the package baked into the template, so run `deploy` again after upgrading `agno`; it publishes a new revision under the same name.

   To use an image you already push to a registry instead, build it for linux/amd64 and register it with `POST /v1/templates` and `"entrypoint": ["sleep", "infinity"]`.

4. Swap the provider on your agent. Nothing else about the agent changes:

   ```python
   from agno.sandbox.agent37 import Agent37Sandbox
   from agno.sandbox.checkpoint import FileCheckpointStore

   sandbox = Agent37Sandbox("agno-sandbox", checkpoints=FileCheckpointStore(shared_path))
   agent = ClaudeAgent(id="coder", db=db, sandbox=sandbox)
   ```

   `sandbox_claude_agent37.py` is this agent run directly, two turns on a new session. It needs Postgres and `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`, which the harness forwards into the instance.

5. Delete what you no longer need. `agent37_setup.py teardown --name agno-sandbox` removes the template. After a turn the instance sleeps for the warm window, at disk-only cost, so the next turn can resume it. AgentOS's queue worker retires instances whose session never returns; a script retires its own with `SandboxCoordinator.retire_computer`, as `sandbox_claude_agent37.py` does. Instances this provider creates are named `agno-...`; delete leftovers from the dashboard or with `DELETE /v1/instances/{id}`.

## Cookbooks

`agent37_setup.py` builds the template (`deploy`) and removes it (`teardown`).

`agent37_execution.py` creates an instance, writes and reads a file, reuses the instance, pauses and resumes it, and deletes it. No model credentials are needed.

`sandbox_claude_agent37.py` is the same agent as `docker/sandbox_claude.py` with `sandbox=Agent37Sandbox(template)`, so each turn runs in an Agent 37 instance.

## How the provider works

Each sandbox generation is one instance, named after its session and generation. Agent 37 has no idempotency key for creates, so a lost reply is resolved by listing the workspace for that name; when two creates of one generation overlap, the oldest instance wins and the others are deleted. `namespace` (default `"default"`) separates deployments that share a workspace.

Commands go through the exec API as root, and a small script sent with each command drops to UID 1000 in `/workspace` with `HOME=/runtime`, the same user and directories as the Docker and AgentCore sandboxes. The exec API takes one shell command with no stdin and returns at most 512 KB per stream, so larger input and output are staged in a root-only directory and moved in chunks. Every command carries a name, so a dropped connection rejoins the same run instead of starting it again; a command whose outcome is still unknown stops the instance. A command runs for at most 840 seconds; a harness turn is not bound by that, since it runs in the background and is polled.

Pause is Agent 37's sleep and resume is its start. Memory and processes are kept, except that an instance Agent 37 moved to cold storage wakes with its files only. Stop halts the instance and keeps its disk, which bills until destroy deletes it. Create never restarts a stopped generation: recovery uses a new one, restored from the checkpoint.

`env` is stored by Agent 37 with the instance and follows its naming rules, so the model key the harness forwards is held there for the instance's life. `resources`, `instance_type`, `region` and `network` are passed to Agent 37 as given; `network="deny-all"` cuts the instance off from the model API.

What to expect: checkpoints move through the exec API in chunks of 512 KiB in and 256 KiB out, eight at a time, so large workspaces are slow to capture and restore. An instance bills until it is deleted and nothing ends one on its own. Finding a generation lists every instance in the workspace.
