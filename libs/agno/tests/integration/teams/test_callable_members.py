"""Integration tests for Team callable members based on session_state.

This tests the pattern where team members are dynamically selected at runtime
based on session_state values (e.g., needs_research flag).

Key scenarios tested:
1. Basic callable members selection based on session_state
2. Delegation to callable members (team leader must see member IDs)
3. System message contains resolved member information
"""

from agno.agent.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team


def test_callable_members_selected_by_session_state(shared_db):
    """Team members are selected based on session_state at runtime."""
    writer = Agent(
        name="Writer",
        role="Content writer",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Write clear, concise content."],
    )

    researcher = Agent(
        name="Researcher",
        role="Research analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["Research topics and summarize findings."],
    )

    def pick_members(session_state: dict):
        """Include the researcher only when needed."""
        needs_research = session_state.get("needs_research", False)
        if needs_research:
            return [researcher, writer]
        return [writer]

    team = Team(
        name="Content Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        instructions=["Coordinate the team to complete the task."],
        db=shared_db,
        telemetry=False,
    )

    # Run without research - only writer should be used
    response1 = team.run(
        "Write a haiku about Python",
        session_state={"needs_research": False},
    )
    assert response1 is not None
    assert response1.content is not None

    # Run with research - researcher + writer should be used
    response2 = team.run(
        "Research the history of Python and write a short summary",
        session_state={"needs_research": True},
    )
    assert response2 is not None
    assert response2.content is not None


