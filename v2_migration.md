# Agno v1 to v2 migration guide

This guide aims to help migrating your Agno code to v2.

## Storage

Storage is used to persist Agent sessions, state and memories in a database. This is how Storage looks like on V1:

```python v1_storage.py
from agno.agent import Agent
from agno.storage.sqlite import SqliteStorage

storage = SqliteStorage(table_name="agent_sessions", db_file="agno.db", mode="agent")

agent = Agent(storage=storage)
```

### Storage V2

- All previously available databases are also supported on V2.
- The `Storage` classes have moved from `agno/storage` to `agno/db`. We will now refer to them as our `Db` classes.
- The `mode` parameter has been deprecated. The same instance can now be used by Agents, Teams and Workflows.
- The `table_name` parameter has been deprecated. One instance can now handle multiple tables, you can define their names as shown in the following example.

```python v2_storage.py
from agno.agent import Agent
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="agno.db")

agent = Agent(db=db)
```

You can find examples for all other databases and advanced scenarios in the `/cookbook` folder.

## Memory

Memory gives an Agent the ability to recall relevant information. This is how Memory looks like on V1:

```python v1_memory.py
from agno.agent import Agent
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory

memory_db = SqliteMemoryDb(table_name="memory", db_file="agno.db")
memory = Memory(db=memory_db)

agent = Agent(memory=memory)
```

### Memory V2

- The `MemoryDb` classes have been deprecated. The main `Db` classes are to be used.
- The `Memory` class has been deprecated. You now just need to set `enable_user_memories=True` on an Agent with a `db` for Memory to work.

```python v2_memory.py
from agno.agent import Agent
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="agno.db")

agent = Agent(db=db, enable_user_memories=True)
```

- The generated memories will be stored in the `memories_table`. By default, the `agno_memories` will be used. It will be created if needed. You can also set the memory table like this:

```python v2_memory_set_table.py
db = SqliteDb(db_file="agno.db", memory_table="your_memory_table_name")
```

- The methods you previously had access to through the Memory class, are now direclty available on the relevant `db` object. For example:
``` python v2_memory_db_methods.py
agent.db.get_user_memories(user_id="123")
```

You can find examples for other all other databases and advanced scenarios in the `/cookbook` folder.

## Knowledge v2


## Workflows v2

We have heavily updated our Workflows, aiming to provide top-of-the-line tooling to build agentic systems.
You can check a comprehensive migration guide for Workflows here: https://docs.agno.com/workflows_2/migration

## Migrating your DB

If you used `Storage` or `Memory` to store Agent sessions and memories in you database, you must migrate your tables for them to be used in v2.

- We have a migration script to make it easy: `agno/scripts/migrate_to_v2.py`
- Follow the script instructions and run it. Your new v2-ready tables will be available afterwards.

Notice:
- The script won't cleanup the old tables, in case you still need them.
- The script is idempotent. If something goes wrong or if you stop it mid-run, you can run it again.