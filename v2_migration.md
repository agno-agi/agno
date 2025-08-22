# Agno v2 Migration Guide

This guide walks you through all the changes needed to migrate your Agno applications from v1 to v2.

If you have questions during your migration, we're here to help! Reach out to us on [Discord](https://discord.gg/4MtYHHrgA8) or [Discourse](https://community.agno.com/).

## 1. Migrating your Agno DB

If you used our `Storage` or `Memory` functionalities to store Agent sessions and memories in your database, you can start by migrating your tables.

- You can use our migration script: `agno/scripts/migrate_to_v2.py`
- Follow the script instructions and run it.
- Your v2-ready tables will be available afterwards.

Notice:
- The script won't cleanup the old tables, in case you still need them.
- The script is idempotent. If something goes wrong or if you stop it mid-run, you can run it again.

## 2. Migrating your Agno code

Each section covers a specific framework domain, with before and after examples and detailed explanations where needed.

### Agents and Teams

Agents and Teams are the main building blocks in the Agno framework.

These are the v2 updates we have made to the `Agent` and `Team` classes:

1. Streaming responses with `arun` now returns an `AsyncIterator`, not a coroutine. This is how you consume the resulting events now, when streaming a run:
```python v2_arun.py
async for event in agent.arun(...):
    ...
```

2. The `RunResponse` class is now `RunOutput`. This is the type of the results you get when running an Agent:

```python v2_run_output.py
from agno.run.agent import RunOutput

run_output: RunOutput = agent.run(...)
```

3.  The events you get when streaming an Agent result have been renamed:
    - `RunOutputStartedEvent` → `RunStartedEvent`
    - `RunOutputCompletedEvent` → `RunCompletedEvent`
    - `RunOutputErrorEvent` → `RunErrorEvent`
    - `RunOutputCancelledEvent` → `RunCancelledEvent`
    - `RunOutputContinuedEvent` → `RunContinuedEvent`
    - `RunOutputPausedEvent` → `RunPausedEvent`
    - `RunOutputContentEvent` → `RunContentEvent`

4. Similarly, for Team output events:
    - `TeamRunOutputStartedEvent` → `TeamRunStartedEvent`
    - `TeamRunOutputCompletedEvent` → `TeamRunCompletedEvent`
    - `TeamRunOutputErrorEvent` → `TeamRunErrorEvent`
    - `TeamRunOutputCancelledEvent` → `TeamRunCancelledEvent`
    - `TeamRunOutputContentEvent` → `TeamRunContentEvent`


5. **Renamed args and methods**
- `agent_id` -> `id`
- `add_session_summary_references` -> `add_session_summary_to_context`
- `add_memory_references` -> `add_memories_to_context`
- `add_context` -> `add_dependencies`
- `add_history_to_messages` -> `add_history_to_context`
- `add_messages` -> `additional_messages`
- `add_datetime_to_instructions` -> `add_datetime_to_context`
- `add_location_to_instructions` -> `add_location_to_context`
- `add_name_to_instructions` -> `add_name_to_context`
- `context` -> `dependencies`
- `extra_data` -> `metadata`
- `goal` -> `success_criteria`
- Some methods have been made private e.g. `set_id` -> `_set_id`. You can assume methods which name start with underscore are private, and only to be used inside the Agent class itself.

6. **Deprecated args and methods**
- `resolve_context`
- `show_tool_calls`


### Storage

Storage is used to persist Agent sessions, state and memories in a database.

This is how Storage looks like on v1:

```python v1_storage.py
from agno.agent import Agent
from agno.storage.sqlite import SqliteStorage

storage = SqliteStorage(table_name="agent_sessions", db_file="agno.db", mode="agent")

agent = Agent(storage=storage)
```

These are the changes we have made for v2:

1. The `Storage` classes have moved from `agno/storage` to `agno/db`. We will now refer to them as our `Db` classes.
2. The `mode` parameter has been deprecated. The same instance can now be used by Agents, Teams and Workflows.

```python v2_storage.py
from agno.agent import Agent
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="agno.db")

agent = Agent(db=db)
```

3. The `table_name` parameter has been deprecated. One instance now handles multiple tables, you can define their names individually.
```python v2_storage_table_names.py
db = SqliteDb(db_file="agno.db", sessions_table="your_sessions_table_name", ...)
```

These are all the supported tables, each used to persist data related to a specific domain:
```python v2_storage_all_tables.py
db = SqliteDb(
    db_file="agno.db",
    # Table to store your Agent, Team and Workflow sessions and runs
    session_table="your_session_table_name",
    # Table to store all user memories
    memory_table="your_memory_table_name",
    # Table to store all metrics aggregations
    metrics_table="your_metrics_table_name",
    # Table to store all your evaluation data
    eval_table="your_evals_table_name",
    # Table to store all your knowledge content
    knowledge_table="your_knowledge_table_name",
)
```

4. Previously running a `Team` would create a team session and sessions for every team member participating in the run. Now, only the `Team` session is created. The runs for the team leader and all members can be found in the `Team` session.
```python v2_storage_team_sessions.py
team.run(...)

team_session = team.get_latest_session()

# The runs for the team leader and all team members are here
team_session.runs
```

You can find examples for all other databases and advanced scenarios in the `/cookbook` folder.

### Memory

Memory gives an Agent the ability to recall relevant information.

This is how Memory looks like on V1:

```python v1_memory.py
from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory

memory_db = SqliteMemoryDb(table_name="memory", db_file="agno.db")
memory = Memory(db=memory_db)

agent = Agent(memory=memory)
```

These are the changes we have made for v2:

1. The `MemoryDb` classes have been deprecated. The main `Db` classes are to be used.
2. The `Memory` class has been deprecated. You now just need to set `enable_user_memories=True` on an Agent with a `db` for Memory to work.

```python v2_memory.py
from agno.agent import Agent
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="agno.db")

agent = Agent(db=db, enable_user_memories=True)
```

3. The generated memories will be stored in the `memories_table`. By default, the `agno_memories` will be used. It will be created if needed. You can also set the memory table like this:

```python v2_memory_set_table.py
db = SqliteDb(db_file="agno.db", memory_table="your_memory_table_name")
```

4. The methods you previously had access to through the Memory class, are now direclty available on the relevant `db` object. For example:
``` python v2_memory_db_methods.py
agent.db.get_user_memories(user_id="123")
```

You can find examples for other all other databases and advanced scenarios in the `/cookbook` folder.

### [wip] Knowledge

**Renamed**
- `retriever` -> `knowledge_retriever`
- `add_references` -> `add_knowledge_to_context`

### Metrics

Metrics are used to understand the usage and consumption related to a Session, a Run or a Message.

These are the changes we have made for v2:

1. The `time` field has been renamed to `duration`.
2. Provider-specific metrics fields are now to be found inside the `provider_metrics` field.
3. A new `additional_metrics` field has been added for you to add any extra fields you need.

### Workflows

We have heavily updated our Workflows, aiming to provide top-of-the-line tooling to build agentic systems.

You can check a comprehensive migration guide for Workflows here: https://docs.agno.com/workflows_2/migration


### Playground

Our `Playground` has been deprecated. Our new platform offering will substitute all usage cases. More information coming soon!

