# Agentic RAG - Docs Assistant

An AI-powered documentation assistant using Agentic RAG (Retrieval-Augmented Generation). Ask questions about Agno and get answers from the official documentation.

This [tutorial](https://docs.agno.com/tutorials/agentic-rag) demonstrates:

- **AgentOS runtime:** for serving your documentation assistant agent.
- **PostgreSQL with PgVector:** for storing knowledge embeddings and agent sessions.
- **Hybrid Search:** combining semantic and keyword search for better results.

For more details, checkout [Agno](https://agno.link/gh) and give it a star!

## Setup

Follow these steps to get started:

### Clone the repo

```sh
git clone https://github.com/agno-agi/agno.git
cd agno/tutorials/agentic-rag
```

### Configure API keys

Export your OpenAI API key:

```sh
export OPENAI_API_KEY="YOUR_API_KEY_HERE"
```

> [!TIP]
> You can copy the `.env.example` file and rename it to `.env` to get started.

### Install Docker

Please install Docker Desktop from [here](https://www.docker.com/products/docker-desktop).

## Starting the application

### Local Setup

Run the application using docker compose:

```sh
docker compose up --build -d
```

This command builds the Docker image and starts the application:

- The **AgentOS server**, running on [http://localhost:8000](http://localhost:8000).
- The **PostgreSQL database** for storing agent sessions, knowledge, and memories, accessible on `localhost:5532`.

Once started, you can:

- View the AgentOS runtime at [http://localhost:8000/docs](http://localhost:8000/docs).

### Connect the AgentOS UI to the AgentOS runtime

- Open the [AgentOS UI](https://os.agno.com)
- Login and add `http://localhost:8000` as a new AgentOS. You can call it `Local AgentOS` (or any name you prefer).

### Load Knowledge Base

The Docs Assistant loads the Agno documentation into a local knowledge base and answers questions about the platform.

To populate the knowledge base, run the following command:

```sh
docker exec -it agentic-rag-os python -m agents.docs_assistant
```

### Stop the application

When you're done, stop the application using:

```sh
docker compose down
```

### Cloud Setup

To deploy the application to Railway, run the following commands:

1. Install Railway CLI:

```sh
brew install railway
```

More information on how to install Railway CLI can be found [here](https://docs.railway.com/guides/cli).

2. Login to Railway:

```sh
railway login
```

3. Deploy the application:

```sh
./scripts/railway_up.sh
```

This command will:

- Create a new Railway project.
- Deploy a PgVector database service to your Railway project.
- Build and deploy the docker image to your Railway project.
- Set environment variables in your AgentOS service.
- Create a new domain for your AgentOS service.

### Load Knowledge Base (Railway)

To load the knowledge base on your deployed Railway service:

```sh
railway ssh --service agentic-rag-os -- python -m agents.docs_assistant
```

### Updating the application

To update the application, run the following command:

```sh
railway up --service agentic-rag-os -d
```

This rebuilds and redeploys the Docker image to your Railway service.

### Deleting the application

To delete the application, run the following command:

```sh
railway down --service agentic-rag-os
railway down --service pgvector
```

Careful: This command will delete the application and PgVector database services from your Railway project.

### Connect to AgentOS UI

To connect the AgentOS UI to your deployed application:

- Open the [AgentOS UI](https://os.agno.com)
- Create a new AgentOS by clicking on the `+` button in the top left corner.
- Enter your Railway URL and click on the `Connect` button.

## Development Setup

To setup your local development environment:

### Create Virtual Environment

```sh
python -m venv .venv
source .venv/bin/activate
```

(On Windows, use `.venv\Scripts\activate`)

### Install Dependencies

```sh
pip install -r requirements.txt
```

### Start PgVector Database

```sh
docker run -d \
  -e POSTGRES_DB=ai \
  -e POSTGRES_USER=ai \
  -e POSTGRES_PASSWORD=ai \
  -p 5532:5432 \
  --name pgvector \
  agnohq/pgvector:18
```

### Run the Application

```sh
# Load knowledge base
python -m agents.docs_assistant

# Start the server
python -m app.main
```

## Learn More

- [Full Tutorial](https://docs.agno.com/tutorials/agentic-rag)
- [Agno Documentation](https://docs.agno.com)
- [Knowledge Documentation](https://docs.agno.com/basics/knowledge/overview)
- [Discord Community](https://agno.link/discord)
- [Report an Issue](https://github.com/agno-agi/agno/issues)
