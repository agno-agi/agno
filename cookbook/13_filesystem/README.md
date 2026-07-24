# FileSystem

A durable, private filesystem for agents. To the agent it looks exactly like a normal filesystem toolkit; underneath it is a pluggable storage backend, database by default. Five folders, twelve runnable single-file examples.

FileSystem is the fourth kind of state, the notes an agent writes for its own future runs:

| State | What It Captures | Written by | Use Case |
|-------|------------------|------------|----------|
| **Memory** | Facts about the user | LLM-curated | Personalization |
| **Session state** | Conversation state | Framework | Task continuity within a session |
| **Knowledge** | Reference material | Authored outside the agent | RAG, grounding |
| **FileSystem** | The agent's own working state: records processed, decisions, checkpoints | The agent, verbatim | Recurring jobs, dedupe, resume |

If it's about the user, it's memory. If it dies with the conversation, it's session state. If it was authored outside the agent, it's knowledge. If the agent wrote it for its future self, it's FileSystem.

Each subfolder holds examples for one pattern, containing a `basic.py` that runs end-to-end plus variants that add task-meaningful options on top. `05_operations/` has no `basic.py`, because its two recipes are independent and neither one is the simpler starting point.

Start with [`01_getting_started/basic.py`](01_getting_started/basic.py) and run it twice. The second run is a new process, so it shows that the store outlives more than the session.

## Layout

````
cookbook/13_filesystem/
├── README.md
├── 01_getting_started/         # attach with one line; durability across processes
│   ├── README.md
│   ├── basic.py                # run twice: write in run 1, recall in run 2
│   ├── standalone.py           # the programmatic API, with no Agent and no model
│   ├── local_backend.py        # store files on disk instead of in a database
│   └── TEST_LOG.md
├── 02_durable_records/         # the dedupe pattern: check_lines -> act -> append_file
├── 03_working_state/           # checkpoints and monitors that survive across runs
├── 04_namespaces/              # naming a store: per-user isolation and explicit sharing
└── 05_operations/              # quota recovery and inspecting files (no basic.py)
````

## Workflows

- [`01_getting_started/`](01_getting_started/): attach FileSystem to an agent with one line, see that the files outlive the process, use FileSystem standalone, and swap the storage backend.
- [`02_durable_records/`](02_durable_records/): never repeat work, using exact-line dedupe with `check_lines` and `append_file`. Ends with a scheduled news agent that briefs only what is new.
- [`03_working_state/`](03_working_state/): progress checkpoints and a last-seen monitor, for work that runs longer than one session.
- [`04_namespaces/`](04_namespaces/): everything else uses the default store. Name a namespace when you need more than one: per-user file stores via `namespace="assistant/{user_id}"`, a callable tool factory for arbitrary policy, and two agents sharing one namespace with a read-only consumer.
- [`05_operations/`](05_operations/): hitting the storage cap and recovering, then inspecting and seeding a live agent's files programmatically.

## Running a cookbook

From the agno repo root, create the demo venv:

```bash
./scripts/demo_setup.sh
```

```bash
source .venvs/demo/bin/activate
```

```bash
python cookbook/13_filesystem/01_getting_started/basic.py
```

Examples hand `FileSystem` a `SqliteDb`, so everything runs with no services to start. The same code points at Postgres in production by passing a `PostgresDb` instead. Agent examples use `OPENAI_API_KEY` (gpt-5.5); `standalone.py`, `quota_recovery.py`, and `inspect_files.py` run with no keys at all.

## One file-like toolkit per agent

FileSystem deliberately shares tool names (`read_file`, `write_file`, `list_files`, ...) with `Workspace`, `FileTools`, `PythonTools`, and the rest of the file-toolkit family, so an agent that knows how to use a workspace already knows how to use FileSystem. The tool resolver keeps the first registration per name and drops later duplicates with a logged warning, so `tools=[PythonTools(), fs.tools()]` would silently split reads and writes across two different stores. Attach at most one file-like toolkit per agent. When an agent genuinely needs both FileSystem and a local workspace, wrap one in a sub-agent.
