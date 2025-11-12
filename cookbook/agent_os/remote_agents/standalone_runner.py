"""Examples demonstrating AgentOSRunner for local and remote execution."""

import asyncio
from agno.runner import AgentOSRunner

async def remote_agent_example():
    """Call a remote agent hosted on another AgentOS instance."""
    # Create a runner that points to a remote agent
    runner = AgentOSRunner(
        base_url="http://localhost:7777",
        agent_id="basic-agent",
        # Optional: add API key for authentication
        # api_key="your-api-key-here",
    )
    
    # Run the remote agent (same interface as local)
    response = await runner.arun(
        "What is the capital of France?",
        user_id="user-123",
        session_id="session-456",
    )
    print(f"Remote Response: {response.content}")


# Example 4: Streaming with remote agent
async def remote_streaming_example():
    """Stream responses from a remote agent."""
    runner = AgentOSRunner(
        base_url="http://localhost:7777",
        agent_id="basic-agent",
    )
    
    # Stream the response (same interface as local)
    async for chunk in runner.arun(
        "Tell me a short story",
        stream=True,
        stream_events=True,
    ):
        if hasattr(chunk, 'content') and chunk.content:
            print(chunk.content, end="", flush=True)


# Example 5: Remote team execution
async def remote_team_example():
    """Call a remote team."""
    runner = AgentOSRunner(
        base_url="http://localhost:7777",
        team_id="basic-team",
    )
    
    response = await runner.arun("Research and write about AI")
    print(f"Team Response: {response.content}")


# Example 6: Remote workflow execution
async def remote_workflow_example():
    """Call a remote workflow."""
    runner = AgentOSRunner(
        base_url="http://localhost:7777",
        workflow_id="basic-workflow",
    )
    
    response = await runner.arun(
        "Process this data",
        session_state={"data": [1, 2, 3, 4, 5]},
    )
    print(f"Workflow Response: {response.content}")


# Example 7: Using with context (conversation history)
async def conversation_example():
    """Maintain conversation history with a remote agent."""
    runner = AgentOSRunner(
        base_url="http://localhost:7777",
        agent_id="basic-agent",
    )
    
    # First message
    response1 = await runner.arun(
        "My name is Alice",
        user_id="alice",
        session_id="conversation-1",
        add_history_to_context=True,
    )
    print(f"Response 1: {response1.content}")
    
    # Second message - agent remembers the first
    response2 = await runner.arun(
        "What's my name?",
        user_id="alice",
        session_id="conversation-1",
        add_history_to_context=True,
    )
    print(f"Response 2: {response2.content}")


# Example 8: Error handling
async def error_handling_example():
    """Handle errors when calling remote agents."""
    runner = AgentOSRunner(
        base_url="http://localhost:7777",
        agent_id="non-existent-agent",
        timeout=30.0,
    )
    
    try:
        response = await runner.arun("Hello")
        print(f"Response: {response.content}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("AgentOSRunner Examples")
    print("=" * 60)
    
    # Run examples
    # Note: Remote examples require a running AgentOS instance
    
    print("\n1. Local Agent Example:")
    asyncio.run(local_agent_example())
    
    # Uncomment to run remote examples (requires AgentOS running)
    # print("\n2. Remote Agent Example:")
    # asyncio.run(remote_agent_example())
    
    # print("\n3. Local Streaming Example:")
    # asyncio.run(local_streaming_example())
    
    # print("\n4. Remote Streaming Example:")
    # asyncio.run(remote_streaming_example())
    
    # print("\n5. Remote Team Example:")
    # asyncio.run(remote_team_example())
    
    # print("\n6. Remote Workflow Example:")
    # asyncio.run(remote_workflow_example())
    
    # print("\n7. Conversation Example:")
    # asyncio.run(conversation_example())
    
    # print("\n8. Error Handling Example:")
    # asyncio.run(error_handling_example())

