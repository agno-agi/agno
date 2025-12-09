# Agentic RAG - Docs Assistant

An AI-powered documentation assistant using Agentic RAG. Ask questions about Agno and get answers from the official documentation.

## Features

- **Hybrid Search** - PgVector with semantic + keyword search
- **Recursive Chunking** - Hierarchical text splitting for better context
- **Knowledge Filters** - Preselected, agentic, and filter expressions

## Setup

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [OpenAI API key](https://platform.openai.com/api-keys)

### Clone and Configure

```bash
git clone https://github.com/agno-agi/agno.git
cd agno/tutorials/agentic-rag
cp .env.example .env
# Add your OPENAI_API_KEY to .env
```

## Running with Docker

Start the application:

```bash
docker compose up --build -d
```

This starts:
- **AgentOS server** at [http://localhost:8000](http://localhost:8000)
- **PgVector database** for knowledge embeddings

### Connect to AgentOS UI

1. Open [os.agno.com](https://os.agno.com)
2. Add `http://localhost:8000` as a new endpoint

### Load Knowledge Base

```bash
docker exec -it agentic-rag-os python -m agents.docs_assistant
```

### Stop

```bash
docker compose down
```

## Development Setup

### Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Start PgVector

```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:18
```

### Run

```bash
python -m agents.docs_assistant  # Load knowledge base
python -m app.main               # Start server
```

## Deploy to Railway

### Prerequisites

1. Install [Railway CLI](https://docs.railway.app/develop/cli)
2. Login: `railway login`

### Deploy

```bash
./scripts/railway_up.sh
```

### Update

```bash
railway up --service api -d
```

Connect the [AgentOS UI](https://os.agno.com) to your Railway URL.

## Learn More

- [Full Tutorial](https://docs.agno.com/tutorials/agentic-rag)
- [Agno Documentation](https://docs.agno.com)
- [Knowledge Documentation](https://docs.agno.com/basics/knowledge/overview)
