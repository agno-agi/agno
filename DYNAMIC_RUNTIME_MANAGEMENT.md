# Dynamic Runtime Management for AgentOS

This document describes the new dynamic runtime management feature that allows adding and removing agents, teams, and workflows to a running AgentOS instance without requiring a restart.

## Overview

The dynamic runtime management feature addresses the need for:
- Adding new capabilities without service interruption
- Supporting plugin-like functionality
- Enabling multi-tenant scenarios with user-generated agents/workflows
- Hot-swapping components for development and testing

## Features

### ✅ Implemented Features

- **Thread-Safe Operations**: All runtime operations use locks to ensure thread safety
- **Automatic Initialization**: Newly added components are fully initialized with proper MCP tool tracking
- **Database Auto-Discovery**: Databases and knowledge instances are automatically discovered when components are added
- **Route Refresh**: Routes are automatically updated when components are added or removed
- **Duplicate Prevention**: Prevents adding components with duplicate IDs
- **Statistics Tracking**: Real-time statistics about all components
- **Comprehensive API**: RESTful endpoints for all runtime operations

### 🔧 Core Methods

#### AgentOS Class Methods

```python
# Add components
agent_os.add_agent(agent: Agent) -> bool
agent_os.add_team(team: Team) -> bool
agent_os.add_workflow(workflow: Workflow) -> bool

# Remove components
agent_os.remove_agent(agent_id: str) -> bool
agent_os.remove_team(team_id: str) -> bool
agent_os.remove_workflow(workflow_id: str) -> bool

# Utility methods
agent_os.refresh_routes() -> bool
agent_os.get_runtime_stats() -> Dict[str, Any]
```

### 🌐 API Endpoints

All endpoints require authentication if `os_security_key` is configured.

#### Add Components
- `POST /runtime/agents` - Add a new agent
- `POST /runtime/teams` - Add a new team  
- `POST /runtime/workflows` - Add a new workflow

#### Remove Components
- `DELETE /runtime/agents/{agent_id}` - Remove an agent
- `DELETE /runtime/teams/{team_id}` - Remove a team
- `DELETE /runtime/workflows/{workflow_id}` - Remove a workflow

#### Utility Endpoints
- `POST /runtime/refresh` - Manually refresh routes
- `GET /runtime/stats` - Get runtime statistics

## Usage Examples

### Basic Python Usage

```python
from agno.agent.agent import Agent
from agno.os.app import AgentOS

# Create AgentOS with initial components
agent_os = AgentOS(
    name="Dynamic OS",
    agents=[initial_agent],
)

# Add new agent at runtime
new_agent = Agent(id="dynamic-agent", name="Dynamic Agent")
success = agent_os.add_agent(new_agent)

# Check statistics
stats = agent_os.get_runtime_stats()
print(f"Total agents: {stats['agents']['count']}")

# Remove agent
removed = agent_os.remove_agent("dynamic-agent")
```

### API Usage

```python
import httpx
import json

async def add_agent_via_api():
    agent_config = {
        "id": "api-agent",
        "name": "API Agent",
        "description": "Agent added via API"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:7777/runtime/agents",
            data={"agent_config": json.dumps(agent_config)}
        )
        return response.json()
```

### cURL Examples

```bash
# Add an agent
curl -X POST "http://localhost:7777/runtime/agents" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'agent_config={"id": "curl-agent", "name": "Curl Agent"}'

# Get runtime statistics
curl -X GET "http://localhost:7777/runtime/stats"

# Remove an agent
curl -X DELETE "http://localhost:7777/runtime/agents/curl-agent"

# Refresh routes
curl -X POST "http://localhost:7777/runtime/refresh"
```

## Technical Details

### Thread Safety

All runtime operations use a `threading.Lock` to ensure thread-safe access to the component lists and internal state. This prevents race conditions when multiple operations occur simultaneously.

```python
with self._runtime_lock:
    # All critical operations happen here
    self.agents.append(new_agent)
    self._auto_discover_databases()
    self._refresh_routers()
```

### Component Initialization

When components are added dynamically, they undergo the same initialization process as during startup:

- **Agents**: `initialize_agent()` called, event storage enabled, MCP tools tracked
- **Teams**: `initialize_team()` called, member agents initialized, MCP tools tracked
- **Workflows**: ID generation if needed, database discovery

### Route Management

