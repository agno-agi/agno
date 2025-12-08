# Agentic RAG - Agno Docs Assistant

An AI-powered documentation assistant using Agentic RAG. Ask questions about Agno and get answers from the official documentation.

This example demonstrates:

**Problem 1: Search Quality**
- **Vector databases** - PgVector with hybrid search (semantic + keyword)
- **Readers** - TextReader for parsing documents
- **Chunkers** - RecursiveChunking for hierarchical text splitting
- **Embedders** - OpenAIEmbedder (text-embedding-3-small, 1536 dimensions)

**Problem 2: Access Control**
- **Preselected filters** - Hardcode filters per query (`knowledge_filters={"category": "llms"}`)
- **Agentic filters** - Agent infers filters from query (`enable_agentic_knowledge_filters=True`)
- **Filter expressions** - Complex logic with `AND`, `OR`, `NOT`, `EQ`, `IN`

For more information, checkout [Agno](https://agno.link/gh).

## Quickstart

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [OpenAI API key](https://platform.openai.com/api-keys)

### Run with Docker

```bash
git clone https://github.com/agno-agi/agno.git
cd agno/tutorials/agentic-rag
cp .env.example .env
# Add your OPENAI_API_KEY to .env

docker compose down  # Stop any existing containers
docker compose up -d --build
```

### Connect to AgentOS UI

Open [os.agno.com](https://os.agno.com) and connect with endpoint `http://localhost:8000`.

> **Note:** First startup takes 1-2 minutes while documents are loaded into the vector database. Wait for the green connection indicator before chatting.

## Running with Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start PgVector:

```bash
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:16
```

Run the app:

```bash
python -m app.main           # Start AgentOS API server
python -m app.cli            # Interactive CLI
python -m app.cli "query"    # Single query
```

## Run Examples

See all concepts in action:

```bash
python -m agents.docs_assistant
```

This runs examples showing:
1. **Search quality** - Hybrid search + recursive chunking
2. **Preselected filters** - `knowledge_filters={"category": "llms"}`
3. **Agentic filters** - Agent infers filters from query
4. **Filter expressions** - `AND(EQ("category", "llms"), EQ("doc_type", "reference"))`

## Deploying to Railway

Deploy to [Railway](https://railway.app) for production hosting.

### Prerequisites

1. Install the [Railway CLI](https://docs.railway.app/develop/cli)
2. Login: `railway login`
3. Configure `.env` with your `OPENAI_API_KEY`

### Deploy

```bash
./scripts/railway_up.sh
```

This will:
- Create a new Railway project with PgVector database
- Set all environment variables automatically
- Deploy the app and generate a public domain

### Update Existing Deployment

```bash
railway up --service api -d
```

### Connect to AgentOS UI

Once deployed, connect the [AgentOS UI](https://os.agno.com) to your Railway domain URL (e.g., `https://your-app.up.railway.app`).

View logs: `railway logs --service api`

## Learn More

- [Full Tutorial](https://docs.agno.com/tutorials/agentic-rag) - Step-by-step guide with explanations
- [Agno Documentation](https://docs.agno.com)
- [Knowledge Documentation](https://docs.agno.com/basics/knowledge/overview)
