# Agent Memory

This section demonstrates how Agno agents persist and use user memories across runs, sessions, and agents.

## Directory Layout

- `01_agent_with_memory.py` to `08_memory_tools.py`: Core memory patterns with agents.
- `memory_manager/`: Direct `MemoryManager` API examples using PostgreSQL.
- `optimize_memories/`: Memory optimization strategy examples.

> SurrealDB memory manager examples are now located in `cookbook/92_integrations/surrealdb/`.

## Setup

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install dependencies

```shell
pip install -U psycopg sqlalchemy openai agno
```

### 3. Run an example

```shell
python cookbook/11_memory/01_agent_with_memory.py
```
