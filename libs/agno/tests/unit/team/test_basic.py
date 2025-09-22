import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.utils.string import is_valid_uuid


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
        tools=[YFinanceTools(include_tools=["get_current_stock_price"])],
    )

    team = Team(name="Router Team", model=OpenAIChat("gpt-4o"), members=[web_agent, finance_agent])
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


def test_delegate_to_wrong_member(team):
    function = team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        session_state={},
        team_run_context={},
    )
    response = list(
        function.entrypoint(
            member_id="wrong-agent", task_description="Get the current stock price of AAPL", expected_output=""
        )
    )
    assert "Member with ID wrong-agent not found in the team or any subteams" in response[0]


def test_set_id():
    team = Team(
        id="test_id",
        members=[],
    )
    team.set_id()
    assert team.id == "test_id"


def test_set_id_from_name():
    team = Team(
        name="Test Name",
        members=[],
    )
    team.set_id()
    team_id = team.id

    assert team_id is not None
    assert team_id == "test-name"

    team.id = None
    team.set_id()
    # It is deterministic, so it should be the same
    assert team.id == team_id


def test_set_id_auto_generated():
    team = Team(
        members=[],
    )
    team.set_id()
    assert team.id is not None
    assert is_valid_uuid(team.id)
