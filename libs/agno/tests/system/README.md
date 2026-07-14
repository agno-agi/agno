# AgentOS System Tests

This directory contains comprehensive system tests for AgentOS that spin up a multi-container Docker environment to test the gateway pattern and all API routes.

## Architecture

The test system consists of three containers:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Test Runner                              │
│                    (pytest on host)                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ HTTP requests
┌─────────────────────────────────────────────────────────────────┐
│                     Gateway Server                               │
│                    (port 7001)                                   │
│                                                                  │
│  - Local Agent (gateway-agent)                                   │
│  - Local Workflow (gateway-workflow)                             │
│  - RemoteAgent(assistant-agent)  ──────┐                         │
│  - RemoteAgent(researcher-agent) ──────┼──► Remote Server        │
│  - RemoteTeam(research-team)     ──────┤                         │
│  - RemoteWorkflow(qa-workflow)   ──────┘                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Internal network
┌─────────────────────────────────────────────────────────────────┐
│                     Remote Server                                │
│                    (port 7002)                                   │
│                                                                  │
│  - Agent: assistant-agent (Calculator, Knowledge)                │
│  - Agent: researcher-agent (DuckDuckGo search)                   │
│  - Team: research-team                                           │
│  - Workflow: qa-workflow                                         │
│  - Knowledge: PgVector-based                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PostgreSQL (pgvector)                        │
│                    (port 5632 external, 5432 internal)           │
│                                                                  │
│  - Sessions, Memory, Metrics                                     │
│  - Vector embeddings for Knowledge                               │
│  - Traces and Evals                                              │
└─────────────────────────────────────────────────────────────────┘
```

## Prerequisites

- Docker and Docker Compose
- Python 3.12+
- OpenAI API key (for LLM-powered tests)

## Quick Start

### 1. Set up environment

Create virtual environment
```bash
uv venv --python 3.13
source .venv/bin/activate
```

Install dependencies
```bash
uv pip install -r requirements.txt
```

Export API key
```bash
# Create .env file with your API key
echo "OPENAI_API_KEY=your-api-key-here" > .env
```

### 2. Start the containers

```bash
# Build and start all containers
docker compose up --build -d

# Wait for containers to be healthy (check status)
docker compose ps

# View logs
docker compose logs -f
```

### 3. Run the tests

#### Using run_tests.sh (Recommended)

The `run_tests.sh` script handles container management and test execution:

```bash
# Run all tests (builds containers, waits for health, runs pytest)
./run_tests.sh

# Run specific test files
./run_tests.sh test_agents_routes.py
./run_tests.sh test_agents_routes.py test_teams_routes.py

# Options
./run_tests.sh --rebuild                 # Rebuild containers from scratch
./run_tests.sh --skip-build              # Skip container build (use existing)
./run_tests.sh --down                    # Stop containers after tests
./run_tests.sh --skip-build test_agents_routes.py -v  # Combine options with pytest args
```

#### Running manually

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests
pytest -v

# Run specific test modules independently
pytest test_config_routes.py -v          # Health & config tests
pytest test_agents_routes.py -v          # Agent route tests
pytest test_teams_routes.py -v           # Team route tests
pytest test_workflows_routes.py -v       # Workflow route tests
pytest test_session_routes.py -v         # Session route tests
pytest test_memory_routes.py -v          # Memory route tests
pytest test_knowledge_routes.py -v       # Knowledge route tests
pytest test_traces_routes.py -v          # Traces route tests
pytest test_evals_routes.py -v           # Eval route tests
pytest test_metrics_routes.py -v         # Metrics route tests
pytest test_a2a_routes.py -v             # A2A protocol tests
pytest test_agui_routes.py -v            # AG-UI route tests
pytest test_mcp_routes.py -v             # MCP route tests
pytest test_slack_routes.py -v           # Slack integration tests
pytest test_agentos_routes.py -v         # Integration tests (remote resources, error handling, auth)

# Run specific test class
pytest test_agents_routes.py::test_get_agents_list -v

# Run with more output
pytest test_agents_routes.py -v --tb=long
```

### 4. Tear down

```bash
# Stop and remove containers
docker compose down

# Remove volumes too
docker compose down -v
```

## Test Structure

The tests are organized into separate modules for independent execution:

- **`test_utils.py`** - Shared utilities, fixtures, and helper functions
- **`test_config_routes.py`** - Health check and config routes
- **`test_agents_routes.py`** - Agent routes (list, details, runs)
- **`test_teams_routes.py`** - Team routes (list, details, runs)
- **`test_workflows_routes.py`** - Workflow routes (list, details, runs)
- **`test_session_routes.py`** - Session management routes
- **`test_memory_routes.py`** - Memory management routes
- **`test_knowledge_routes.py`** - Knowledge base routes
- **`test_traces_routes.py`** - Trace monitoring routes
- **`test_evals_routes.py`** - Evaluation routes
- **`test_metrics_routes.py`** - Metrics routes
- **`test_a2a_routes.py`** - A2A (Agent-to-Agent) protocol routes
- **`test_agui_routes.py`** - AG-UI routes
- **`test_mcp_routes.py`** - MCP (Model Context Protocol) routes
- **`test_slack_routes.py`** - Slack integration routes
- **`test_agentos_routes.py`** - Integration tests (remote resources, error handling, auth)

