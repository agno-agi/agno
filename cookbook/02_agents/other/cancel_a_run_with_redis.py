"""
Example demonstrating how to cancel a running agent execution using Redis.

This example shows how to:
1. Set up a Redis-based cancellation manager for distributed environments
2. Start an agent run in a separate thread
3. Cancel the run from another thread (or another process/service)
4. Handle the cancelled response

The Redis cancellation manager is useful when:
- You have multiple processes/services that need to cancel runs
- You're running agents in a distributed environment (e.g., multiple workers)
- You need cancellation state to persist across process restarts

Requirements:
    pip install redis

Usage:
    # Start Redis first (using Docker):
    docker run -d --name redis -p 6379:6379 redis:latest

    # Run the example:
    python cancel_a_run_with_redis.py
"""

import threading
import time

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunEvent
from agno.run.base import RunStatus
from agno.run.cancel import set_cancellation_manager
from agno.run.cancellation_management import RedisRunCancellationManager
from redis import Redis


def setup_redis_cancellation_manager():
    """
    Set up a Redis-based cancellation manager.

    This enables distributed run cancellation across multiple processes.
    """
    # Create Redis client
    redis_client = Redis(
        host="localhost",
        port=6379,
        db=0,
        decode_responses=False,  # Keep as bytes for compatibility
    )

    # Test connection
    redis_client.ping()
    print("Connected to Redis successfully")

    # Create and set the Redis cancellation manager
    redis_manager = RedisRunCancellationManager(
        redis_client=redis_client,
        key_prefix="agno:run:cancellation:",  # Optional: customize key prefix
        ttl_seconds=3600,  # Keys expire after 1 hour (prevents orphaned keys)
    )

    # Set as the global cancellation manager
    set_cancellation_manager(redis_manager)

    print("Redis cancellation manager configured")
    return redis_client


def long_running_task(agent: Agent, run_id_container: dict):
    """
    Simulate a long-running agent task that can be cancelled.

    Args:
        agent: The agent to run
        run_id_container: Dictionary to store the run_id for cancellation

    Returns:
        Dictionary with run results and status
    """
    try:
        # Start the agent run - this simulates a long task
        final_response = None
        content_pieces = []

        for chunk in agent.run(
            "Write a very long story about a dragon who learns to code. "
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
            # When the run is cancelled, a `RunEvent.run_cancelled` event is emitted
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
                final_response = chunk

        # If we get here, the run completed successfully
        if final_response:
            run_id_container["result"] = {
                "status": final_response.status.value
                if final_response.status
                else "completed",
                "run_id": final_response.run_id,
                "cancelled": final_response.status == RunStatus.cancelled,
                "content": ("".join(content_pieces)[:200] + "...")
                if content_pieces
                else "No content",
            }
        else:
            run_id_container["result"] = {
                "status": "unknown",
                "run_id": run_id_container.get("run_id"),
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


def cancel_after_delay(agent: Agent, run_id_container: dict, delay_seconds: int = 5):
    """
    Cancel the agent run after a specified delay.

    In a real distributed scenario, this cancellation could come from:
    - A different process
    - A different service
    - An API endpoint
    - A monitoring system

    Args:
        agent: The agent whose run should be cancelled
        run_id_container: Dictionary containing the run_id to cancel
        delay_seconds: How long to wait before cancelling
    """
    print(f"Will cancel run in {delay_seconds} seconds...")
    time.sleep(delay_seconds)

    run_id = run_id_container.get("run_id")
    if run_id:
        print(f"\nCancelling run: {run_id}")
        # This uses the Redis manager under the hood
        success = agent.cancel_run(run_id)
        if success:
            print(f"Run {run_id} marked for cancellation in Redis")
        else:
            print(f"Failed to cancel run {run_id} (may not exist or already completed)")
    else:
        print("No run_id found to cancel")


def main():
    """Main function demonstrating Redis-based run cancellation."""

    # Step 1: Set up Redis cancellation manager
    print("Setting up Redis cancellation manager...")
    print("=" * 50)

    try:
        redis_client = setup_redis_cancellation_manager()
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")
        print("\nMake sure Redis is running:")
        print("  docker run -d --name redis -p 6379:6379 redis:latest")
        return

    # Step 2: Initialize the agent with a model
    agent = Agent(
        name="StorytellerAgent",
        model=OpenAIChat(id="gpt-4o-mini"),
        description="An agent that writes detailed stories",
    )

    print("\nStarting agent run cancellation example with Redis...")
    print("=" * 50)

    # Container to share run_id between threads
    run_id_container = {}

    # Start the agent run in a separate thread
    agent_thread = threading.Thread(
        target=lambda: long_running_task(agent, run_id_container),
        name="AgentRunThread",
    )

    # Start the cancellation thread
    cancel_thread = threading.Thread(
        target=cancel_after_delay,
        args=(agent, run_id_container, 5),  # Cancel after 5 seconds
        name="CancelThread",
    )

    # Start both threads
    print("Starting agent run thread...")
    agent_thread.start()

    print("Starting cancellation thread...")
    cancel_thread.start()

    # Wait for both threads to complete
    print("Waiting for threads to complete...")
    agent_thread.join()
    cancel_thread.join()

    # Print the results
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
            print("\nSUCCESS: Run was successfully cancelled via Redis!")
        else:
            print("\nWARNING: Run completed before cancellation")
    else:
        print("No result obtained - check if cancellation happened during streaming")

    # Cleanup: Close Redis connection
    redis_client.close()

    print("\nExample completed!")


if __name__ == "__main__":
    main()
