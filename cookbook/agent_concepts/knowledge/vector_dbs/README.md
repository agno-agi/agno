## Vector DBs
Vector databases enable us to store information as embeddings and search for “results similar” to our input query using cosine similarity or full text search.

## Setup

### Create a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### Install libraries

```shell
pip install -U qdrant-client pypdf openai agno
```

## Test your VectorDB

### Cassandra DB

```shell
python cookbook/vector_dbs/cassandra_db.py
```


### ChromaDB

```shell
python cookbook/vector_dbs/chroma_db.py
```

### Clickhouse

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

- Run using a helper script

```shell
./cookbook/run_clickhouse.sh
```

- OR run using the docker run command

```shell
docker run -d \
  -e CLICKHOUSE_DB=ai \
  -e CLICKHOUSE_USER=ai \
  -e CLICKHOUSE_PASSWORD=ai \
  -e CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1 \
  -v clickhouse_data:/var/lib/clickhouse/ \
  -v clickhouse_log:/var/log/clickhouse-server/ \
  -p 8123:8123 \
  -p 9000:9000 \
  --ulimit nofile=262144:262144 \
  --name clickhouse-server \
  clickhouse/clickhouse-server
```

#### Run the agent

```shell
python cookbook/vector_dbs/clickhouse.py
```

### LanceDB

```shell
python cookbook/vector_dbs/lance_db.py
```

### PgVector

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

```shell
python cookbook/vector_dbs/pg_vector.py
```

### Mem0

```shell
python cookbook/vector_dbs/mem0.py
```

### Milvus

```shell
python cookbook/vector_dbs/milvus.py
```

### Pinecone DB

```shell
python cookbook/vector_dbs/pinecone_db.py
```

### Singlestore

> Install [docker desktop](https://docs.docker.com/desktop/install/mac-install/) first.

#### Run the setup script
```shell
./cookbook/scripts/run_singlestore.sh
```

#### Create the database

- Visit http://localhost:8080 and login with username: `root` and password: `admin`
- Create the database with your choice of name. Default setup script requires AGNO as database name. `CREATE DATABASE your_database_name;`

#### Add credentials

- For SingleStore

```shell
export SINGLESTORE_HOST="localhost"
export SINGLESTORE_PORT="3306"
export SINGLESTORE_USERNAME="root"
export SINGLESTORE_PASSWORD="admin"
export SINGLESTORE_DATABASE="your_database_name"
export SINGLESTORE_SSL_CA=".certs/singlestore_bundle.pem"
```

- Set your OPENAI_API_KEY

```shell
export OPENAI_API_KEY="sk-..."
```

#### Run Agent

```shell
python cookbook/vector_dbs/singlestore.py
```


### Qdrant

```shell
docker run -p 6333:6333 -p 6334:6334 -v $(pwd)/qdrant_storage:/qdrant/storage:z qdrant/qdrant
```

```shell
python cookbook/vector_dbs/qdrant_db.py
```

### Weaviate

```shell
./cookbook/scripts/run_weviate.sh
```

```shell
python cookbook/vector_dbs/weaviate_db.py
```
