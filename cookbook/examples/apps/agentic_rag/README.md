# Agentic RAG Agent

**Agentic RAG Agent** is a chat application that combines models with retrieval-augmented generation.
It allows users to ask questions based on custom knowledge bases, documents, and web data, retrieve context-aware answers, and maintain chat history across sessions.

> Note: Fork and clone this repository if needed

### 1. Create a virtual environment

```shell
python3 -m venv ~/.venvs/agenticrag
source ~/.venvs/agenticrag/bin/activate
```

### 2. Export `OPENAI_API_KEY`

```shell
export OPENAI_API_KEY=***
```

### 3. Install libraries

```shell
pip install -r cookbook/examples/apps/agentic_rag/requirements.txt
```

### 4. Run PgVector

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

### 5. Run Agentic RAG App

```shell
streamlit run cookbook/examples/apps/agentic_rag/app.py
```


### How to Use
- Open [localhost:8501](http://localhost:8501) in your browser.
- Upload documents or provide URLs (websites, csv, txt, and PDFs) to build a knowledge base.
- Enter questions in the chat interface and get context-aware answers.
- The app can also answer question using duckduckgo search without any external documents added.

### Troubleshooting
- **Docker Connection Refused**: Ensure `pgvector` and `qdrant` containers are running (`docker ps`).
- **OpenAI API Errors**: Verify that the `OPENAI_API_KEY` is set and valid.


