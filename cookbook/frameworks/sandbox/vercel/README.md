# Vercel Sandbox

`VercelSandbox` runs each session's computer on a Vercel Sandbox microVM instead of a local container. The agent, the queue and the database stay wherever AgentOS runs; only the turns move. The concepts shared with the other providers, the checkpoint archive, how a turn completes and the session coordinator, are in the [parent README](../README.md). These steps create billable compute.

## Getting started

1. Install the extra. The Vercel SDK needs Python 3.10 or newer on the host; asking for the extra on Python 3.9 fails instead of installing nothing. The guest runs its own Python 3.12.

   ```bash
   uv pip install "agno[vercel-sandbox]"
   ```

2. Sign in to Vercel. Credentials are the SDK's: OIDC (for example after `vercel env pull`), or `VERCEL_TOKEN` with `VERCEL_TEAM_ID` and `VERCEL_PROJECT_ID`. They stay on the host. Nothing from the control plane, neither these credentials nor your database or queue settings, enters the computer. The only secrets inside it are the variables you pass in `env`, plus the model key the harness needs.

3. Build an Agno wheel from this checkout. The computer installs Agno from it, then compares the Python source it installed with the source your process imported and refuses to start on any difference, so a host running unreleased code needs a wheel built from that same code:

   ```bash
   (cd libs/agno && uv build --wheel)
   ```

   Without `wheel=`, the computer installs the Agno release that matches your host's version. That requires the release to hold exactly your source. This release-install route has not been verified; use the matching wheel for a development checkout.

4. Run the example. The fixture harness makes no model calls:

   ```bash
   ./cookbook/scripts/run_pgvector.sh        # public mode needs Postgres
   .venv/bin/python cookbook/frameworks/sandbox/vercel/vercel_session.py --wheel libs/agno/dist/agno-*.whl
   .venv/bin/python cookbook/frameworks/sandbox/vercel/vercel_session.py --wheel libs/agno/dist/agno-*.whl --mode direct
   .venv/bin/python cookbook/frameworks/sandbox/vercel/vercel_session.py --wheel libs/agno/dist/agno-*.whl --mode direct --replace
   ```

   `--harness claude` and `--harness codex` run a real model and check that turn 2 recalls a codeword that only the conversation from turn 1 holds. Claude forwards `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`, Codex forwards `OPENAI_API_KEY`.

5. Swap the provider on your agent. Nothing else about the agent changes:

   ```python
   from agno.sandbox.vercel import VercelSandbox

   sandbox = VercelSandbox(wheel="libs/agno/dist/agno-3.1.8-py3-none-any.whl", checkpoints=FileCheckpointStore(shared_path))
   agent = ClaudeAgent(id="coder", db=db, sandbox=sandbox)
   ```

## The three modes

`--mode public` is a sandboxed agent with a database. Turn 1 creates a computer and its checkpoint is stored when the turn completes. The coordinator keeps the computer running for `warm_computer_seconds` (300 by default), so turn 2 reuses it: `metadata.sandbox.resumed` is `True`, nothing is restored, and any process the first turn left running is still running. Once that window has passed, or the computer is gone, or its `lifetime` is too short for another turn, the next turn takes a new generation restored from the last checkpoint instead. The window is a reuse deadline, not a timer: nothing stops the computer when it ends.

`--mode direct` drives the runtime client by hand. Turn 2 finds the same computer with `create`. With `--replace` the computer is checkpointed after turn 1, destroyed, and turn 2 runs on generation 2, restored from the checkpoint.

The shared coordinator keeps three checkpoints per session by default. Set `VercelSandbox(retain_checkpoints=2, ...)` to keep two, or `retain_checkpoints=None` to keep every checkpoint.

## Cost, cleanup and what is not bounded

- A computer kept warm is running, and Vercel bills a running computer for its provisioned memory whether or not it is busy. It ends when the next turn claims it, when `coordinator.retire_computer` or a periodic `coordinator.sweep_warm()` (which your deployment must call) retires it, or when its `lifetime` runs out. The example retires the computer it leaves behind.
- Expiry stops compute; it does not establish that the sandbox record has been deleted. Explicitly destroy the owned sandbox and verify its absence when cleanup requires record removal.
- `lifetime` bounds how long one computer runs. It does not bound how many computers exist or the total bill. Vercel can only delete a sandbox by name, so every create attempt gets a name of its own and nothing deletes a sibling by prefix. If a create succeeds but its reply is lost, or the listing lags, a computer can exist that nothing tracks until its `lifetime` ends. Keep `lifetime` short, and check your Vercel dashboard after failures.
- Creating a computer installs Agno, the Claude and Codex SDKs and SQLAlchemy into it, so the first turn of a generation waits for that install; a computer became usable in 17.6 to 25.5 seconds in three observations on one account, which is not a guarantee. The install runs inside the coordinator's database transaction for that session, holding its connection and the session's row lock until it finishes.
- The `claude-agent-sdk`, `openai-codex` and `sqlalchemy` versions are pinned in the provider. A checkpoint is only known to restore onto a computer that installed the same versions.

## Limits and boundaries

- Vercel computers are not paused. A warm computer keeps running between turns, and `pause`/`resume` are not supported. Persistent stop and resume, snapshots, prepared images and the runtime HTTP transport are not used.
- A checkpoint holds the workspace and the harness's own state under `/runtime/native`, less the native credential files and the Codex plugin clone (`native/codex/.tmp/plugins`, which the Codex CLI rebuilds when it starts). It does not capture running processes, and a capture is refused while a turn is running. Files written by processes that run as another user than the agent are not covered.
- Absolute symlinks are preserved when restoring inside a sandbox. Extraction and ownership handoff do not follow their targets; host-side archive restoration keeps the shared default of omitting absolute links.
- Repository-backed sessions (`agent.repository`) need `git` in the computer, which is not installed. The bootstrap records whether `git` is present.
- Audio and video attachments are refused; images and files travel with a run as for the other providers.
- The computer runs your commands as an unprivileged user with no capabilities and no way to regain privilege. The control state, the environment file and the checkpoint staging directories belong to root and are out of its reach.
