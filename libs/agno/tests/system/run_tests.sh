#!/bin/bash
# Script to run the AgentOS system tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== AgentOS System Tests ===${NC}"

# Check for required environment variables
if [ -z "$OPENAI_API_KEY" ]; then
    if [ -f ".env" ]; then
        echo -e "${YELLOW}Loading environment from .env file${NC}"
        export $(cat .env | xargs)
    else
        echo -e "${RED}Error: OPENAI_API_KEY not set and no .env file found${NC}"
        echo "Please set OPENAI_API_KEY or create a .env file with:"
        echo "  OPENAI_API_KEY=your-api-key-here"
        exit 1
    fi
fi

# Parse command line arguments
REBUILD=false
DOWN_AFTER=false
SKIP_BUILD=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --rebuild)
            REBUILD=true
            shift
            ;;
        --down)
            DOWN_AFTER=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        *)
            break
            ;;
    esac
done

# Clean up if rebuild requested
if [ "$REBUILD" = true ]; then
    echo -e "${YELLOW}Rebuilding containers from scratch...${NC}"
    docker compose down -v
fi

# Start containers
if [ "$SKIP_BUILD" = false ]; then
    echo -e "${GREEN}Building and starting containers...${NC}"
    docker compose up --build -d
else
    echo -e "${GREEN}Starting containers (skip build)...${NC}"
    docker compose up -d
fi

# Wait for services to be healthy
echo -e "${YELLOW}Waiting for services to be healthy...${NC}"
MAX_WAIT=120
WAIT_INTERVAL=5
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    GATEWAY_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' system-test-gateway 2>/dev/null || echo "not_found")
    REMOTE_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' system-test-remote 2>/dev/null || echo "not_found")
    POSTGRES_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' system-test-postgres 2>/dev/null || echo "not_found")

    if [ "$GATEWAY_HEALTH" = "healthy" ] && [ "$REMOTE_HEALTH" = "healthy" ] && [ "$POSTGRES_HEALTH" = "healthy" ]; then
        echo -e "${GREEN}All services are healthy!${NC}"
        break
    fi

    echo "  Postgres: $POSTGRES_HEALTH, Remote: $REMOTE_HEALTH, Gateway: $GATEWAY_HEALTH"
    sleep $WAIT_INTERVAL
    ELAPSED=$((ELAPSED + WAIT_INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo -e "${RED}Timeout waiting for services to be healthy${NC}"
    echo "Container logs:"
    docker compose logs --tail=50
    exit 1
fi

# Install test dependencies
echo -e "${GREEN}Installing test dependencies...${NC}"
pip install -q -r requirements.txt

# Run tests
echo -e "${GREEN}Running tests...${NC}"
if [ $# -eq 0 ]; then
    # No test files specified, run all tests
    pytest
else
    # Run specific test files passed as arguments
    pytest "$@"
fi
TEST_EXIT_CODE=$?

# Clean up if requested
if [ "$DOWN_AFTER" = true ]; then
    echo -e "${YELLOW}Stopping containers...${NC}"
    docker compose down
fi

exit $TEST_EXIT_CODE

