# Redis Integration

Examples demonstrating Redis integration with Agno agents, teams, and workflows.

## Setup

```shell
pip install redis

# Start Redis container
docker run --name my-redis -p 6379:6379 -d redis
```

## Configuration

```python
from agno.agent import Agent
from agno.db.redis import RedisDb

db = RedisDb(db_url="redis://localhost:6379")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Examples

- [`redis_for_agent.py`](redis_for_agent.py) - Agent with Redis storage
- [`redis_for_team.py`](redis_for_team.py) - Team with Redis storage
- [`redis_for_workflow.py`](redis_for_workflow.py) - Workflow with Redis storage
