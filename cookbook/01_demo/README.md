# Agno AgentOS Demo

This demo shows how to run a multi-agent system using the **Agno AgentOS: a high performance runtime for multi-agent systems**:

## Getting Started

### 0. Clone the repository

```shell
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 1. Create a virtual environment

```shell
uv venv .demoenv --python 3.12
source .demoenv/bin/activate
```

### 2. Install dependencies

```shell
uv pip install -r cookbook/01_demo/requirements.txt
```

### 3. Run Postgres with PgVector

We'll use postgres for storing agent sessions, memories, metrics, evals and knowledge. Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) and run the following command to start a postgres container with PgVector.

```shell
./cookbook/scripts/run_pgvector.sh
```

OR use the docker run command directly:

```shell
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -e PGDATA=/var/lib/postgresql \
  -v pgvolume:/var/lib/postgresql \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:18
```

### 4. Export API Keys

We'll use OpenAI, Anthropic and Parallel Search services. Please export the following environment variables:

```shell
export ANTHROPIC_API_KEY=***
export OPENAI_API_KEY=***
export PARALLEL_API_KEY=***
```

### 5. Run the demo AgentOS

```shell
python cookbook/01_demo/run.py
```

### 6. Connect to the AgentOS UI

- Open the web interface: [os.agno.com](https://os.agno.com/)
- Connect to http://localhost:7777 to interact with the demo AgentOS.

### Load Knowledge Base for the Agno Knowledge Agent

The Agno Knowledge Agent is a great example of building a knowledge agent using Agentic RAG. It loads the Agno documentation into pgvector and answers questions from the docs. It uses the OpenAI embedding model to embed the docs and the pgvector to store the embeddings.

To populate the knowledge base, run the following command:

```sh
python cookbook/01_demo/agents/agno_knowledge_agent.py
```

### Load data for the SQL Agent

To load the data for the SQL Agent, run:

```sh
python cookbook/01_demo/agents/sql/load_f1_data.py
```

To populate the knowledge base, run:

```sh
python cookbook/01_demo/agents/sql/load_sql_knowledge.py
```

### Load Knowledge Base for the Deep Knowledge Agent

The Deep Knowledge Agent is a great example of building a deep research agent using Agno.

To populate the knowledge base, run the following command:

```sh
python cookbook/01_demo/agents/deep_knowledge_agent.py
```

---

## Additional Resources

Need help, have a question, or want to connect with the community?

- 📚 **[Read the Agno Docs](https://docs.agno.com)** for more in-depth information.
- 💬 **Chat with us on [Discord](https://agno.link/discord)** for live discussions.
- ❓ **Ask a question on [Discourse](https://agno.link/community)** for community support.
- 🐛 **[Report an Issue](https://github.com/agno-agi/agno/issues)** on GitHub if you find a bug or have a feature request.