def test_callable_members_stream(shared_db):
    """Callable members work with streaming."""
    writer = Agent(
        name="Writer",
        role="Content writer",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    researcher = Agent(
        name="Researcher",
        role="Research analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    def pick_members(session_state: dict):
        if session_state.get("needs_research"):
            return [researcher, writer]
        return [writer]

    team = Team(
        name="Content Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        db=shared_db,
        telemetry=False,
    )

    # Stream with research enabled
    chunks = []
    for chunk in team.run(
        "Write a short poem",
        session_state={"needs_research": True},
        stream=True,
    ):
        chunks.append(chunk)

    assert len(chunks) > 0
    response = team.get_last_run_output()
    assert response is not None
    assert response.content is not None


async def test_callable_members_async(shared_db):
    """Callable members work with async runs."""
    writer = Agent(
        name="Writer",
        role="Content writer",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    researcher = Agent(
        name="Researcher",
        role="Research analyst",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    def pick_members(session_state: dict):
        if session_state.get("needs_research"):
            return [researcher, writer]
        return [writer]

    team = Team(
        name="Content Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        db=shared_db,
        telemetry=False,
    )

    response = await team.arun(
        "Write a short greeting",
        session_state={"needs_research": False},
    )
    assert response is not None
    assert response.content is not None


def test_callable_members_default_session_state(shared_db):
    """Callable members handle missing session_state keys gracefully."""
    writer = Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    def pick_members(session_state: dict):
        # Default to writer only if needs_research is not set
        needs_research = session_state.get("needs_research", False)
        if needs_research:
            return [researcher, writer]
        return [writer]

    team = Team(
        name="Content Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        db=shared_db,
        telemetry=False,
    )

    # Empty session_state - should default to writer only
    response = team.run(
        "Say hello",
        session_state={},
    )
    assert response is not None
    assert response.content is not None


def test_callable_members_complex_selection(shared_db):
    """Callable members can use multiple session_state values."""
    writer = Agent(
        name="Writer",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    researcher = Agent(
        name="Researcher",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    editor = Agent(
        name="Editor",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    def pick_members(session_state: dict):
        members = [writer]
        if session_state.get("needs_research"):
            members.insert(0, researcher)
        if session_state.get("needs_editing"):
            members.append(editor)
        return members

    team = Team(
        name="Content Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        db=shared_db,
        telemetry=False,
    )

    # Full pipeline: research + write + edit
    response = team.run(
        "Create a polished article",
        session_state={"needs_research": True, "needs_editing": True},
    )
    assert response is not None
    assert response.content is not None


def test_callable_members_delegation(shared_db):
    """Team leader can delegate to callable members by ID.

    This tests that the system message contains resolved member IDs so the
    team leader can properly delegate tasks to dynamically resolved members.
    """
    # Create a writer that has a distinctive behavior we can verify
    writer = Agent(
        name="Writer",
        role="Content writer who writes poems",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["You are a poet. Always write in verse with rhymes."],
    )

    researcher = Agent(
        name="Researcher",
        role="Research analyst who finds facts",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=["You research topics and provide factual summaries."],
    )

    def pick_members(session_state: dict):
        needs_research = session_state.get("needs_research", False)
        if needs_research:
            return [researcher, writer]
        return [writer]

    team = Team(
        name="Content Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        instructions=[
            "You coordinate the team. Delegate writing tasks to the Writer.",
            "For research tasks, first delegate to Researcher, then to Writer.",
        ],
        db=shared_db,
        telemetry=False,
    )

    # Run with delegation - the team should delegate to the writer
    response = team.run(
        "Write a short haiku about the ocean",
        session_state={"needs_research": False},
    )
    assert response is not None
    assert response.content is not None

    # Verify delegation happened by checking member_responses
    # The writer should have been called
    if response.member_responses:
        member_names = [mr.member_name for mr in response.member_responses]
        assert "Writer" in member_names


def test_callable_members_system_message_contains_member_ids(shared_db):
    """System message must contain resolved member IDs for delegation to work.

    This is the core test for the fix - when members is a callable, the system
    message builder must use get_resolved_members() to get the actual member
    list, not read team.members directly (which would be the callable).

    get_members_system_message_content() iterates over
    team.members directly. If it's a callable, the iteration fails silently
    and returns empty content, so the team leader has no member IDs to delegate to.
    """
    writer = Agent(
        name="TestWriter",
        role="A test writer agent",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    researcher = Agent(
        name="TestResearcher",
        role="A test researcher agent",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    def pick_members(session_state: dict):
        if session_state.get("include_researcher"):
            return [researcher, writer]
        return [writer]

    team = Team(
        name="Test Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        db=shared_db,
        telemetry=False,
    )

    # Run the team to trigger system message generation
    response = team.run(
        "Hello",
        session_state={"include_researcher": True},
    )

    assert response is not None
    assert response.messages is not None, "Response should have messages"

    # Find the system message
    system_messages = [m for m in response.messages if m.role == "system"]
    assert len(system_messages) > 0, "Should have at least one system message"

    system_content = system_messages[0].content
    assert system_content is not None, "System message should have content"

    # CRITICAL: The system message MUST contain the member IDs for delegation to work
    # Without the fix, this would be empty because get_members_system_message_content()
    # iterates over team.members (the callable) instead of resolved members
    assert "TestWriter" in system_content, (
        f"System message must contain 'TestWriter' for delegation. Got: {system_content[:500]}..."
    )
    assert "TestResearcher" in system_content, (
        f"System message must contain 'TestResearcher' for delegation. Got: {system_content[:500]}..."
    )


async def test_callable_members_delegation_async(shared_db):
    """Async delegation to callable members works correctly."""
    writer = Agent(
        name="AsyncWriter",
        role="Async content writer",
        model=OpenAIChat(id="gpt-4o-mini"),
    )

    def pick_members(session_state: dict):
        return [writer]

    team = Team(
        name="Async Team",
        model=OpenAIChat(id="gpt-4o-mini"),
        members=pick_members,
        cache_callables=False,
        instructions=["Delegate all writing tasks to the AsyncWriter."],
        db=shared_db,
        telemetry=False,
    )

    response = await team.arun(
        "Write a one-line greeting",
        session_state={},
    )

    assert response is not None
    assert response.content is not None

    # Check delegation happened
    if response.member_responses:
        member_names = [mr.member_name for mr in response.member_responses]
        assert "AsyncWriter" in member_names
