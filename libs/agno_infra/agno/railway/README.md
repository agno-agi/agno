# Railway Provider for Agno

Deploy applications to [Railway](https://railway.app) using Agno's infrastructure-as-code framework.

## Features

- 🚀 Deploy Docker containers to Railway
- 🔐 Secure environment variable management
- 📦 Automatic project and environment creation
- 🎯 Simple, declarative infrastructure definitions
- ♻️  Full resource lifecycle management (create, update, delete)

## Quick Start

### 1. Get Railway API Token

1. Create a Railway account at [railway.app](https://railway.app)
2. Go to [Account Settings → Tokens](https://railway.app/account/tokens)
3. Create a new API token
4. Set it as an environment variable:

```bash
export RAILWAY_API_TOKEN="your_token_here"
```

### 2. Get Workspace ID (Optional but Recommended)

Railway requires projects to be created within a workspace (team). You can either:

**Option A: Let it auto-detect** (uses your first available workspace)

**Option B: Set explicitly for better control:**

1. Log into Railway Dashboard
2. Click on your team/workspace name
3. Check the URL: `https://railway.app/team/{WORKSPACE_ID}`
4. Set the environment variable:

```bash
export RAILWAY_WORKSPACE_ID="your_workspace_id_here"
```

### 3. Deploy Your First App

```python
from agno.railway.app.base import RailwayApp
from agno.railway.resources import RailwayResources

# Define your app
app = RailwayApp(
    name="my-app",
    image_name="docker.io/nginx",
    image_tag="alpine",
    open_port=True,
    port_number=80,
    env_vars={
        "NODE_ENV": "production",
    },
)

# Create Railway resources
railway = RailwayResources(
    name="my-deployment",
    apps=[app],
    # workspace_id="your-workspace-id",  # Optional: explicit workspace
)

# Deploy!
railway.create_resources()
```

### 4. Clean Up

```python
# Delete all resources
railway.delete_resources()
```

## Architecture

The Railway provider follows Agno's infrastructure patterns:

```
RailwayResources (orchestrator)
  └── RailwayApp (application definition)
        ├── RailwayProject (top-level container)
        ├── RailwayEnvironment (production, staging, etc.)
        ├── RailwayService (the actual deployment)
        └── RailwayVariable (environment variables)
```

## Components

### RailwayResources

The main orchestrator that manages resource lifecycle.

```python
from agno.railway.resources import RailwayResources

railway = RailwayResources(
    name="my-deployment",
    api_token="optional_token",  # Falls back to env var
    apps=[app1, app2],
    resources=[custom_resource],
)
```

### RailwayApp

Base class for Railway applications.

```python
from agno.railway.app.base import RailwayApp

app = RailwayApp(
    name="my-app",
    image_name="myorg/myapp",
    image_tag="v1.0.0",
    open_port=True,
    port_number=8000,
    railway_environment="production",  # or "staging", "dev"
    service_icon="🚀",  # optional emoji
    env_vars={
        "DATABASE_URL": "postgresql://...",
        "API_KEY": "secret",
    },
)
```

### Railway Resources

Individual resources that can be managed:

- **RailwayProject**: Top-level container for all resources
- **RailwayEnvironment**: Environment (production, staging, dev)
- **RailwayService**: Application deployment from Docker image
- **RailwayVariable**: Individual environment variable
- **RailwayVariableCollection**: Bulk environment variables

## Examples

### Example 1: Simple Nginx Deployment

```python
from agno.railway.app.base import RailwayApp
from agno.railway.resources import RailwayResources

app = RailwayApp(
    name="nginx",
    image_name="docker.io/nginx",
    image_tag="alpine",
    open_port=True,
    port_number=80,
)

railway = RailwayResources(name="nginx-demo", apps=[app])
railway.create_resources()
```

### Example 2: Custom Application with Environment Variables

```python
app = RailwayApp(
    name="api",
    image_name="myorg/api",
    image_tag="latest",
    open_port=True,
    port_number=8000,
    env_vars={
        "PORT": "8000",
        "DATABASE_URL": "postgresql://user:pass@host:5432/db",
        "REDIS_URL": "redis://localhost:6379",
        "API_KEY": "secret_key",
        "NODE_ENV": "production",
    },
)

railway = RailwayResources(name="api-deployment", apps=[app])
railway.create_resources()
```

### Example 3: Multiple Environments

```python
# Production app
prod_app = RailwayApp(
    name="api-prod",
    image_name="myorg/api",
    image_tag="v1.0.0",
    railway_environment="production",
    env_vars={"NODE_ENV": "production"},
)

# Staging app
staging_app = RailwayApp(
    name="api-staging",
    image_name="myorg/api",
    image_tag="latest",
    railway_environment="staging",
    env_vars={"NODE_ENV": "staging"},
)

railway = RailwayResources(
    name="multi-env-deployment",
    apps=[prod_app, staging_app],
)
railway.create_resources()
```

### Example 4: FastAPI Application

```python
from agno.railway import RailwayFastApi, RailwayResources

# Create FastAPI app with Uvicorn configuration
app = RailwayFastApi(
    name="my-fastapi-app",
    image_name="myorg/fastapi-app",
    image_tag="latest",
    open_port=True,
    port_number=8000,
    # Uvicorn configuration
    uvicorn_host="0.0.0.0",
    uvicorn_port=8000,
    uvicorn_reload=False,
    uvicorn_log_level="info",
    web_concurrency=4,
    # Environment variables
    env_vars={
        "DATABASE_URL": "postgresql://...",
        "API_KEY": "your-api-key",
    },
)

# Deploy to Railway
railway = RailwayResources(
    name="fastapi-deployment",
    apps=[app],
)
railway.create_resources()
```

The RailwayFastApi class automatically configures Uvicorn environment variables:
- `UVICORN_HOST`: Server bind address (default: "0.0.0.0")
- `UVICORN_PORT`: Server port (default: 8000)
- `UVICORN_RELOAD`: Enable auto-reload for development
- `UVICORN_LOG_LEVEL`: Logging level (debug, info, warning, error)
- `WEB_CONCURRENCY`: Number of worker processes

### Example 5: PostgreSQL Database

```python
from agno.railway import RailwayPostgres, RailwayFastApi, RailwayResources

# Create PostgreSQL database
database = RailwayPostgres(
    name="my-database",
    postgres_version="16",
    database_name="myapp",
    postgres_user="appuser",
)

# Create FastAPI app with database connection
app = RailwayFastApi(
    name="api-with-db",
    image_name="myorg/api",
    image_tag="latest",
    database=database,  # Automatically adds DATABASE_URL
    env_vars={
        "API_KEY": "your-api-key",
    },
)

# Deploy both database and app
railway = RailwayResources(
    name="full-stack-deployment",
    apps=[database, app],  # Database first, then app
)
railway.create_resources()
```

The database automatically creates these environment variables:
- `DATABASE_URL`: Full PostgreSQL connection string
- `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`: Individual connection parameters

### Example 6: AgentOS with Agents

```python
from agno.railway import RailwayAgentOS, RailwayPostgres, RailwayResources

# Create PostgreSQL for agent persistence
database = RailwayPostgres(
    name="agent-database",
    postgres_version="16",
    database_name="agno_agents",
)

# Deploy AgentOS with agents
agentos = RailwayAgentOS(
    name="my-agentos",
    image_name="myorg/agentos-agents",  # Custom image with your agents
    image_tag="latest",
    database=database,  # Required for agent memory/sessions
    uvicorn_log_level="info",
    web_concurrency=2,
    env_vars={
        "ANTHROPIC_API_KEY": "your-key",
        "ENABLE_AGENTIC_MEMORY": "true",
    },
)

# Deploy full agent stack
railway = RailwayResources(
    name="agent-deployment",
    apps=[database, agentos],
)
railway.create_resources()
```

AgentOS automatically configures:
- Database connection from referenced database
- Uvicorn server settings
- AgentOS UI integration (https://os.agno.com)
- CORS for UI access

**Note**: For deploying agents, see the complete example in `agent-infra-railway-agents/` directory.

## Configuration

### Environment Variables

The Railway provider uses the following environment variables:

- `RAILWAY_API_TOKEN` (required): Your Railway API token
- `RAILWAY_WORKSPACE_ID` (required): Your Railway workspace/team ID
- `RAILWAY_PROJECT_ID` (optional): Default project ID
- `RAILWAY_ENVIRONMENT` (optional): Default environment name

### Workspace Configuration

Railway requires all projects to be created within a workspace (team). The workspace ID is resolved in the following priority order:

1. Explicitly provided in code (`workspace_id` parameter)
2. Set in infra settings
3. `RAILWAY_WORKSPACE_ID` environment variable
4. Auto-detected from your Railway account (uses first available workspace)

**To find your workspace ID:**

1. Log into Railway Dashboard
2. Click on your team/workspace name
3. Check the URL: `https://railway.app/team/{WORKSPACE_ID}`
4. Copy the workspace ID

**Example with explicit workspace ID:**

```python
from agno.railway import RailwayResources
from agno.railway.app import RailwayApp

app = RailwayApp(
    name="my-app",
    image_name="nginx:latest",
)

railway = RailwayResources(
    name="my-deployment",
    apps=[app],
    workspace_id="your-workspace-id-here",  # Explicit workspace
)
railway.create_resources()
```

**Example with environment variable:**

```bash
export RAILWAY_API_TOKEN="your-token-here"
export RAILWAY_WORKSPACE_ID="your-workspace-id-here"
python deploy.py
```

### API Token Priority

The Railway API token is resolved in the following priority order:

1. Explicitly provided in code (`api_token` parameter)
2. Set in infra settings
3. `RAILWAY_API_TOKEN` environment variable

### Rate Limiting

Railway enforces the following rate limits:

- **Project Creation**: Maximum 1 project per 30 seconds per user
  - The provider automatically handles this by waiting when necessary
  - You'll see a log message: "Railway rate limit: waiting Xs..."

- **General API**: Automatic retry with exponential backoff on rate limit errors

## API Reference

### RailwayResources

Main orchestrator for Railway infrastructure.

**Constructor Parameters:**
- `name` (str, required): Deployment name
- `apps` (List[RailwayApp], optional): List of apps to deploy
- `workspace_id` (str, optional): Railway workspace/team ID
  - Priority: explicit parameter → infra settings → RAILWAY_WORKSPACE_ID env var → auto-detected
- `api_token` (str, optional): Railway API token
  - Priority: explicit parameter → infra settings → RAILWAY_API_TOKEN env var

#### `create_resources()`
Create Railway resources with dependency resolution.

**Parameters:**
- `group_filter` (str, optional): Filter by group
- `name_filter` (str, optional): Filter by name
- `type_filter` (str, optional): Filter by resource type
- `dry_run` (bool, optional): Preview without creating
- `auto_confirm` (bool, optional): Skip confirmation prompt
- `force` (bool, optional): Force recreation of existing resources

**Returns:** `Tuple[int, int]` - (number_created, total_number)

#### `delete_resources()`
Delete Railway resources in reverse dependency order.

**Parameters:** Same as `create_resources()` (except no `force`)

**Returns:** `Tuple[int, int]` - (number_deleted, total_number)

#### `update_resources()`
Update Railway resources (typically via redeployment).

**Note:** Railway handles many updates automatically. For significant changes, use `create_resources(force=True)`.

### RailwayApp Properties

- `name` (str, required): Application name
- `image_name` (str): Docker image name
- `image_tag` (str): Docker image tag (default: "latest")
- `open_port` (bool): Whether to expose a port
- `port_number` (int): Port number to expose
- `railway_environment` (str): Environment name (default: "production")
- `railway_project_id` (str, optional): Existing project ID to use instead of creating new
- `service_icon` (str, optional): Emoji or URL for service icon
- `env_vars` (dict): Environment variables

## Troubleshooting

### Authentication Errors

If you see "Authentication failed. Check your Railway API token":

1. Verify your token is set correctly:
   ```bash
   echo $RAILWAY_API_TOKEN
   ```

2. Generate a new token at [railway.app/account/tokens](https://railway.app/account/tokens)

3. Ensure the token has the correct permissions (use an Account token for full access)

### Workspace Errors

If you see "You must specify a workspaceId to create a project":

1. Set your workspace ID explicitly:
   ```bash
   export RAILWAY_WORKSPACE_ID="your-workspace-id"
   ```

2. Or let it auto-detect (requires API token with workspace access):
   ```python
   railway = RailwayResources(
       name="my-deployment",
       apps=[app],
       # workspace_id will be auto-detected from your Railway account
   )
   ```

3. Find your workspace ID:
   - Log into Railway Dashboard
   - Click on your team/workspace name
   - Check URL: `https://railway.app/team/{WORKSPACE_ID}`

If auto-detection fails, you'll see a warning and need to set it explicitly.

### Rate Limiting

Railway has API rate limits:
- **General API**: Free tier: 100 requests/hour; Hobby: 1,000 requests/hour, 10/second; Pro: 10,000 requests/hour, 50/second
- **Project Creation**: Maximum 1 project per 30 seconds per user (automatically handled)

The Railway provider implements automatic handling:
- Exponential backoff retry for general rate limits
- Automatic wait for project creation rate limits
- You'll see: "Railway rate limit: waiting Xs..." when this occurs

### Resource Already Exists

If resources already exist, Railway will return the existing resource. To force recreation:

```python
railway.create_resources(force=True)
```

## What's Next?

### Phase 2: Database Support (Coming Soon)

```python
from agno.railway.app.postgres import Postgres

db = Postgres(name="mydb")
app = FastApi(
    name="api",
    env_vars={"DATABASE_URL": "{{postgres.connection_string}}"}
)

railway = RailwayResources(apps=[db, app])
```

### Phase 3: Advanced Features (Future)

- GitHub repository deployments
- Persistent volumes
- Custom domains
- Deployment status tracking
- Multi-service dependencies

## Contributing

The Railway provider is part of the Agno project. Contributions are welcome!

## License

Apache License 2.0 - See LICENSE file for details

## Resources

- [Railway Documentation](https://docs.railway.com)
- [Railway GraphQL API](https://docs.railway.com/reference/public-api)
- [Agno Documentation](https://docs.agno.com)
- [Example Deployments](../../cookbook/railway/)
