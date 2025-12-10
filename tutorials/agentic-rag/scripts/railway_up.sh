#!/bin/bash

# Deploy Agentic RAG to Railway
# Prerequisites:
# - Railway CLI installed: https://docs.railway.com/reference/cli-api
# - Logged in: railway login
# - .env file with OPENAI_API_KEY

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Load .env
if [ -f .env ]; then
    echo "Loading .env..."
    set -a
    source .env
    set +a
else
    echo "Error: No .env file found. Create one with OPENAI_API_KEY."
    exit 1
fi

# Validate OPENAI_API_KEY
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY is not set in .env"
    exit 1
fi

echo "=== Initializing Railway project ==="
railway init -n "agentic-rag"

echo ""
echo "=== Deploying PgVector database ==="
# Deploy pgvector template (template code: 3jJFCA)
# See: https://railway.com/deploy/3jJFCA
railway deploy -t 3jJFCA

echo ""
echo "Waiting for database to be ready..."
sleep 15

echo ""
echo "=== Creating API service with environment variables ==="
# Add a new service for the API with variables using Railway's reference syntax
# The pgvector template creates a service named "pgvector" with standard Postgres variables
railway add --service api \
  --variables "DB_DRIVER=postgresql+psycopg" \
  --variables 'DB_USER=${{pgvector.PGUSER}}' \
  --variables 'DB_PASS=${{pgvector.PGPASSWORD}}' \
  --variables 'DB_HOST=${{pgvector.PGHOST}}' \
  --variables 'DB_PORT=${{pgvector.PGPORT}}' \
  --variables 'DB_DATABASE=${{pgvector.PGDATABASE}}' \
  --variables "OPENAI_API_KEY=${OPENAI_API_KEY}"

echo ""
echo "=== Deploying application ==="
railway up --service api -d

echo ""
echo "=== Creating public domain ==="
railway domain --service api

echo ""
echo "=== Deployment complete! ==="
echo ""
echo "Useful commands:"
echo "  railway logs --service api  - View application logs"
echo "  railway status        - Check deployment status"
echo "  railway open          - Open project in browser"
echo "  railway variables     - View environment variables"
