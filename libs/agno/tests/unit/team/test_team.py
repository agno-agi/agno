import uuid

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools


@pytest.fixture
def team():
    web_agent = Agent(
        name="Web Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for information",
        tools=[DuckDuckGoTools(cache_results=True)],
    )

    finance_agent = Agent(
        name="Finance Agent",
        model=OpenAIChat("gpt-4o"),
        role="Get financial data",
        tools=[YFinanceTools(stock_price=True)],
    )

    team = Team(name="Router Team", mode="route", model=OpenAIChat("gpt-4o"), members=[web_agent, finance_agent])
    return team


def test_team_system_message_content(team):
    """Test basic functionality of a route team."""

    # Get the actual content
    members_content = team.get_members_system_message_content()

    # Check for expected content with fuzzy matching
    assert "Agent 1:" in members_content
    assert "ID: web-agent" in members_content
    assert "Name: Web Agent" in members_content
    assert "Role: Search the web for information" in members_content
    assert "duckduckgo_search" in members_content

    assert "Agent 2:" in members_content
    assert "ID: finance-agent" in members_content
    assert "Name: Finance Agent" in members_content
    assert "Role: Get financial data" in members_content
    assert "get_current_stock_price" in members_content


def test_transfer_to_wrong_member(team):
    function = team.get_transfer_task_function(session_id="test-session")
    response = list(
        function.entrypoint(
            member_id="wrong-agent", task_description="Get the current stock price of AAPL", expected_output=""
        )
    )
    assert "Member with ID wrong-agent not found in the team or any subteams" in response[0]


def test_forward_to_wrong_member(team):
    function = team.get_forward_task_function(message="Hello, world!", session_id="test-session")
    response = list(function.entrypoint(member_id="wrong-agent", expected_output=""))
    assert "Member with ID wrong-agent not found in the team or any subteams" in response[0]


def test_get_member_id():
    member = Agent(name="Test Agent")
    assert Team(members=[member])._get_member_id(member) == "test-agent"
    member = Agent(name="Test Agent", agent_id="123")
    assert Team(members=[member])._get_member_id(member) == "123"
    member = Agent(name="Test Agent", agent_id=str(uuid.uuid4()))
    assert Team(members=[member])._get_member_id(member) == "test-agent"
    member = Agent(agent_id=str(uuid.uuid4()))
    assert Team(members=[member])._get_member_id(member) == member.agent_id

    member = Agent(name="Test Agent")
    inner_team = Team(name="Test Team", members=[member])
    assert Team(members=[inner_team])._get_member_id(inner_team) == "test-team"
    inner_team = Team(name="Test Team", team_id="123", members=[member])
    assert Team(members=[inner_team])._get_member_id(inner_team) == "123"
    inner_team = Team(name="Test Team", team_id=str(uuid.uuid4()), members=[member])
    assert Team(members=[inner_team])._get_member_id(inner_team) == "test-team"
    inner_team = Team(team_id=str(uuid.uuid4()), members=[member])
    assert Team(members=[inner_team])._get_member_id(inner_team) == inner_team.team_id


@pytest.mark.asyncio
async def test_aget_relevant_docs_from_knowledge_with_none_num_documents():
    """Test that aget_relevant_docs_from_knowledge handles num_documents=None correctly with retriever."""

    # Create a mock knowledge object
    class MockKnowledge:
        def __init__(self):
            self.num_documents = 5
            self.vector_db = None

        def validate_filters(self, filters):
            return filters or {}, []

    # Create a mock retriever function
    def mock_retriever(team, query, num_documents, **kwargs):
        # Verify that num_documents is correctly set to knowledge.num_documents
        assert num_documents == 5
        return [{"content": "test document"}]

    # Create Team instance
    team = Team(members=[])
    team.knowledge = MockKnowledge()
    team.retriever = mock_retriever

    # Call the function with num_documents=None
    result = await team.aget_relevant_docs_from_knowledge(query="test query", num_documents=None)

    # Verify the result
    assert result == [{"content": "test document"}]


def test_get_relevant_docs_from_knowledge_num_documents():
    # Create mock knowledge
    class MockKnowledge:
        def __init__(self):
            self.num_documents = 7
            self.vector_db = None

        def validate_filters(self, filters):
            return filters or {}, []

    # Create mock retriever
    called = {}

    def mock_retriever(team, query, num_documents, **kwargs):
        called["num_documents"] = num_documents
        return [{"content": "doc"}]

    team = Team(members=[])
    team.knowledge = MockKnowledge()
    team.retriever = mock_retriever

    # When num_documents=None, use knowledge.num_documents
    result = team.get_relevant_docs_from_knowledge("query", num_documents=None)
    assert called["num_documents"] == 7
    assert result == [{"content": "doc"}]

    # When num_documents=3, prioritize explicit parameter
    result = team.get_relevant_docs_from_knowledge("query", num_documents=3)
    assert called["num_documents"] == 3
    assert result == [{"content": "doc"}]
