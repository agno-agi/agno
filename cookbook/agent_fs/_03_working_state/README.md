# Working State

Long-running work that survives across sessions and runs. Input is a task bigger than one run (or observations that change between runs); output is an agent that picks up exactly where it left off, because its progress lives in durable files rather than in the session.

Session state dies with the session, and scheduled agents get a fresh session per run — a checkpoint file does not. Both examples default to a fresh per-run SQLite file so demo runs start clean; a real deployment pins one fixed, shared `db_url` (or sets `AGNO_FS_DB`) so the state also outlives the process — [`_01_getting_started/basic.py`](../_01_getting_started/basic.py) is the cross-process proof.

## Files

- `basic.py` — a four-step task executed two steps per run. Each run reads `state/checkpoint.md` first, does the next steps, and updates the checkpoint. The second run starts from step 3 without being told anything.
- `last_seen_monitor.py` — a monitor comparing current readings against `state/last-run.md`: run 1 records a baseline, run 2 reports exactly what changed and updates the file.

## When to use

- Multi-run tasks: migrations, audits, backfills — anything you would checkpoint in a job queue, done by an agent instead.
- Restart-proof deployments: same pattern with a pinned `db_url`, as above.
- Monitors and watchers that alert on change: the last-seen value is agent working state, not user memory.
- For exact record-set dedupe (which items did I already process?), use [`_02_durable_records/`](../_02_durable_records/) instead — `check_lines` is built for that. For the basics of attaching AgentFS, see [`_01_getting_started/`](../_01_getting_started/).

## Run

```bash
python cookbook/agent_fs/_03_working_state/basic.py
python cookbook/agent_fs/_03_working_state/last_seen_monitor.py
```

Requires `OPENAI_API_KEY`.
