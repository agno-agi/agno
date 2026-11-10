"""
Example demonstrating background streaming with disconnect and resume.

Background streaming runs (background=True, stream=True) survive client
disconnections: the run keeps executing and buffering events in the event
stream, and a client can reconnect later and replay everything it missed, then
keep tailing live events.

This example simulates that flow at the library level:
1. Start a background streaming run and consume only the first few events
   (then "disconnect").
2. Reconnect: replay missed events from the event stream by index, then tail
   live events until the run completes.

The event stream is pluggable (same pattern as run cancellation management).
The default is in-memory (single process). For multi-container deployments,
configure Redis Streams so clients can resume from ANY replica:

    from agno.os import AgentOS, QueueConfig

    agent_os = AgentOS(
        agents=[agent],
        queue=QueueConfig(redis="redis://localhost:6379"),
    )

Requirements:
- OPENAI_API_KEY set

Usage:
    .venvs/demo/bin/python cookbook/02_agents/14_advanced/background_streaming_resume.py
"""

import asyncio

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.os.event_streams import get_event_stream

agent = Agent(
    name="ResumableStreamAgent",
    model=OpenAIResponses(id="gpt-5.5"),
    description="An agent whose background stream can be resumed after a disconnect",
    db=InMemoryDb(),
)


async def main():
    # 1. Start a background streaming run. Events arrive as SSE-formatted
    # strings; the run itself executes in a detached task that survives the
    # consumer going away.
    stream = agent.arun(
        "Write a six-line poem about reliable systems, one line at a time.",
        background=True,
        stream=True,
        session_id="resume-demo",
    )

    run_id = None
    consumed = 0
    async for sse_chunk in stream:
        if run_id is None and '"run_id"' in sse_chunk:
            # Each SSE payload carries the run_id and an event_index
            import json as _json

            data_line = next(
                line for line in sse_chunk.splitlines() if line.startswith("data: ")
            )
            payload = _json.loads(data_line[len("data: ") :])
            run_id = payload.get("run_id")
        consumed += 1
        if consumed >= 3:
            print(
                f"Consumed {consumed} events, disconnecting (run continues in background)"
            )
            break

    assert run_id is not None, "run_id not seen in the first events"

    # Simulate time passing while disconnected - the run keeps producing
    await asyncio.sleep(2)

    # 2. Reconnect: replay everything after the last event we saw, then tail
    # live events until the run reaches a terminal state. This is exactly what
    # the AgentOS /runs/{run_id}/resume endpoint does for HTTP clients.
    event_stream = get_event_stream()
    last_seen_index = consumed - 1

    print(f"\nResuming run {run_id} from event index {last_seen_index}...")
    replayed = await event_stream.replay(run_id, last_event_index=last_seen_index)
    print(f"Replayed {len(replayed)} missed events")

    live = 0
    async for event_index, _sse_data in event_stream.tail(
        run_id, last_event_index=last_seen_index
    ):
        live += 1
    print(f"Tailed events up to index {event_index}; stream ended with the run")

    status = await event_stream.get_run_status(run_id)
    print(f"\nFinal run status: {status}")
    result = await agent.aget_run_output(run_id=run_id, session_id="resume-demo")
    print(f"Final content:\n{result.content}")


if __name__ == "__main__":
    asyncio.run(main())
