# Microsoft 365 Copilot Interface

Examples of exposing Agno agents to Microsoft 365 Copilot and Copilot Studio using the M365Copilot interface.

## Overview

The M365Copilot interface enables Microsoft 365 Copilot to invoke Agno agents, teams, and workflows as specialized sub-agents. This allows you to:

- **Expose Agno agents as plugins** in Microsoft Copilot Studio
- **Delegate specialized tasks** from Microsoft 365 Copilot to your Agno agents
- **Use Microsoft Entra ID** for secure authentication
- **Generate OpenAPI specifications** for easy plugin registration

## Architecture

```
Microsoft 365 Copilot
        │
        │ HTTP (via M365 Interface)
        ▼
┌─────────────────────────────────┐
│         AgentOS                 │
│  ┌─────────────────────────────┐│
│  │  M365Copilot Interface     ││
│  │  - OpenAPI spec generation  ││
│  │  - JWT validation           ││
│  │  - Agent invocation         ││
│  └─────────────────────────────┘│
│                                 │
│  ┌─────────────────────────────┐│
│  │  Agno Agents               ││
│  └─────────────────────────────┘│
└─────────────────────────────────┘
```

## Configuration

### Environment Variables

```bash
# Required
export M365_TENANT_ID="your-tenant-id-here"
export M365_CLIENT_ID="your-client-id-here"

# Optional
export M365_AUDIENCE="api://agno"  # Default: "api://agno"
```

### Microsoft Entra ID Setup

1. **Register an application** in Microsoft Entra ID
2. **Get your tenant ID** and **client ID**
3. **Configure API permissions** if needed
4. **Set environment variables** with your credentials

## Examples

### Basic Agent

See [basic.py](basic.py) for a minimal example of exposing an agent to Microsoft 365 Copilot.

```python
from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.agent import Agent

agent = Agent(
    agent_id="financial-analyst",
    name="Financial Analyst",
    instructions="Analyze financial data..."
)

os = AgentOS(
    agents=[agent],
    interfaces=[M365Copilot(agent=agent)]
)

os.run()
```

### Multiple Agents

```python
from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.agent import Agent

# Create multiple specialized agents
financial_agent = Agent(
    agent_id="financial-analyst",
    name="Financial Analyst",
    instructions="..."
)

research_agent = Agent(
    agent_id="research-team",
    name="Research Team",
    instructions="..."
)

# Expose via M365 interface
os = AgentOS(
    agents=[financial_agent, research_agent],
    interfaces=[
        M365Copilot(
            agent=financial_agent,  # Primary agent
            agent_descriptions={
                "financial-analyst": "Financial analysis expert",
                "research-team": "Market research and intelligence"
            }
        )
    ]
)
```

### Team Interface

```python
from agno.os import AgentOS
from agno.os.interfaces.m365 import M365Copilot
from agno.team import Team

team = Team(
    team_id="research-team",
    name="Research Team",
    members=[...]
)

os = AgentOS(
    teams=[team],
    interfaces=[M365Copilot(team=team)]
)
```

## Endpoints

### GET /m365/manifest

Returns the OpenAPI specification for plugin registration.

```bash
curl http://localhost:7777/m365/manifest
```

### GET /m365/agents

Lists all available agents (requires authentication).

```bash
curl -H "Authorization: Bearer <token>" \\
     http://localhost:7777/m365/agents
```

### POST /m365/invoke/{component_id}

Invokes an agent (requires authentication).

```bash
curl -X POST \\
     -H "Authorization: Bearer <token>" \\
     -H "Content-Type: application/json" \\
     -d '{"message": "Analyze Q3 revenue"}' \\
     http://localhost:7777/m365/invoke/financial-analyst
```

### GET /m365/health

Health check endpoint.

```bash
curl http://localhost:7777/m365/health
```

## Registering in Copilot Studio

1. **Get the OpenAPI specification**:
   ```bash
   curl http://localhost:7777/m365/manifest
   ```

2. **Open Copilot Studio** (https://copilotstudio.microsoft.com)

3. **Create a new plugin**:
   - Choose "API plugin"
   - Paste the OpenAPI specification
   - Configure authentication (Bearer token, Microsoft Entra ID)

4. **Add to Microsoft 365 Copilot**:
   - Publish the plugin
   - Add to your Copilot instance

## Testing

### Manual Testing

```bash
# 1. Get manifest (no auth required)
curl http://localhost:7777/m365/manifest

# 2. Get health (no auth required)
curl http://localhost:7777/m365/health

# 3. List agents (requires valid JWT token)
curl -H "Authorization: Bearer <your-jwt-token>" \\
     http://localhost:7777/m365/agents

# 4. Invoke agent (requires valid JWT token)
curl -X POST \\
     -H "Authorization: Bearer <your-jwt-token>" \\
     -H "Content-Type: application/json" \\
     -d '{"message": "Analyze Q3 revenue trends"}' \\
     http://localhost:7777/m365/invoke/financial-analyst
```

### Testing with Microsoft Entra ID

1. **Get a test token** from Microsoft Entra ID
2. **Use the token** in Authorization header
3. **Verify agent invocation** works correctly

## Security

### Authentication

The M365Copilot interface validates Microsoft Entra ID JWT tokens on every request to protected endpoints:
- `/m365/agents` - Lists available agents
- `/m365/invoke` - Invokes agents

### Authorization

Currently, all authenticated users can access all components. Implement custom authorization by modifying `validate_token_for_component()` in `auth.py`.

### Best Practices

- **Use HTTPS** in production
- **Validate tokens** on every request
- **Implement rate limiting** for production deployments
- **Monitor usage** and log suspicious activity
- **Use least privilege** for API permissions

## Troubleshooting

### "tenant_id is required"

Set the `M365_TENANT_ID` environment variable:
```bash
export M365_TENANT_ID="your-tenant-id"
```

### "client_id is required"

Set the `M365_CLIENT_ID` environment variable:
```bash
export M365_CLIENT_ID="your-client-id"
```

### "Component not found"

Verify the agent ID in the URL matches the agent's `agent_id`:
```python
agent = Agent(agent_id="my-agent")  # Use this ID in URLs
```

### Token validation fails

Ensure:
- Token is from the correct tenant (`M365_TENANT_ID`)
- Token has the correct audience (`M365_CLIENT_ID`)
- Token is not expired
