# Working State

Long-running work that survives across sessions and runs. When a task is bigger than one run, or when observations change between runs, the agent keeps its progress in durable files instead of in the session, and picks up exactly where it left off.

Session state dies with the session, and a scheduled agent gets a fresh session per run. A checkpoint file survives both. Both examples use a fresh per-run SQLite file so demo runs start clean. A real deployment pins one fixed, shared database so the state also outlives the process, which [`01_getting_started/basic.py`](../01_getting_started/basic.py) demonstrates.

## Files

- `basic.py`: a four-step task executed two steps per run. Each run reads `state/checkpoint.md` first, does the next steps, and updates the checkpoint. The second run starts from step 3 without being told anything.
- `last_seen_monitor.py`: a monitor comparing current readings against `state/last-run.md`. Run 1 records a baseline, run 2 reports exactly what changed and updates the file.

## When to use

- Multi-run tasks such as migrations, audits and backfills, meaning anything you would checkpoint in a job queue, done by an agent instead.
- Restart-proof deployments, using the same pattern with one pinned, shared database, as above.
- Monitors and watchers that alert on change, where the last-seen value is agent working state rather than user memory.
- For exact record-set dedupe (which items did I already process?), use [`02_durable_records/`](../02_durable_records/) instead, since `check_lines` is built for that. For the basics of attaching FileSystem, see [`01_getting_started/`](../01_getting_started/).

## Run

```bash
python cookbook/13_filesystem/03_working_state/basic.py
python cookbook/13_filesystem/03_working_state/last_seen_monitor.py
```

Requires `OPENAI_API_KEY`.
