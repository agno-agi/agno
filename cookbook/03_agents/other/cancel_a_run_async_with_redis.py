"""
Example demonstrating how to cancel an async agent run using Redis.

This example shows how to:
1. Set up a Redis-based cancellation manager with async support
2. Start an async agent run
3. Cancel the run from a concurrent task
4. Handle the cancelled response

The async Redis cancellation manager is useful when:
- You're using async/await patterns throughout your application
- You want non-blocking Redis operations
- You're running in an async web framework (FastAPI, Starlette, etc.)

Requirements:
    pip install redis

Usage:
    # Start Redis first (using Docker):
    docker run -d --name redis -p 6379:6379 redis:latest

    # Run the example:
    python cancel_a_run_async_with_redis.py
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunEvent
from agno.run.base import RunStatus
from agno.run.cancel import set_cancellation_manager
from agno.run.cancellation_management import RedisRunCancellationManager
from redis.asyncio import Redis as AsyncRedis


async def setup_async_redis_cancellation_manager():
    """
    Set up an async Redis-based cancellation manager.

    This enables distributed run cancellation with non-blocking Redis operations.
    """
    # Create async Redis client
    async_redis_client = AsyncRedis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=False,
    )

    # Test connection
    await async_redis_client.ping()

    # Create and set the Redis cancellation manager with async client
    redis_manager = RedisRunCancellationManager(
        async_redis_client=async_redis_client,
        key_prefix="agno:run:cancellation:",
        ttl_seconds=3600,
    )

    # Set as the global cancellation manager
    set_cancellation_manager(redis_manager)

    print("Async Redis cancellation manager configured")
    return async_redis_client


async def run_agent_task(agent: Agent, run_id_container: dict):
    """
    Run the agent asynchronously and stream the response.

    Args:
        agent: The agent to run
        run_id_container: Dictionary to store the run_id for cancellation
    """
    try:
        content_pieces = []

        async for chunk in agent.arun(
            "Write a very long story about a robot learning to paint. "
            "Make it at least 2000 words with detailed descriptions and dialogue. "
            "Take your time and be very thorough.",
            stream=True,
        ):
            if "run_id" not in run_id_container and chunk.run_id:
                run_id_container["run_id"] = chunk.run_id
                print(f"Run started with ID: {chunk.run_id}")

            if chunk.event == RunEvent.run_content:
                print(chunk.content, end="", flush=True)
                content_pieces.append(chunk.content)
            elif chunk.event == RunEvent.run_cancelled:
                print(f"\nRun was cancelled: {chunk.run_id}")
                run_id_container["result"] = {
                    "status": "cancelled",
                    "run_id": chunk.run_id,
                    "cancelled": True,
                    "content": "".join(content_pieces)[:200] + "..."
                    if content_pieces
                    else "No content before cancellation",
                }
                return
            elif hasattr(chunk, "status") and chunk.status == RunStatus.completed:
                run_id_container["result"] = {
                    "status": "completed",
                    "run_id": chunk.run_id,
                    "cancelled": False,
                    "content": ("".join(content_pieces)[:200] + "...")
                    if content_pieces
                    else "No content",
                }

    except Exception as e:
        print(f"\nException in run: {str(e)}")
        run_id_container["result"] = {
            "status": "error",
            "error": str(e),
            "run_id": run_id_container.get("run_id"),
            "cancelled": True,
            "content": "Error occurred",
        }


async def cancel_after_delay(
    agent: Agent, run_id_container: dict, delay_seconds: int = 5
):
    """
    Cancel the agent run after a specified delay using async operations.

    Args:
        agent: The agent whose run should be cancelled
        run_id_container: Dictionary containing the run_id to cancel
        delay_seconds: How long to wait before cancelling
    """
    print(f"Will cancel run in {delay_seconds} seconds...")
    await asyncio.sleep(delay_seconds)

    run_id = run_id_container.get("run_id")
    if run_id:
        print(f"\nCancelling run: {run_id}")
        # For async cancellation, you can use the module-level async function
        from agno.run.cancel import acancel_run

        success = await acancel_run(run_id)
        if success:
            print(f"Run {run_id} marked for cancellation in Redis (async)")
        else:
            print(f"Failed to cancel run {run_id}")
    else:
        print("No run_id found to cancel")


async def main():
    """Main async function demonstrating async Redis-based run cancellation."""

    print("Setting up async Redis cancellation manager...")
    print("=" * 50)

    try:
        async_redis_client = await setup_async_redis_cancellation_manager()
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")
        print("\nMake sure Redis is running:")
        print("  docker run -d --name redis -p 6379:6379 redis:latest")
        return

    # Initialize the agent
    agent = Agent(
        name="StorytellerAgent",
        model=OpenAIChat(id="gpt-4o-mini"),
        description="An agent that writes detailed stories",
    )

    print("\nStarting async agent run cancellation example...")
    print("=" * 50)

    # Container to share run_id between tasks
    run_id_container = {}

    # Run both tasks concurrently
    agent_task = asyncio.create_task(run_agent_task(agent, run_id_container))
    cancel_task = asyncio.create_task(cancel_after_delay(agent, run_id_container, 5))

    print("Starting agent run and cancellation tasks...")

    # Wait for both tasks
    await asyncio.gather(agent_task, cancel_task, return_exceptions=True)

    # Print results
    print("\n" + "=" * 50)
    print("RESULTS:")
    print("=" * 50)

    result = run_id_container.get("result")
    if result:
        print(f"Status: {result['status']}")
        print(f"Run ID: {result['run_id']}")
        print(f"Was Cancelled: {result['cancelled']}")

        if result.get("error"):
            print(f"Error: {result['error']}")
        else:
            print(f"Content Preview: {result['content']}")

        if result["cancelled"]:
            print("\nSUCCESS: Run was successfully cancelled via async Redis!")
        else:
            print("\nWARNING: Run completed before cancellation")
    else:
        print("No result obtained")

    # Cleanup
    await async_redis_client.aclose()

    print("\nExample completed!")


if __name__ == "__main__":
    asyncio.run(main())
