# Attachment staging safety

Claude and Codex stage file/image inputs inside the active workspace under
`.agno/uploads/<run_id>`. Restoring a session on another workspace restores
attachments there and tells the harness their new paths. A stored absolute path
is a historical locator, never permission to write to another directory.

Staging rejects traversal run IDs and existing symlink upload directories/files.
A failed staging operation removes its newly created files, including partial
writes, while preserving preexisting files. Failure restoring older inputs also
cleans newly staged current inputs, even when `keep_uploads=True`.

After the turn, a run folder that the staging created is removed whole, including
anything the harness wrote next to the inputs; a folder that already existed keeps
everything except the staged inputs. A staging rejection (traversal run id, symlink)
is a `MediaStagingError`, an input check error: it is never retried by the agent's
`retries` and AgentOS reports it as an input problem.

These filesystem checks are not a substitute for a sandbox that isolates
concurrently executing hostile code. Configure a private workspace per session.

Run the cookbook to watch the behaviour with a live ClaudeAgent: a simulated staging
failure leaving nothing behind, a session continued on a replica with a different
workspace, a file Claude writes beside an attachment, and a symlinked uploads
directory refused without retries:

```bash
.venvs/demo/bin/python cookbook/frameworks/attachment_safety/attachment_staging.py
```

Run the deterministic regression scenarios without model credentials:

```bash
.venv/bin/python -m pytest libs/agno/tests/unit/agents/test_media_staging_safety.py -q
```

The suite covers both harness wrappers, current/prior input failures, path
confinement, preexisting file preservation and cleanup. See `TEST_LOG.md` for
recorded validation.
