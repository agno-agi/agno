# AgentOS Demo

This demo shows how to run a **multi-agent system** using **AgentOS**, the high-performance runtime built into the [Agno](https://agno.com) framework.

It includes a set of example Agents and Teams that demonstrate how AgentOS can coordinate specialized agents for tasks like research, analysis, memory management, and data retrieval.

---

## What’s Included

- 🧩 **Agno MCP Agent** — connects to the Agno MCP servers for live context and data
- 📚 **Agno Knowledge Agent** — searches the Agno documentation for information
- 🎥 **YouTube Agent** — analyzes YouTube videos and answers questions
- 💹 **Finance Agent** — retrieves and analyzes stock and market data
- 🔍 **Research Agent** — performs live research using ExaTools
- 🧾 **Finance Team** — combines research and finance data into reports to provide a full investment brief
- 🧠 **Memory Manager** — summarizes and maintains user memories

---

## Setup

> 💡 **Tip:** Fork and clone the repository first if you plan to modify the demo.

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

### 5. Add Agno Documentation to the Knowledge Base

```shell
python cookbook/demo/agno_knowledge_agent.py
```

### 6. Run the demo AgentOS

```shell
python cookbook/demo/run.py
```

### 7. Connect to the AgentOS UI

- Open the web interface: [os.agno.com](https://os.agno.com/)
- Connect to http://localhost:7777 to interact with the demo AgentOS.

---

## Additional Resources

Additional Resources

📘 Documentation: https://docs.agno.com
💬 Discord: https://agno.link/discord
