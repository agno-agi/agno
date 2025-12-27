"""
Running Evaluations with AgentOSClient

This example demonstrates how to run and manage evaluations
using AgentOSClient.

Prerequisites:
1. Start an AgentOS server with agents
2. Run this script: python 08_run_evals.py
"""

import asyncio

from agno.client import AgentOSClient
from agno.db.schemas.evals import EvalType


async def run_accuracy_eval():
    """Run an accuracy evaluation."""
    print("=" * 60)
    print("Running Accuracy Evaluation")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    # Get available agents
    config = await client.aget_config()
    if not config.agents:
        print("No agents available")
        return

    agent_id = config.agents[0].id
    print(f"Evaluating agent: {agent_id}")

    # Run accuracy eval
    try:
        eval_result = await client.run_eval(
            agent_id=agent_id,
            eval_type=EvalType.ACCURACY,
            input_text="What is 2 + 2?",
            expected_output="4",
        )

        if eval_result:
            print(f"\nEval ID: {eval_result.id}")
            print(f"Eval Type: {eval_result.eval_type}")
            print(f"Eval Data: {eval_result.eval_data}")
        else:
            print("Evaluation returned no result")

    except Exception as e:
        print(f"Error running eval: {e}")
        if hasattr(e, "response"):
            print(f"Response: {e.response.text}")


async def run_performance_eval():
    """Run a performance evaluation."""
    print("\n" + "=" * 60)
    print("Running Performance Evaluation")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    # Get available agents
    config = await client.aget_config()
    if not config.agents:
        print("No agents available")
        return

    agent_id = config.agents[0].id
    print(f"Evaluating agent: {agent_id}")

    # Run performance eval
    try:
        eval_result = await client.run_eval(
            agent_id=agent_id,
            eval_type=EvalType.PERFORMANCE,
            input_text="Hello, how are you?",
            num_iterations=2,  # Run twice to measure performance
        )

        if eval_result:
            print(f"\nEval ID: {eval_result.id}")
            print(f"Eval Type: {eval_result.eval_type}")
            print(f"Performance Data: {eval_result.eval_data}")
        else:
            print("Evaluation returned no result")

    except Exception as e:
        print(f"Error running eval: {e}")
        if hasattr(e, "response"):
            print(f"Response: {e.response.text}")


async def list_eval_runs():
    """List all evaluation runs."""
    print("\n" + "=" * 60)
    print("Listing Evaluation Runs")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    try:
        evals = await client.list_eval_runs()
        print(f"\nFound {len(evals.data)} evaluation runs")

        for eval_run in evals.data[:5]:  # Show first 5
            print(f"\n- ID: {eval_run.id}")
            print(f"  Name: {eval_run.name}")
            print(f"  Type: {eval_run.eval_type}")
            print(f"  Agent: {eval_run.agent_id}")

    except Exception as e:
        print(f"Error listing evals: {e}")


async def get_eval_details():
    """Get details of a specific evaluation."""
    print("\n" + "=" * 60)
    print("Getting Evaluation Details")
    print("=" * 60)

    client = AgentOSClient(base_url="http://localhost:7777")

    try:
        # First list evals to get an ID
        evals = await client.list_eval_runs()
        if not evals.data:
            print("No evaluations found")
            return

        eval_id = evals.data[0].id
        print(f"Getting details for eval: {eval_id}")

        eval_run = await client.get_eval_run(eval_id)
        print(f"\nEval ID: {eval_run.id}")
        print(f"Name: {eval_run.name}")
        print(f"Type: {eval_run.eval_type}")
        print(f"Agent ID: {eval_run.agent_id}")
        print(f"Data: {eval_run.eval_data}")

    except Exception as e:
        print(f"Error getting eval: {e}")


async def main():
    await run_accuracy_eval()
    await run_performance_eval()
    await list_eval_runs()
    await get_eval_details()


if __name__ == "__main__":
    asyncio.run(main())
