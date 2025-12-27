# Agent Memory

Your Agents can store insights and facts about the user that it learns through conversation. This helps the agents personalize its response to the user it is interacting with. Think of this as adding “ChatGPT like memory” to your agent. This is called `Memory` in Agno.

In this section you will find a comprehensive guide showcasing what can be achieved with Memory. The examples are ordered and build on each other.

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

### 3. Run a cookbook

```shell
python cookbook/memory/memory_manager/01_standalone_memory.py
```
