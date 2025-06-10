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

    member = Agent(name="Test Agent")
    inner_team = Team(name="Test Team", members=[member])
    assert Team(members=[inner_team])._get_member_id(inner_team) == "test-team"
    inner_team = Team(name="Test Team", team_id="123", members=[member])
    assert Team(members=[inner_team])._get_member_id(inner_team) == "123"
    inner_team = Team(name="Test Team", team_id=str(uuid.uuid4()), members=[member])
    assert Team(members=[inner_team])._get_member_id(inner_team) == "test-team"
