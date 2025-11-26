"""
Example demonstrating AgentOSClient for discovery and management operations.

This example shows how to use AgentOSClient to:
- Discover available agents, teams, and workflows
- Get detailed configuration information
- Execute agents/teams/workflows via the client

Run `agent_os_setup.py` first to start the remote AgentOS instance.
"""

import asyncio

from agno.os import AgentOSClient


async def discovery_example():
    """Discover available resources on a remote AgentOS instance."""
    print("\n" + "=" * 60)
    print("Discovery Example")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7778") as client:
        # Get OS configuration
        config = await client.get_config()
        print(f"\nAgentOS ID: {config.os_id}")
        print(f"Description: {config.description}")

        # List all agents
        print("\n--- Available Agents ---")
        agents = await client.list_agents()
        for agent in agents:
            print(f"  • {agent.id}: {agent.name}")
            if agent.description:
                print(f"    Description: {agent.description}")

        # List all teams
        print("\n--- Available Teams ---")
        teams = await client.list_teams()
        for team in teams:
            print(f"  • {team.id}: {team.name}")
            if team.description:
                print(f"    Description: {team.description}")

        # List all workflows
        print("\n--- Available Workflows ---")
        workflows = await client.list_workflows()
        for workflow in workflows:
            print(f"  • {workflow.id}: {workflow.name}")
            if workflow.description:
                print(f"    Description: {workflow.description}")

        # Get models
        print("\n--- Models in Use ---")
        models = await client.get_models()
        for model in models:
            print(f"  • {model.id} ({model.provider})")


async def detailed_config_example():
    """Get detailed configuration for specific resources."""
    print("\n" + "=" * 60)
    print("Detailed Configuration Example")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7778") as client:
        # Get detailed agent config
        print("\n--- Agent Details ---")
        agent = await client.get_agent("basic-agent")
        print(f"Agent ID: {agent.id}")
        print(f"Name: {agent.name}")
        if agent.model:
            print(f"Model: {agent.model.name} - {agent.model.model}")
        if agent.sessions:
            print(f"Sessions: {agent.sessions}")
        if agent.system_message:
            print(f"System Message Config: {agent.system_message}")

        # Get detailed team config
        print("\n--- Team Details ---")
        team = await client.get_team("basic-team")
        print(f"Team ID: {team.id}")
        print(f"Name: {team.name}")
        if team.members:
            print(f"Members: {len(team.members)}")
            for member in team.members:
                print(f"  • {member.name}")

        # Get detailed workflow config
        print("\n--- Workflow Details ---")
        workflow = await client.get_workflow("basic-workflow")
        print(f"Workflow ID: {workflow.id}")
        print(f"Name: {workflow.name}")
        if workflow.steps:
            print(f"Steps: {len(workflow.steps)}")


async def execution_via_client_example():
    """Execute agents/teams/workflows using the client."""
    print("\n" + "=" * 60)
    print("Execution via Client Example")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7778") as client:
        try:
            # Method 1: Get a runner and execute (recommended for multiple runs)
            print("\n--- Method 1: Using Runner ---")
            runner = client.agent("basic-agent")
            response = await runner.arun(
                "What is the capital of Japan?",
                user_id="user-123",
                session_id="session-789",
            )
            print(f"Response: {response.content}")

            # Method 2: Direct execution (convenience)
            print("\n--- Method 2: Direct Execution ---")
            response = await client.run_agent(
                "basic-agent",
                "What is 2+2?",
                user_id="user-123",
                session_id="session-789",
            )
            print(f"Response: {response.content}")

            # Execute a team
            print("\n--- Team Execution ---")
            team_response = await client.run_team(
                "basic-team",
                "What are the top 3 programming languages in 2024?",
                user_id="user-456",
            )
            print(f"Team Response: {team_response.content}")
        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "openai_api_key" in error_msg.lower() or "502" in error_msg:
                print(f"\  Execution requires OPENAI_API_KEY environment variable to be set.")
            else:
                print(f"\n Error during execution: {error_msg}")


async def streaming_via_client_example():
    """Stream responses from agents via the client."""
    print("\n" + "=" * 60)
    print("Streaming via Client Example")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7778") as client:
        try:
            # Streaming with runner
            print("\n--- Streaming Response ---")
            runner = client.agent("basic-agent")

            async for chunk in runner.arun(
                "Tell me a 2 sentence story about a robot",
                user_id="user-123",
                session_id="session-999",
                stream=True,
                stream_events=True,
            ):
                if hasattr(chunk, "content") and chunk.content:
                    print(chunk.content, end="", flush=True)

            print("\n")
        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "openai_api_key" in error_msg.lower():
                print(f"\n Streaming requires OPENAI_API_KEY environment variable to be set.")
            else:
                print(f"\n Error during streaming: {error_msg}")


async def multi_resource_workflow():
    """Demonstrate a workflow using multiple resources."""
    print("\n" + "=" * 60)
    print("Multi-Resource Workflow Example")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7778") as client:
        try:
            # First, discover what's available
            agents = await client.list_agents()
            print(f"Found {len(agents)} agents")

            # Get detailed config for the first agent
            if agents:
                agent = await client.get_agent(agents[0].id)
                print(f"\nUsing agent: {agent.name}")

                # Create a runner for this agent
                runner = client.agent(agent.id)

                # Execute multiple times with the same runner (efficient)
                questions = [
                    "What is AI?",
                    "What is machine learning?",
                    "What is deep learning?",
                ]

                print("\n--- Running Multiple Questions ---")
                for i, question in enumerate(questions, 1):
                    print(f"\nQuestion {i}: {question}")
                    response = await runner.arun(
                        question,
                        session_id="learning-session",
                        user_id="student-001",
                    )
                    print(f"Answer: {response.content[:200]}...")
        except Exception as e:
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "openai_api_key" in error_msg.lower() or "502" in error_msg:
                print(f"\Multi-resource workflow requires OPENAI_API_KEY environment variable to be set.")
            else:
                print(f"\n Error in workflow: {error_msg}")


async def error_handling_example():
    """Demonstrate error handling with the client."""
    print("\n" + "=" * 60)
    print("Error Handling Example")
    print("=" * 60)

    async with AgentOSClient(base_url="http://localhost:7778") as client:
        # Try to get a non-existent agent
        try:
            print("\n--- Attempting to get non-existent agent ---")
            await client.get_agent("non-existent-agent")
        except Exception as e:
            print(f"Expected error: {type(e).__name__}")
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                print(f"Status code: {e.response.status_code}")

        # Try to run a non-existent agent
        try:
            print("\n--- Attempting to run non-existent agent ---")
            await client.run_agent("non-existent-agent", "Hello")
        except Exception as e:
            print(f"Expected error: {type(e).__name__}")
            if hasattr(e, "response") and hasattr(e.response, "status_code"):
                print(f"Status code: {e.response.status_code}")


if __name__ == "__main__":
    print("=" * 60)
    print("AgentOSClient Examples")
    print("=" * 60)
    print("\nMake sure agent_os_setup.py is running on port 7778")
    print("=" * 60)

    # Run examples
    asyncio.run(discovery_example())
    asyncio.run(detailed_config_example())
    asyncio.run(execution_via_client_example())
    asyncio.run(streaming_via_client_example())
    asyncio.run(multi_resource_workflow())
    asyncio.run(error_handling_example())

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)
