# Learning Demo: AgentOS + the Learning UI

A small AgentOS app that shows the learning system end to end: one agent with every database-backed learning store enabled, a seed script that populates them with real conversations, and the Learning pages at [os.agno.com](https://os.agno.com) to browse the results.

## What it shows

| Learning page | Store | Seeded with |
|---------------|-------|-------------|
| User Profiles | `user_profile` | Alice (engineering lead) and Ben (founder) |
| User Memories | `user_memory` | Preferences like "short, direct answers" |
| Session Context | `session_context` | Goal, plan, and progress for the Postgres upgrade |
| Entity Memories | `entity_memory` | Postgres Cluster, Marcus Lee, Northwind, Design System |
| Decision Logs | `decision_log` | Recommendations the agent logged with reasoning |

Learned Knowledge is not included because it requires a vector database. See [05_learned_knowledge](../05_learned_knowledge/) for that store.

## Files

- `agents.py`: The ops assistant with all five stores enabled on a SQLite database.
- `seed.py`: Six scripted conversations across two users that populate every store.
- `run.py`: The AgentOS server exposing the `/learnings` CRUD endpoints.

## Run it

### 1. Set your OpenAI key

```bash
export OPENAI_API_KEY="..."
```

### 2. Seed the learning stores

```bash
.venvs/demo/bin/python cookbook/08_learning/10_demo/seed.py
```

This runs the conversations through the agent. Extraction happens automatically, and the script prints everything the agent learned at the end.

### 3. Start the AgentOS server

```bash
.venvs/demo/bin/python cookbook/08_learning/10_demo/run.py
```

### 4. Connect from os.agno.com

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

The demo stores everything in `tmp/learning_demo.db`. Delete it and re-run `seed.py` to reset.
