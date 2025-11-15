#!/bin/bash
set -e

echo "╔════════════════════════════════════════════╗"
echo "║   AgentOS System Tests - Quick Runner     ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Check if OpenAI API key is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ Error: OPENAI_API_KEY environment variable is not set"
    echo ""
    echo "Please set it before running tests:"
    echo "  export OPENAI_API_KEY='your-api-key-here'"
    exit 1
fi

echo "✓ OpenAI API key is set"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo ""
    echo "Please start Docker and try again"
    exit 1
fi

echo "✓ Docker is running"
echo ""

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: docker-compose is not installed"
    echo ""
    echo "Please install docker-compose and try again"
    exit 1
fi

echo "✓ docker-compose is available"
echo ""

# Stop any existing containers
echo "Stopping any existing test containers..."
docker-compose down -v > /dev/null 2>&1 || true
echo ""

# Build and start services
echo "Building and starting services..."
docker-compose up -d --build

echo ""
echo "Waiting for services to be healthy..."
echo ""

# Wait for health checks
MAX_WAIT=60
WAIT_INTERVAL=2
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if docker-compose ps | grep -q "unhealthy"; then
        echo "  Waiting... ($ELAPSED seconds)"
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
    else
        # Check if nginx is responding
        if curl -s http://localhost:8080/health > /dev/null 2>&1; then
            echo "✓ All services are healthy!"
            break
        fi
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
    fi
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo "❌ Services failed to become healthy in time"
    echo ""
    echo "Showing logs:"
    docker-compose logs --tail=50
    exit 1
fi

# Give a bit more time for database migrations
sleep 5

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║          Running System Tests             ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Run tests
if pytest test_agent_os.py -v -s; then
    echo ""
    echo "╔════════════════════════════════════════════╗"
    echo "║         ✓ All Tests Passed!               ║"
    echo "╚════════════════════════════════════════════╝"
    echo ""
    TEST_RESULT=0
else
    echo ""
    echo "╔════════════════════════════════════════════╗"
    echo "║         ❌ Some Tests Failed               ║"
    echo "╚════════════════════════════════════════════╝"
    echo ""
    TEST_RESULT=1
fi

# Ask if user wants to stop services
echo ""
read -p "Do you want to stop the services? (y/N): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Stopping services..."
    docker-compose down -v
    echo "✓ Services stopped and cleaned up"
else
    echo ""
    echo "Services are still running. You can:"
    echo "  - View logs: docker-compose logs -f"
    echo "  - Stop services: docker-compose down"
    echo "  - Restart: docker-compose restart"
    echo "  - Access nginx at: http://localhost:8080"
fi

echo ""
exit $TEST_RESULT

