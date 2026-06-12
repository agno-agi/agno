# Learning Demo: AgentOS + the Learning UI

A small AgentOS app that shows the learning system end to end: one agent with all six learning stores enabled, a seed script that populates them with real conversations, and the Learning pages at [os.agno.com](https://os.agno.com) to browse the results.

## What it shows

| Learning page | Store | Seeded with |
|---------------|-------|-------------|
| User Profiles | `user_profile` | Alice (engineering lead) and Ben (founder) |
| User Memories | `user_memory` | Preferences like "short, direct answers" |
| Session Context | `session_context` | Goal, plan, and progress for the Postgres upgrade |
| Entity Memories | `entity_memory` | Postgres Cluster, Marcus Lee, Northwind, Design System |
| Decision Logs | `decision_log` | Recommendations the agent logged with reasoning |

The sixth store, **Learned Knowledge**, lives in pgvector rather than the `agno_learnings` table, so it surfaces through the agent instead of a Learning page: Alice teaches the agent a Postgres upgrade rule, and the agent recalls it when Ben asks a related question in a different session. Watch for the `save_learning` and `search_learnings` tool calls in the seed output.

## Files

- `agents.py`: The ops assistant with all six stores enabled on Postgres + pgvector.
- `seed.py`: Scripted conversations across two users that populate every store.
- `run.py`: The AgentOS server exposing the `/learnings` CRUD endpoints.

## Run it

### 1. Set your OpenAI key

```bash
export OPENAI_API_KEY="..."
```

### 2. Start the pgvector container

```bash
./cookbook/scripts/run_pgvector.sh
```

### 3. Seed the learning stores

```bash
.venvs/demo/bin/python cookbook/08_learning/10_demo/seed.py
```

This runs the conversations through the agent. Extraction happens automatically, and the script prints everything the agent learned at the end.

### 4. Start the AgentOS server

```bash
.venvs/demo/bin/python cookbook/08_learning/10_demo/run.py
```

### 5. Connect from os.agno.com

1. Open [os.agno.com](https://os.agno.com) and sign in
2. **Add OS** -> **Local**, connect to `http://localhost:7777`
3. Open the **Learning** section in the sidebar

Each page reads from the `agno_learnings` table through the `/learnings` REST endpoints. You can also chat with the Ops Assistant directly: it recalls what it knows about the active user and keeps learning from new conversations.

## The REST API

The same data is available over plain HTTP:

```bash
curl "http://localhost:7777/learnings?limit=10"
curl "http://localhost:7777/learnings?learning_type=user_profile"
curl "http://localhost:7777/learnings/users"
```

Interactive docs are at `http://localhost:7777/docs`. For a client-side walkthrough of the CRUD endpoints, see [cookbook/05_agent_os/learnings](../../05_agent_os/learnings/).

## Start fresh

Learnings live in the `agno_learnings` table and the `learning_demo_knowledge` vector table. Drop both and re-run `seed.py` to reset:

```bash
docker exec pgvector psql -U ai -d ai -c 'DROP TABLE IF EXISTS agno_learnings, learning_demo_knowledge;'
```