Each test module can be run independently, making it easier to:
- Debug specific functionality
- Run focused test suites in CI/CD
- Reduce test execution time during development

## Test Coverage

The tests cover all routes in the AgentOS API:

### Core Routes (`/config`, `/models`)
- `GET /config` - Get OS configuration
- `GET /models` - List available models

### Agent Routes (`/agents`)
- `GET /agents` - List all agents
- `GET /agents/{agent_id}` - Get agent details
- `POST /agents/{agent_id}/runs` - Create agent run (streaming/non-streaming)
- `POST /agents/{agent_id}/runs/{run_id}/cancel` - Cancel agent run
- `POST /agents/{agent_id}/runs/{run_id}/continue` - Continue agent run

### Team Routes (`/teams`)
- `GET /teams` - List all teams
- `GET /teams/{team_id}` - Get team details
- `POST /teams/{team_id}/runs` - Create team run

### Workflow Routes (`/workflows`)
- `GET /workflows` - List all workflows
- `GET /workflows/{workflow_id}` - Get workflow details
- `POST /workflows/{workflow_id}/runs` - Create workflow run
- `POST /workflows/{workflow_id}/runs/{run_id}/cancel` - Cancel workflow run

### Session Routes (`/sessions`)
- `GET /sessions` - List sessions with pagination
- `POST /sessions` - Create new session
- `GET /sessions/{session_id}` - Get session by ID
- `GET /sessions/{session_id}/runs` - Get session runs
- `GET /sessions/{session_id}/runs/{run_id}` - Get specific run
- `POST /sessions/{session_id}/rename` - Rename session
- `PATCH /sessions/{session_id}` - Update session
- `DELETE /sessions/{session_id}` - Delete session
- `DELETE /sessions` - Delete multiple sessions

### Memory Routes (`/memories`)
- `POST /memories` - Create memory
- `GET /memories` - List memories
- `GET /memories/{memory_id}` - Get memory by ID
- `PATCH /memories/{memory_id}` - Update memory
- `DELETE /memories/{memory_id}` - Delete memory
- `DELETE /memories` - Delete multiple memories
- `GET /memory_topics` - Get memory topics
- `GET /user_memory_stats` - Get user memory statistics
- `POST /optimize-memories` - Optimize memories

### Knowledge Routes (`/knowledge`)
- `POST /knowledge/content` - Upload content
- `GET /knowledge/content` - List content
- `GET /knowledge/content/{content_id}` - Get content by ID
- `PATCH /knowledge/content/{content_id}` - Update content
- `DELETE /knowledge/content/{content_id}` - Delete content
- `DELETE /knowledge/content` - Delete all content
- `GET /knowledge/content/{content_id}/status` - Get content status
- `POST /knowledge/search` - Search knowledge
- `GET /knowledge/config` - Get knowledge configuration

### Eval Routes (`/eval-runs`)
- `GET /eval-runs` - List evaluation runs
- `GET /eval-runs/{eval_run_id}` - Get eval run
- `POST /eval-runs` - Run evaluation
- `PATCH /eval-runs/{eval_run_id}` - Update eval run
- `DELETE /eval-runs` - Delete eval runs

### Traces Routes (`/traces`)
- `GET /traces` - List traces
- `GET /traces/{trace_id}` - Get trace detail
- `GET /trace_session_stats` - Get trace statistics

### Metrics Routes (`/metrics`)
- `GET /metrics` - Get metrics
- `POST /metrics/refresh` - Refresh metrics

### Health Routes
- `GET /health` - Health check

### Database Routes
- `POST /databases/{db_id}/migrate` - Migrate database

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key for LLM calls | Required |
| `GATEWAY_URL` | URL of gateway server for tests | `http://localhost:7001` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://ai:ai@postgres:5432/ai` |
| `REMOTE_SERVER_URL` | URL of remote server (internal) | `http://remote-server:7002` |

## Troubleshooting

### Containers not starting

```bash
# Check container logs
docker compose logs gateway-server
docker compose logs remote-server
docker compose logs postgres

# Rebuild from scratch
docker compose down -v
docker compose build --no-cache
docker compose up -d
```

### Tests timing out

Increase the timeout in the test file:

```python
REQUEST_TIMEOUT = 120.0  # seconds
```

### Database connection issues

```bash
# Check if postgres is running
docker compose exec postgres pg_isready -U ai

# Connect to database
docker compose exec postgres psql -U ai -d ai
```

### Remote server not accessible

```bash
# Check if remote server is healthy
curl http://localhost:7002/health

# Check network connectivity
docker compose exec gateway-server curl http://remote-server:7002/health
```

## Development

### Adding new tests

1. Add test methods to the appropriate test class
2. Follow the existing patterns for fixtures and assertions
3. Run tests locally before committing

### Modifying server configurations

1. Edit `gateway_server.py` or `remote_server.py`
2. Rebuild the containers: `docker compose build`
3. Restart: `docker compose up -d`
