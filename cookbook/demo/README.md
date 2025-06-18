# Agno Demo Agents

This cookbook contains a collection of demo agents that showcase the capabilities of Agno.

> Note: Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
uv venv --python 3.12
source .venv/bin/activate
```

### 2. Install libraries

```shell
uv pip install -r cookbook/demo/requirements.txt
```

### 3. Run PgVector

Let's use Postgres for storing data and `PgVector` for vector search.

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

- Run using a helper script

```shell
./cookbook/scripts/run_pgvector.sh
```

- OR run using the docker run command

```shell
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgvolume:/var/lib/postgresql/data \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

### 4. Load data

Load F1 data into the database.

```shell
python cookbook/demo/sql/load_f1_data.py
```

Load F1 knowledge base

```shell
python cookbook/demo/sql/load_knowledge.py
```

### 5. Export API Keys

We recommend using claude-3-7-sonnet for this task, but you can use any Model you like.

```shell
export ANTHROPIC_API_KEY=***
```

Other API keys are optional, but if you'd like to test:

```shell
export OPENAI_API_KEY=***
export GOOGLE_API_KEY=***
export GROQ_API_KEY=***
```

### 6. Run Demo Agents

```shell
python cookbook/demo/app.py
```

- Open [app.agno.com/playground](https://app.agno.com/playground?endpoint=localhost%3A7777) to chat with the demo agents.

### 7. Message us on [discord](https://agno.link/discord) if you have any questions