Routes are automatically refreshed when components are added or removed. Due to FastAPI limitations, the current implementation rebuilds the router configuration rather than dynamically adding/removing individual routes.

### MCP Tool Handling

MCP (Model Context Protocol) tools are automatically tracked when adding agents and teams. This ensures proper connection lifecycle management for tools that require it.

## Limitations and Considerations

### Current Limitations

1. **Route Rebuilding**: FastAPI doesn't support dynamic route removal, so we rebuild router configurations
2. **Session Persistence**: Existing sessions for removed components may become invalid
3. **Configuration Complexity**: The API currently accepts simplified configurations - extend as needed
4. **Memory Usage**: Removed components may not be immediately garbage collected if references exist

### Performance Considerations

- Adding/removing components requires acquiring a lock, which may briefly block other operations
- Route refreshing rebuilds router configurations, which has some overhead
- Database auto-discovery scans all components when changes are made

### Security Considerations

- All runtime management endpoints respect the AgentOS authentication system
- Component configurations should be validated before creation
- Consider rate limiting for production deployments
- Audit logging recommended for component changes

## Best Practices

### Development

1. **Test Thread Safety**: Use the provided thread safety demonstration
2. **Validate Configurations**: Always validate component configurations before adding
3. **Monitor Statistics**: Use the stats endpoint to monitor system state
4. **Handle Errors Gracefully**: Check return values and handle failures appropriately

### Production

1. **Authentication Required**: Always enable `os_security_key` for production deployments
2. **Rate Limiting**: Implement rate limiting for runtime management endpoints
3. **Audit Logging**: Log all component additions and removals
4. **Resource Monitoring**: Monitor memory and performance impact of dynamic operations
5. **Backup Configurations**: Maintain backups of component configurations

### Error Handling

```python
# Always check return values
if not agent_os.add_agent(new_agent):
    print(f"Failed to add agent - duplicate ID: {new_agent.id}")

# Handle API errors
try:
    response = await client.post("/runtime/agents", data=config)
    response.raise_for_status()
except httpx.HTTPStatusError as e:
    print(f"API error: {e.response.status_code} {e.response.text}")
```

## Migration Guide

### From Static to Dynamic

If you currently initialize all components during AgentOS creation, you can migrate to dynamic management:

```python
# Before
agent_os = AgentOS(
    agents=[agent1, agent2, agent3],
    teams=[team1, team2],
    workflows=[workflow1, workflow2]
)

# After - start with minimal setup
agent_os = AgentOS(
    agents=[agent1],  # Keep essential agents
)

# Add others dynamically
agent_os.add_agent(agent2)
agent_os.add_agent(agent3)
agent_os.add_team(team1)
agent_os.add_team(team2)
agent_os.add_workflow(workflow1)
agent_os.add_workflow(workflow2)
```

## Contributing

When extending this feature:

1. Maintain thread safety for all operations
2. Update both Python methods and API endpoints
3. Add appropriate validation and error handling
4. Update documentation and examples
5. Consider backward compatibility

## Future Enhancements

Potential future improvements:

- [ ] Component hot-reloading with configuration updates
- [ ] Bulk operations for adding multiple components
- [ ] Component dependency management
- [ ] Advanced routing strategies
- [ ] Event hooks for component lifecycle
- [ ] Component templating system
- [ ] Configuration validation schemas
- [ ] Component rollback capabilities

## Troubleshooting

### Common Issues

**Q: Added component doesn't appear in routes**
A: Try calling `agent_os.refresh_routes()` manually or use the `/runtime/refresh` endpoint.

**Q: Getting duplicate ID errors**
A: Check existing components with `agent_os.get_runtime_stats()` before adding new ones.

**Q: Thread safety concerns**
A: All operations are automatically thread-safe. Use the thread safety demo to verify behavior.

**Q: Memory usage growing**
A: Ensure proper cleanup by removing unused components and checking for lingering references.

### Debug Information

Enable debug logging to see detailed information about runtime operations:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Support

For issues, questions, or feature requests related to dynamic runtime management:

1. Check the examples in `examples/dynamic_runtime_management.py`
2. Review the API documentation at `/docs` when running AgentOS
3. Submit issues to the AgentOS GitHub repository
4. Join the AgentOS community discussions

---

*This feature was implemented to address [GitHub Issue #4584](https://github.com/agno-agi/agno/issues/4584)*
