# Operations

Operating FileSystem stores from the outside. Input is a live agent's file store (or one about to go live); output is a healthy, inspected, correctly seeded one. Both recipes are plain Python against the same backend the agent uses — no Agent, no model, no server, no API keys.

There is no `basic.py` here: these are two independent operational recipes with no simplest-case ordering.

## Files

- `quota_recovery.py` — hits both caps on purpose (per-file and per-namespace), shows the exact error strings the agent would see, and recovers the way the errors suggest: start a new partition, delete partitions you no longer need.
- `inspect_namespace.py` — attach to an agent's namespace by name from a script: list files, measure usage, read state, and seed records the agent will dedupe against on its next run.

## When to use

- An agent's writes started failing and you want to see and fix its store: `quota_recovery.py`.
- Ops scripts, tests, and migrations that read or seed agent state without running the agent: `inspect_namespace.py`.
- To build the store these recipes operate on, start at [`_01_getting_started/`](../_01_getting_started/); the record-log layout being inspected comes from [`_02_durable_records/`](../_02_durable_records/).

## Run

```bash
python cookbook/filesystem/_05_operations/quota_recovery.py
python cookbook/filesystem/_05_operations/inspect_namespace.py
```

No environment variables required — neither file uses a model.
