"""
Example demonstrating cross-process streaming resume with RedisEventStream.

With the default in-memory event stream, a background streaming run can only be
resumed from the process that is executing it. Backed by Redis Streams, the
events become location-independent: ANY process (e.g. another AgentOS replica
behind a load balancer) can replay missed events and tail live ones.

This example simulates two containers in one script:
1. The "producer" process starts a background streaming run with a Redis-backed
   event stream, consumes a few events, then disconnects.
2. An "observer" - a separate RedisEventStream instance with its own Redis
   client, sharing nothing with the producer except Redis - resumes the run:
   replays what was missed and tails live events to completion.

Requirements:
- Redis running (./cookbook/scripts/run_redis.sh)
- OPENAI_API_KEY set
- pip install redis

Usage:
    .venvs/demo/bin/python cookbook/02_agents/14_advanced/redis_event_stream_resume.py
"""

import asyncio
import json

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.os.event_streams import RedisEventStream, set_event_stream
from redis.asyncio import Redis as AsyncRedis

REDIS_URL = "redis://localhost:6379"

agent = Agent(
    name="CrossProcessStreamAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    description="An agent whose background stream is observable from any process",
    db=InMemoryDb(),
)


def extract_run_id(sse_chunk: str) -> str:
    data_line = next(
        line for line in sse_chunk.splitlines() if line.startswith("data: ")
    )
    return json.loads(data_line[len("data: ") :]).get("run_id")


async def main():
    # 1. The "producer" process: configure the Redis-backed event stream, then
    # start a background streaming run. The producer XADDs every event to a
    # per-run Redis stream instead of an in-process buffer.
    producer_client = AsyncRedis.from_url(REDIS_URL)
    set_event_stream(RedisEventStream(producer_client))

    stream = agent.arun(
        "Write a six-line poem about distributed systems, one line at a time.",
        background=True,
        stream=True,
        session_id="redis-resume-demo",
    )

    run_id = None
    consumed = 0
    async for sse_chunk in stream:
        if run_id is None and '"run_id"' in sse_chunk:
            run_id = extract_run_id(sse_chunk)
        consumed += 1
        if consumed >= 3:
            print(
                f"Producer consumed {consumed} events, client disconnects (run continues)"
            )
            break

    assert run_id is not None, "run_id not seen in the first events"

    # 2. The "observer" process: a separate RedisEventStream with its own
    # client. In production this is a different container - it never talks to
    # the producer, only to Redis. This is exactly what the AgentOS
    # /runs/{run_id}/resume endpoint does on whichever replica receives the
    # reconnect.
    observer = RedisEventStream(AsyncRedis.from_url(REDIS_URL))
    last_seen_index = consumed - 1

    print(f"\nObserver resuming run {run_id} from event index {last_seen_index}...")
    replayed = await observer.replay(run_id, last_event_index=last_seen_index)
    print(f"Observer replayed {len(replayed)} missed events")

    final_index = last_seen_index
    async for event_index, _sse_data in observer.tail(
        run_id, last_event_index=last_seen_index
    ):
        final_index = event_index
    print(f"Observer tailed live events up to index {final_index}; run finished")

    status = await observer.get_run_status(run_id)
    print(f"\nFinal run status seen by the observer: {status}")

    result = await agent.aget_run_output(run_id=run_id, session_id="redis-resume-demo")
    print(f"Final content:\n{result.content}")


if __name__ == "__main__":
    asyncio.run(main())
