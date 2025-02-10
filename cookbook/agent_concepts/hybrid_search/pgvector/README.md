## Pgvector Hybrid Search

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install libraries

```shell
pip install -U pgvector pypdf "psycopg[binary]" sqlalchemy openai agno
```

### 3. Run PgVector

```shell
./cookbook/scripts/run_pgvector.sh
```

### 4. Run PgVector Hybrid Search Agent

```shell
python cookbook/agent_concepts/hybrid_search/pgvector/agent.py
```
