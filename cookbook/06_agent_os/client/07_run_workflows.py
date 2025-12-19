"""
Running Workflows with AgentOSClient

This example demonstrates how to execute workflow runs using
AgentOSClient, including both streaming and non-streaming responses.

Prerequisites:
1. Start an AgentOS server with a workflow configured
2. Run this script: python 07_run_workflows.py
"""

import asyncio
import json

from agno.client import AgentOSClient


async def run_workflow_non_streaming():
    """Execute a non-streaming workflow run."""
    print("=" * 60)
    print("Non-Streaming Workflow Run")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    # Get available workflows
    config = await client.aget_config()
    if not config.workflows:
        print("No workflows available")
        return

    workflow_id = config.workflows[0].id
    print(f"Running workflow: {workflow_id}")

    try:
        # Execute the workflow
        result = await client.run_workflow(
            workflow_id=workflow_id,
            message="What are the benefits of using Python for data science?",
        )

        print(f"\nRun ID: {result.run_id}")
        print(f"Content: {result.content}")
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, "response"):
            print(f"Response: {e.response.text}")


async def run_workflow_streaming():
    """Execute a streaming workflow run."""
    print("\n" + "=" * 60)
    print("Streaming Workflow Run")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    # Get available workflows
    config = await client.aget_config()
    if not config.workflows:
        print("No workflows available")
        return

    workflow_id = config.workflows[0].id
    print(f"Streaming from workflow: {workflow_id}")
    print("\nResponse: ", end="", flush=True)

    try:
        # Stream the response
        async for line in client.run_workflow_stream(
            workflow_id=workflow_id,
            message="Explain machine learning in simple terms.",
        ):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if data.get("event") == "RunContent":
                        content = data.get("content", "")
                        print(content, end="", flush=True)
                except json.JSONDecodeError:
                    pass

        print("\n")
    except Exception as e:
        print(f"\nError: {type(e).__name__}")


async def main():
    # await run_workflow_non_streaming()
    await run_workflow_streaming()


if __name__ == "__main__":
    asyncio.run(main())
