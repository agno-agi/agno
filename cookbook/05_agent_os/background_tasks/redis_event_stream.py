"""AgentOS with a Redis event stream for multi-container streaming resume.

By default, background streaming runs (background=True, stream=True) buffer
their events in process memory: a client that reconnects to /resume through a
load balancer and lands on a different replica cannot see them. Configuring a
Redis-backed event stream makes events readable from every replica, so a
background stream can be resumed from any container.

Run several replicas of this app behind a load balancer to see it work: start
a background streaming run against one replica, then hit
GET /agents/{agent_id}/runs/{run_id}/resume on another - the events replay and
tail from Redis regardless of which replica executes the run.

Cross-container cancellation (RedisRunCancellationManager) and the event stream
share the same Redis: one carries client intent to the executing container, the
other carries events back out. Configure both together.

Requirements:
- Redis running (./cookbook/scripts/run_redis.sh)
- OPENAI_API_KEY set
- pip install redis
"""

from agno.agent import Agent
from agno.db.redis import RedisDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.event_streams import RedisEventStream
from agno.run.cancel import set_cancellation_manager
from agno.run.cancellation_management.redis_cancellation_manager import (
    RedisRunCancellationManager,
)
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

REDIS_URL = "redis://localhost:6379"

# One Redis serves storage, cancellation and the event stream in this example
db = RedisDb(db_url=REDIS_URL)
async_redis = AsyncRedis.from_url(REDIS_URL)
sync_redis = Redis.from_url(REDIS_URL)

# Cross-container cancellation: a cancel request received by any replica
# reaches the replica executing the run
set_cancellation_manager(
    RedisRunCancellationManager(redis_client=sync_redis, async_redis_client=async_redis)
)

agent = Agent(
    name="Resumable Stream Agent",
    id="resumable-stream-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    description="An agent whose background streams can be resumed from any replica",
    db=db,
)

agent_os = AgentOS(
    description="AgentOS with cross-container streaming resume",
    agents=[agent],
    event_stream=RedisEventStream(async_redis),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="redis_event_stream:app", reload=True)
