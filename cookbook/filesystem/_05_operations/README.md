# Operations

Operating FileSystem stores from the outside. Point these recipes at a live agent's file store, or one about to go live, and you can inspect it, fix it and seed it. Both are plain Python against the same backend the agent uses, with no Agent, model, server or API keys involved.

There is no `basic.py` here. These are two independent operational recipes and neither one is the simpler starting point.

## Files

- `quota_recovery.py`: hits both caps on purpose, per-file and per-namespace, shows the exact error strings the agent would see, and recovers the way those errors suggest, by starting a new partition and deleting partitions you no longer need.
- `inspect_namespace.py`: attach to an agent's namespace by name from a script, then list files, measure usage, read state, and seed records the agent will dedupe against on its next run.

## When to use

- An agent's writes started failing and you want to see and fix its store: `quota_recovery.py`.
- Ops scripts, tests, and migrations that read or seed agent state without running the agent: `inspect_namespace.py`.
- To build the store these recipes operate on, start at [`_01_getting_started/`](../_01_getting_started/). The record-log layout being inspected comes from [`_02_durable_records/`](../_02_durable_records/).

## Run

```bash
python cookbook/filesystem/_05_operations/quota_recovery.py
python cookbook/filesystem/_05_operations/inspect_namespace.py
```

No environment variables required, since neither file uses a model.
