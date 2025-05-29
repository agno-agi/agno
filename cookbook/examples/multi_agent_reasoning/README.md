# Multi Agent Reasoning

This cookbook demo's multi-agent reasoning using a reasoning finance team. The team is made up of two agents:

- Web Search Agent: Searches the web for information
- Finance Agent: Gets financial data using the `yfinance` library

We'll using `sonnet-4` as the team leader and `gpt-4.1` as the team members.

> Note: Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
uv venv --python 3.12
source .venv/bin/activate
```

### 2. Install libraries

```shell
uv pip install -r cookbook/examples/multi_agent_reasoning/requirements.txt
```

### 3. Run PgVector

For this example, we'll use Postgres for storing data and `PgVector` for vector search. You can use any other vectordb or storage system you like.

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

### 4. Export API Keys

We recommend using claude-4-sonnet as the team leader and gpt-4.1 as the team members.

```shell
export ANTHROPIC_API_KEY=***
export OPENAI_API_KEY=***
```

### 5. Authenticate with Agno

```shell
ag setup
```

### 6. Run Playground App

```shell
python cookbook/examples/multi_agent_reasoning/playground.py
```

- Open [app.agno.com/playground](https://app.agno.com/playground?endpoint=localhost%3A7777) to chat with your new multi-agent reasoning team.

### 7. Message us on [discord](https://agno.link/discord) if you have any questions

