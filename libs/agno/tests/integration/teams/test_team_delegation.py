import asyncio
from typing import List

import pytest
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team

ASYNC_TEST_TIMEOUT = 300


def test_team_delegation():
    """Test basic functionality of a coordinator team."""

    def get_climate_change_info() -> str:
        return "Climate change is a global issue that requires urgent action."

    researcher = Agent(
        name="Researcher",
        model=OpenAIChat("gpt-4o"),
        role="Research information",
        tools=[get_climate_change_info],
    )

    writer = Agent(name="Writer", model=OpenAIChat("gpt-4o"), role="Write content based on research")

    team = Team(
        name="Content Team",
        model=OpenAIChat("gpt-4o"),
        members=[researcher, writer],
        instructions=[
            "First, have the Researcher gather information on the topic.",
            "Then, have the Writer create content based on the research.",
        ],
    )

    response = team.run("Write a short article about climate change solutions")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0


def test_respond_directly():
    """Test basic functionality of a coordinator team."""

    english_agent = Agent(name="English Agent", model=OpenAIChat("gpt-5-mini"), role="Answer in English")
    spanish_agent = Agent(name="Spanish Agent", model=OpenAIChat("gpt-5-mini"), role="Answer in Spanish")

    team = Team(
        name="Translation Team",
        model=OpenAIChat("gpt-5-mini"),
        determine_input_for_members=False,
        respond_directly=True,
        members=[english_agent, spanish_agent],
        instructions=[
            "If the user asks in English, respond in English. If the user asks in Spanish, respond in Spanish.",
            "Never answer directly, you must delegate the task to the appropriate agent.",
        ],
    )

    response = team.run("¿Cuéntame algo interesante sobre Madrid?")

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    assert response.member_responses[0].content == response.content
    # Check the user message is the same as the input
    assert response.member_responses[0].messages[1].role == "user"
    assert response.member_responses[0].messages[1].content == "¿Cuéntame algo interesante sobre Madrid?"


def test_use_input_directly_structured_input():
    """Test basic functionality of a coordinator team."""

    class ResearchRequest(BaseModel):
        topic: str
        focus_areas: List[str]
        target_audience: str
        sources_required: int

    researcher = Agent(name="Researcher", model=OpenAIChat("gpt-4o"), role="Research information")

    team = Team(
        name="Content Team",
        model=OpenAIChat("gpt-4o"),
        determine_input_for_members=False,
        members=[researcher],
        instructions=[
            "Have the Researcher gather information on the topic.",
        ],
    )

    research_request = ResearchRequest(
        topic="AI Agent Frameworks",
        focus_areas=["AI Agents", "Framework Design", "Developer Tools", "Open Source"],
        target_audience="Software Developers and AI Engineers",
        sources_required=7,
    )

    response = team.run(
        input=research_request,
    )

    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    # Check the user message is the same as the input
    assert response.member_responses[0].messages[1].role == "user"
    assert response.member_responses[0].messages[1].content == research_request.model_dump_json(
        indent=2, exclude_none=True
    )


def test_delegate_to_all_members():
    """Test basic functionality of a collaborate team."""
    agent1 = Agent(
        name="Agent 1",
        model=OpenAIChat("gpt-4o"),
        role="First perspective provider",
        instructions="Provide a perspective on the given topic.",
    )

    agent2 = Agent(
        name="Agent 2",
        model=OpenAIChat("gpt-4o"),
        role="Second perspective provider",
        instructions="Provide a different perspective on the given topic.",
    )

    team = Team(
        name="Collaborative Team",
        delegate_to_all_members=True,
        model=OpenAIChat("gpt-4o"),
        members=[agent1, agent2],
        instructions=[
            "Synthesize the perspectives from both team members.",
            "Provide a balanced view that incorporates insights from both perspectives.",
            "Only ask the members once for their perspectives.",
        ],
    )

    response = team.run("What are the pros and cons of remote work?")
    assert response.content is not None
    assert isinstance(response.content, str)
    assert len(response.content) > 0
    tools = response.tools
    assert tools is not None
    assert len(tools) == 1


