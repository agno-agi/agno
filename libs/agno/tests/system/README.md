# AgentOS System Tests

This directory contains system tests for AgentOS that verify stateless deployment across multiple containers with load balancing.

## Architecture

The test setup consists of:
- **3 AgentOS containers**: Stateless application servers
- **1 PostgreSQL database**: Shared state storage
- **1 Nginx load balancer**: Distributes requests across containers
- **Python test suite**: Validates stateless behavior

```
┌─────────────┐
│   Client    │
│  (pytest)   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│    Nginx    │  (Round-robin load balancer)
│   Port 80   │
└──────┬──────┘
       │
       ├──────────┬──────────┐
       ▼          ▼          ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│AgentOS-1 │ │AgentOS-2 │ │AgentOS-3 │
│  :7777   │ │  :7777   │ │  :7777   │
└────┬─────┘ └────┬─────┘ └────┬─────┘
     │            │            │
     └────────────┴────────────┘
                  │
                  ▼
          ┌──────────────┐
          │  PostgreSQL  │
          │   :5432      │
          └──────────────┘
```

## Prerequisites

- Docker and Docker Compose installed
- Python 3.11+ (for running tests locally)
- OpenAI API key (set in environment)

## Setup

1. **Set environment variables**:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```

2. **Install test dependencies**:
   ```bash
   pip install pytest requests
   ```

## Running Tests

### Start the infrastructure:
```bash
cd libs/agno/tests/system
docker-compose up --build -d
```

This will:
- Build the AgentOS Docker image
- Start PostgreSQL database
- Launch 3 AgentOS containers
- Start Nginx load balancer on port 8080

### Wait for services to be ready:
```bash
# Check service health
docker-compose ps

# Check logs
docker-compose logs -f
```

### Run the tests:
```bash
# From the system tests directory
pytest test_agent_os.py -v -s

# Or run specific tests
pytest test_agent_os.py::TestAgentOSStateless::test_create_and_retrieve_session_stateless -v -s
```

### Stop and clean up:
```bash
docker-compose down -v
```

## Configuration Files

- **docker-compose.yml**: Multi-container orchestration
- **os.Dockerfile**: AgentOS container image
- **nginx.conf**: Load balancer configuration
- **test_app.py**: AgentOS application code
- **test_agent_os.py**: System test suite

## Troubleshooting

### Services not starting:
```bash
# Check individual service logs
docker-compose logs postgres
docker-compose logs agentos-1
docker-compose logs nginx

# Restart services
docker-compose restart
```

### Database connection issues:
```bash
# Verify PostgreSQL is accessible
docker-compose exec postgres psql -U agno -d agentos_test -c "\dt"
```

### Port conflicts:
If port 8080 or 5432 is already in use, modify the ports in `docker-compose.yml`:
```yaml
ports:
  - "8081:80"  # Change nginx port to 8081
```

### Tests failing:
1. Ensure all services are healthy: `docker-compose ps`
2. Check OpenAI API key is set: `echo $OPENAI_API_KEY`
3. Review logs for errors: `docker-compose logs`
4. Increase timeouts in test if network is slow
