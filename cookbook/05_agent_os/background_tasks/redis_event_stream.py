"""AgentOS with Redis-coordinated background runs (multi-container ready).

QueueConfig is the single place to configure background run execution:
- max_concurrency: how many background runs execute at once per replica
  (the rest wait in line as PENDING)
- redis: one setting that enables BOTH cross-container transports, built from
  shared clients: distributed cancellation (a cancel received by any replica
  reaches the one executing the run) and the Redis event stream (a background
  stream can be replayed and resumed from any replica)

Run several replicas of this app behind a load balancer to see it work: start
a background streaming run against one replica, then hit
POST /agents/{agent_id}/runs/{run_id}/resume on another - events replay and
tail from Redis regardless of which replica executes the run.

Granular overrides remain available for advanced setups: pass
AgentOS(event_stream=...) or call set_cancellation_manager() explicitly and
the queue.redis wiring will not replace them.

Requirements:
- Redis running (./cookbook/scripts/run_redis.sh)
- OPENAI_API_KEY set
- pip install redis
"""

from agno.agent import Agent
from agno.db.redis import RedisDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, QueueConfig

REDIS_URL = "redis://localhost:6379"

# One Redis serves storage and run coordination in this example
db = RedisDb(db_url=REDIS_URL)

agent = Agent(
    name="Resumable Stream Agent",
    id="resumable-stream-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    description="An agent whose background streams can be resumed from any replica",
    db=db,
)

agent_os = AgentOS(
    description="AgentOS with cross-container background run coordination",
    agents=[agent],
    queue=QueueConfig(
        max_concurrency=16,
        redis=REDIS_URL,
    ),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="redis_event_stream:app", reload=True)
