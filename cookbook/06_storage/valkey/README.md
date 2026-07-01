# Valkey Integration

Examples demonstrating Valkey integration with Agno agents, teams, and workflows.

## Setup

These configurations and examples will use Valkey GLIDE. 

```shell
uv pip install valkey-glide-sync

# Start Valkey container
docker run --name my-valkey -p 6379:6379 -d valkey/valkey-bundle
```

## Configuration

```python
from agno.agent import Agent
from agno.db.valkey import ValkeyDb

db = ValkeyDb(host="localhost", port=6379)

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Examples

- [`valkey_for_agent.py`](valkey_for_agent.py) - Agent with Valkey storage
- [`valkey_for_team.py`](valkey_for_team.py) - Team with Valkey storage
- [`valkey_for_workflow.py`](valkey_for_workflow.py) - Workflow with Valkey storage