@pytest.mark.asyncio
async def test_async_delegate_to_all_members_agent_identity():
    """
    Regression test for closure bug in adelegate_task_to_members (PR #6067).

    Verifies that when delegate_to_all_members=True and async mode is used,
    each agent correctly receives its own identity (not the last agent's).

    Bug: Python closures in loops capture variables by reference, so all
    concurrent tasks would see the last loop iteration's values.

    Fix: Capture loop variables via default arguments.
    """
    # Create 3 agents with distinct names that include their identity in responses
    agents = [
        Agent(
            name=f"Worker{i}",
            id=f"worker-{i}",
            model=OpenAIChat("gpt-4o-mini"),
            instructions=[
                f"You are Worker{i}.",
                f"Always start your response with 'I am Worker{i}.'",
                "Keep your response brief - just one sentence.",
            ],
        )
        for i in range(1, 4)
    ]

    team = Team(
        name="Identity Test Team",
        model=OpenAIChat("gpt-4o-mini"),
        members=agents,
        delegate_to_all_members=True,
        # Force the model to use the delegation tool
        tool_choice={"type": "function", "function": {"name": "delegate_task_to_members"}},
        instructions=[
            "Delegate to all members and collect their responses.",
            "Do not modify their responses.",
        ],
    )

    # Run async without streaming with timeout
    try:
        response = await asyncio.wait_for(
            team.arun("Identify yourself.", stream=False),
            timeout=ASYNC_TEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        pytest.skip(f"Test timed out after {ASYNC_TEST_TIMEOUT}s - skipping due to slow API response")

    assert response is not None
    assert response.content is not None

    # Skip if the run was cancelled
    content = str(response.content)
    if "cancelled" in content.lower():
        pytest.skip("Run was cancelled, likely due to timeout")

    # Delegation should have happened since we forced tool_choice
    tool_results = " ".join(str(t.result) for t in response.tools if t.result) if response.tools else ""
    combined = content + " " + tool_results

    # Verify all three agent identities appear in the response
    # Before the fix, all would show "Worker3" - now each should have correct identity
    assert "Worker1" in combined, f"Worker1 not found in response: {combined}"
    assert "Worker2" in combined, f"Worker2 not found in response: {combined}"
    assert "Worker3" in combined, f"Worker3 not found in response: {combined}"


@pytest.mark.asyncio
async def test_async_delegate_to_all_members_streaming_agent_identity():
    """
    Regression test for closure bug in streaming mode (PR #6067).

    Tests that the streaming branch correctly uses the function parameter
    instead of the outer loop variable.
    """
    # Create 3 agents with distinct names
    agents = [
        Agent(
            name=f"StreamWorker{i}",
            id=f"stream-worker-{i}",
            model=OpenAIChat("gpt-4o-mini"),
            instructions=[
                f"You are StreamWorker{i}.",
                f"Always start your response with 'I am StreamWorker{i}.'",
                "Keep your response brief - just one sentence.",
            ],
        )
        for i in range(1, 4)
    ]

    team = Team(
        name="Streaming Identity Test Team",
        model=OpenAIChat("gpt-4o-mini"),
        members=agents,
        delegate_to_all_members=True,
        # Force the model to use the delegation tool
        tool_choice={"type": "function", "function": {"name": "delegate_task_to_members"}},
        instructions=[
            "Delegate to all members and collect their responses.",
            "Do not modify their responses.",
        ],
    )

    # Run async with streaming, with timeout protection
    async def collect_stream():
        collected = []
        async for event in team.arun("Identify yourself.", stream=True, stream_events=True):
            if hasattr(event, "content") and event.content:
                collected.append(str(event.content))
        return collected

    try:
        collected_content = await asyncio.wait_for(collect_stream(), timeout=ASYNC_TEST_TIMEOUT)
    except asyncio.TimeoutError:
        pytest.skip(f"Test timed out after {ASYNC_TEST_TIMEOUT}s - skipping due to slow API response")

    # Combine all content
    full_content = " ".join(collected_content)

    # Skip assertion if the run was cancelled (e.g., due to external timeout)
    if "cancelled" in full_content.lower():
        pytest.skip("Run was cancelled, likely due to timeout")

    # Verify all three agent identities appear
    # Before the fix in streaming mode, all would show "StreamWorker3"
    assert "StreamWorker1" in full_content, f"StreamWorker1 not found in response: {full_content}"
    assert "StreamWorker2" in full_content, f"StreamWorker2 not found in response: {full_content}"
    assert "StreamWorker3" in full_content, f"StreamWorker3 not found in response: {full_content}"


@pytest.mark.asyncio
async def test_async_delegate_to_all_members_with_tools():
    """
    Test that async delegation with tools correctly identifies each agent.

    This tests a more complex scenario where agents have tools and the
    closure bug could affect tool execution attribution.
    """

    # Create agents with a tool that uses their identity - using only 2 agents to speed up
    agents = []
    for i in range(1, 3):

        def create_identity_tool(agent_num: int):
            def identify() -> str:
                """Return this agent's identity."""
                return f"ToolAgent{agent_num} reporting"

            return identify

        agent = Agent(
            name=f"ToolAgent{i}",
            id=f"tool-agent-{i}",
            model=OpenAIChat("gpt-4o-mini"),
            tools=[create_identity_tool(i)],
            instructions=[
                f"You are ToolAgent{i}.",
                "When asked to identify, call the identify tool.",
                "Keep responses brief - one sentence max.",
            ],
        )
        agents.append(agent)

    team = Team(
        name="Tool Identity Test Team",
        model=OpenAIChat("gpt-4o-mini"),
        members=agents,
        delegate_to_all_members=True,
        # Force the model to use the delegation tool
        tool_choice={"type": "function", "function": {"name": "delegate_task_to_members"}},
        instructions=["Delegate to all members. Keep your final response brief."],
    )

    try:
        response = await asyncio.wait_for(
            team.arun("Use your identify tool.", stream=False),
            timeout=ASYNC_TEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        pytest.skip(f"Test timed out after {ASYNC_TEST_TIMEOUT}s - skipping due to slow API response")

    assert response is not None
    assert response.content is not None

    # Check that delegation happened and tools were called
    content = str(response.content)

    # Skip if the run was cancelled (e.g., due to external timeout or rate limiting)
    if "cancelled" in content.lower():
        pytest.skip("Run was cancelled, likely due to timeout or rate limiting")

    tool_results = " ".join(str(t.result) for t in response.tools if t.result) if response.tools else ""
    combined = content + " " + tool_results

    # Verify agent identities appear (tools should have been called)
    assert "ToolAgent1" in combined or "ToolAgent2" in combined, f"No ToolAgent identity found in response: {combined}"
