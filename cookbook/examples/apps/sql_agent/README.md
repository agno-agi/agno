# SQL Agent

This advanced example shows how to build a sophisticated text-to-SQL system that leverages Agentic RAG to provide deep insights into any data. We'll use the F1 dataset as an example, but the system is designed to be easily extensible to other datasets.

The agent uses Agentic RAG to search for table metadata and rules, enabling it to write and run better SQL queries.

> Note: Fork and clone the repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install libraries

```shell
pip install -r cookbook/examples/apps/sql_agent/requirements.txt
```

### 3. Run PgVector

Let's use Postgres for storing our data, but the SQL Agent should work with any database.

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

- Run using a helper script

```shell
./cookbook/run_pgvector.sh
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

### 4. Load F1 data

```shell
python cookbook/examples/apps/sql_agent/load_f1_data.py
```

### 5. Load the knowledge base

The knowledge base contains table metadata, rules and sample queries, which are used by the Agent to improve responses.

We recommend adding the following as you go along:
  - Add `table_rules` and `column_rules` to the table metadata. The Agent is prompted to follow them. This is useful when you want to guide the Agent to always query date in a particular format, or avoid certain columns.
  - Add sample SQL queries to the `cookbook/use_cases/apps/sql_agent/knowledge_base/sample_queries.sql` file. This will give the Assistant a head start on how to write complex queries.

```shell
python cookbook/examples/apps/sql_agent/load_knowledge.py
```

### 6. Export API Keys

We recommend using gpt-4o for this task, but you can use any Model you like.

```shell
export OPENAI_API_KEY=***
```

Other API keys are optional, but if you'd like to test:

```shell
export ANTHROPIC_API_KEY=***
export GOOGLE_API_KEY=***
export GROQ_API_KEY=***
```

### 7. Run SQL Agent

```shell
streamlit run cookbook/examples/apps/sql_agent/app.py
```

- Open [localhost:8501](http://localhost:8501) to view the SQL Agent.

### 8. Message us on [discord](https://agno.link/discord) if you have any questions

