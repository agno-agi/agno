# Async Redis Integration

Examples demonstrating asynchronous Redis integration with Agno agents, teams, and workflows.

`AsyncRedisDb` uses `redis.asyncio` under the hood and is the right choice when calling agents,
teams, or workflows via their async APIs (`arun`, `aprint_response`). The sync `RedisDb` blocks
the event loop and should not be used from async code.

## Setup

```shell
uv pip install redis

# Start Redis container
docker run --name my-redis -p 6379:6379 -d redis
```

## Configuration

```python
from agno.agent import Agent
from agno.db.redis import AsyncRedisDb

db = AsyncRedisDb(db_url="redis://localhost:6379")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

For Redis Cluster, pass a pre-configured `redis.asyncio.RedisCluster` client via `redis_client=`.

## Examples

- [`async_redis_for_agent.py`](async_redis_for_agent.py) - Agent with AsyncRedisDb storage
- [`async_redis_for_team.py`](async_redis_for_team.py) - Team with AsyncRedisDb storage
- [`async_redis_for_workflow.py`](async_redis_for_workflow.py) - Workflow with AsyncRedisDb storage
