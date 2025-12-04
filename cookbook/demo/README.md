# AgentOS Demo

This demo shows how to run a multi-agent system using the **AgentOS: a high performance runtime for multi-agent systems**:

## Setup

> 💡 **Tip:** Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
uv venv .demoenv --python 3.12
source .demoenv/bin/activate
```

### 2. Install dependencies

```shell
uv pip install -r cookbook/demo/requirements.txt
```

### 3. Run Postgres with PgVector

We'll use postgres for storing session, memory and knowledge. Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) and run the following command to start a postgres container with PgVector.

```shell
./cookbook/scripts/run_pgvector.sh
```

OR use the docker run command directly:

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

We recommend using claude-sonnet-4-5 for your agents, but you can use any Model you like.

```shell
export ANTHROPIC_API_KEY=***
export OPENAI_API_KEY=***
export EXA_API_KEY=***
```

### 5. Run the demo AgentOS

```shell
python cookbook/demo/run.py
```

### 6. Connect to the AgentOS UI

- Open the web interface: [os.agno.com](https://os.agno.com/)
- Connect to http://localhost:7777 to interact with the demo AgentOS.


### Optional: Add Agno Documentation to the Knowledge Base

```shell
python cookbook/demo/agno_knowledge_agent.py
```

---

## Additional Resources

Additional Resources

📘 Documentation: https://docs.agno.com
💬 Discord: https://agno.link/discord
