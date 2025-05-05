from agno.agent import Agent
from agno.models.openai import OpenAIChat


# Define a custom tool that forwards the agent context to the tool
def params_forwarding_tool(user_id: str, session_id: str, agent: Agent):
    return f"Tool called with agent ID: {agent.agent_id}, user ID: {user_id}, session ID: {session_id}"

# Test that user_id and session_id are forwarded to the tool on run call with streaming response
def test_run_user_and_session_id_forwarding_to_tool_streaming():
    """
    Test that agent is forwarded to the tool
    """

    agent = Agent(
        agent_id="test-agent",
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[params_forwarding_tool],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False
    )

    # Run the agent with the tool, providing a user ID and session ID that should be included in the tool call response
    run_response = agent.run(
        stream=True,
        user_id="test-user",
        session_id="test-session",
        message="Please invoke the params_forwarding_tool to retrieve context. Return directly the response from the tool without any additional formatting or modification."
    )


    

    content = ""

    # Get the response from the run
    for response in run_response:
        content += response.content

    # Verify tool usage by checking if the agent ID, user ID, and session ID are included in the response
    assert "test-agent" in content
    assert "test-user" in content
    assert "test-session" in content


# Test that user_id and session_id are forwarded to the tool on run call with non-streaming response
def test_run_user_and_session_id_forwarding_to_tool():
    """
    Test that agent is forwarded to the tool
    """

    agent = Agent(
        agent_id="test-agent",
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[params_forwarding_tool],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False
    )

    # Run the agent with the tool, providing a user ID and session ID that should be included in the tool call response
    run_response = agent.run(
        user_id="test-user",
        session_id="test-session",
        message="Please invoke the params_forwarding_tool to retrieve context. Return directly the response from the tool without any additional formatting or modification."
    )

    # Get the response from the run

    # Verify tool usage
    assert any(msg.tool_calls for msg in run_response.messages)
    assert run_response.content is not None

     # Verify the agent ID is included in the response, indicating that the tool was called with the agent context
    assert "test-agent" in run_response.content
    assert "test-user" in run_response.content
    assert "test-session" in run_response.content

# Test that user_id and session_id are forwarded to the tool on call without user_id and session_id on run but on Agent creation
def test_agent_user_and_session_id_forwarding_to_tool():
    """
    Test that agent is forwarded to the tool
    """

    agent = Agent(
        user_id="test-user",
        session_id="test-session",
        agent_id="test-agent",
        name="Test Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[params_forwarding_tool],
        show_tool_calls=True,
        markdown=True,
        telemetry=False,
        monitoring=False
    )

    # Run the agent with the tool, providing a user ID and session ID that should be included in the tool call response
    run_response = agent.run(
        message="Please invoke the params_forwarding_tool to retrieve context. Return directly the response from the tool without any additional formatting or modification."
    )

    # Get the response from the run
    assert "test-agent" in run_response.content
    assert "test-user" in run_response.content
    assert "test-session" in run_response.content

    
    


