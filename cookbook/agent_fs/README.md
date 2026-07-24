# AgentFS

A durable, private filesystem for agents. To the agent it looks exactly like a normal filesystem toolkit; underneath it is a pluggable storage backend, database by default. 5 folders: 12 single-file runnable examples.

AgentFS is the fourth kind of state — the agent's own notes to its future self:

| State | What It Captures | Written by | Use Case |
|-------|------------------|------------|----------|
| **Memory** | Facts about the user | LLM-curated | Personalization |
| **Session state** | Conversation state | Framework | Task continuity within a session |
| **Knowledge** | Reference material | Authored outside the agent | RAG, grounding |
| **AgentFS** | The agent's own working state — records processed, decisions, checkpoints | The agent, verbatim | Recurring jobs, dedupe, resume |

If it's about the user, it's memory. If it dies with the conversation, it's session state. If it was authored outside the agent, it's knowledge. If the agent wrote it for its future self, it's AgentFS.

Each subfolder holds examples for one pattern, containing a `basic.py` that runs end-to-end plus variants that add task-meaningful options on top. `_05_operations/` is the one exception with no `basic.py` — it holds two independent operational recipes with no simplest-case ordering.

Start with [`_01_getting_started/basic.py`](_01_getting_started/basic.py) — and run it twice: it proves the store survives the process, not just the session.

## Layout

````
cookbook/agent_fs/
├── README.md
├── _01_getting_started/        # attach with one line; durability across processes
│   ├── README.md
│   ├── basic.py                # run twice: write in run 1, recall in run 2
│   ├── standalone.py           # no Agent, no model, no keys — the programmatic API
│   ├── local_backend.py        # swap DbFileSystem for LocalFileSystem, agent unchanged
│   └── TEST_LOG.md
├── _02_durable_records/        # the dedupe pattern: check_lines -> act -> append_file
├── _03_working_state/          # checkpoints and monitors that survive restarts
├── _04_multi_tenancy/          # templated namespaces, factories, explicit sharing
└── _05_operations/             # quota recovery and namespace inspection (no basic.py)
````

## Workflows

- [`_01_getting_started/`](_01_getting_started/): attach AgentFS to an agent with one line; prove durability across processes; use it standalone; swap the storage backend.
- [`_02_durable_records/`](_02_durable_records/): never repeat work — exact-line dedupe with `check_lines` and `append_file`, ending in a scheduled news agent that reports only the delta.
- [`_03_working_state/`](_03_working_state/): long-running work that survives restarts — progress checkpoints and a last-seen monitor.
- [`_04_multi_tenancy/`](_04_multi_tenancy/): one static agent, per-user file stores via `namespace="assistant/{user_id}"`; a callable tool factory for arbitrary policy; two agents sharing one namespace with a read-only consumer.
- [`_05_operations/`](_05_operations/): hitting the storage cap and recovering; inspecting and seeding a live agent's namespace programmatically.

## Running a cookbook

From the agno repo root, create the demo venv:

```bash
./scripts/demo_setup.sh
```

```bash
source .venvs/demo/bin/activate
```

```bash
python cookbook/agent_fs/_01_getting_started/basic.py
```

Examples default to `DbFileSystem` on SQLite so everything runs without services; the same code points at Postgres in production by changing the `db_url`. Agent examples use `OPENAI_API_KEY` (gpt-5.5); `standalone.py`, `quota_recovery.py`, and `inspect_namespace.py` run with no keys at all.

## One file-like toolkit per agent

AgentFS deliberately shares tool names (`read_file`, `write_file`, `list_files`, ...) with `Workspace`, `FileTools`, `PythonTools`, and the rest of the file-toolkit family — an agent that knows how to use a workspace already knows how to use AgentFS. The tool resolver keeps the first registration per name and drops later duplicates with a logged warning, so `tools=[PythonTools(), fs.tools()]` would silently split reads and writes across two different stores. Attach at most one file-like toolkit per agent; when an agent genuinely needs both AgentFS and a local workspace, wrap one in a sub-agent.
