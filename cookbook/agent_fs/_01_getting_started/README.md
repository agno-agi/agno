# Getting Started

Attach a durable, private filesystem to an agent with one line: `Agent(tools=[fs.tools()])`. Input is an ordinary agent plus that one line; output is an agent whose files survive every future run, session, and process — the toolkit carries its own instructions.

## Files

- `basic.py` — write a note in run 1, recall it in run 2. This file deliberately reuses one database file across invocations: **run it twice** — durability across processes is the whole point. Delete `tmp/agent_fs_getting_started.db` to reset it.
- `standalone.py` — AgentFS with no `Agent` import at all: seed, read, append, check membership, and measure usage from plain Python. Runs with no API keys.
- `local_backend.py` — swap `DbFileSystem` for `LocalFileSystem`; the agent code does not change. Prints the on-disk tree so you can see the files with ordinary shell tools. Takes its root directory from `AGNO_FS_ROOT` (per-run default under `tmp/`).

## When to use

- Any agent that should remember its own work between runs — start here.
- Seeding or reading an agent's files from scripts and tests: `standalone.py`.
- Local development where you want to `cat` the store: `local_backend.py`.
- For the record-keeping dedupe pattern, continue to [`_02_durable_records/`](../_02_durable_records/). For per-user isolation, see [`_04_multi_tenancy/`](../_04_multi_tenancy/).

## Run

```bash
python cookbook/agent_fs/_01_getting_started/basic.py
python cookbook/agent_fs/_01_getting_started/basic.py   # yes, twice
python cookbook/agent_fs/_01_getting_started/standalone.py
python cookbook/agent_fs/_01_getting_started/local_backend.py
```

`basic.py` and `local_backend.py` require `OPENAI_API_KEY`; `standalone.py` needs no keys.
