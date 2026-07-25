# Getting Started

Attach a durable, private filesystem to an agent with one line: `Agent(tools=[fs.tools()])`. Take an ordinary agent, add that line, and its files now survive every future run, session, and process. The toolkit carries its own instructions.

## Files

- `basic.py`: write a note in run 1, recall it in run 2. This file deliberately reuses one database file across invocations, so **run it twice**. Durability across processes is the whole point. Delete `tmp/filesystem/getting_started.db` to reset it.
- `standalone.py`: FileSystem with no `Agent` import at all. Seed, read, append, check membership, and measure usage from plain Python. Runs with no API keys.
- `local_backend.py`: pass a `LocalFileSystem` instead of a database and the agent code does not change. Prints the on-disk tree so you can see the files with ordinary shell tools. Uses a fresh per-run root directory under `tmp/`.

## When to use

- Any agent that should remember its own work between runs. Start here.
- Seeding or reading an agent's files from scripts and tests: `standalone.py`.
- Local development where you want to `cat` the store: `local_backend.py`.
- For the record-keeping dedupe pattern, continue to [`02_durable_records/`](../02_durable_records/). For per-user isolation, see [`04_namespaces/`](../04_namespaces/).

## Run

```bash
python cookbook/13_filesystem/01_getting_started/basic.py
python cookbook/13_filesystem/01_getting_started/basic.py   # yes, twice
python cookbook/13_filesystem/01_getting_started/standalone.py
python cookbook/13_filesystem/01_getting_started/local_backend.py
```

`basic.py` and `local_backend.py` require `OPENAI_API_KEY`; `standalone.py` needs no keys.
