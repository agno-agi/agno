from unittest.mock import MagicMock

import pytest

pytest.importorskip("ddgs")
pytest.importorskip("yfinance")

from agno.agent import Agent
from agno.metrics import MessageMetrics, RunMetrics
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._run import _asetup_session
from agno.team.team import Team
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools
from agno.utils.string import is_valid_uuid


@pytest.fixture
def team():
    web_agent = Agent(
        name="Web Agent",
        model=OpenAIChat("gpt-4o"),
        role="Search the web for information",
        tools=[WebSearchTools(cache_results=True)],
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
    """The roster renders one <member> element per member, id and name as attributes."""

    members_content = team.get_members_system_message_content()

    assert '<member id="web-agent" name="Web Agent">' in members_content
    assert "Role: Search the web for information" in members_content

    assert '<member id="finance-agent" name="Finance Agent">' in members_content
    assert "Role: Get financial data" in members_content

    assert members_content.count("<member ") == 2
    assert members_content.count("</member>") == 2

    # Tools are listed only when the team opts in, so the prompt never routes on
    # evidence the roster withheld.
    assert "Tools:" not in members_content
    team.add_member_tools_to_context = True
    assert "Tools: " in team.get_members_system_message_content()


def test_delegate_to_wrong_member(team):
    function = team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        run_context=RunContext(session_state={}, run_id="test-run", session_id="test-session"),
        team_run_context={},
    )
    response = list(function.entrypoint(member_id="wrong-agent", task="Get the current stock price of AAPL"))
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
    """An unnamed team gets a readable random id, not a raw UUID."""
    team = Team(
        members=[],
    )
    team.set_id()
    assert team.id is not None
    # generate_id_from_name falls back to a human-readable id when there is no name.
    assert not is_valid_uuid(team.id)
    assert team.id.count("-") >= 2 and team.id.islower()


def test_team_calculate_metrics_preserves_duration(team):
    """Test that _calculate_metrics preserves the duration from current_run_metrics."""

    initial_metrics = RunMetrics()
    initial_metrics.duration = 5.5
    initial_metrics.time_to_first_token = 0.5

    initial_metrics.input_tokens = 10
    initial_metrics.output_tokens = 20

    message_metrics = MessageMetrics()
    message_metrics.input_tokens = 10
    message_metrics.output_tokens = 20
    messages = [Message(role="assistant", content="Response", metrics=message_metrics)]

    # Pass the initial metrics (containing duration) to the calculation
    calculated = team._calculate_metrics(messages, current_run_metrics=initial_metrics)

    # Token counts are accumulated during the model call, so the running total is
    # carried forward rather than re-summed from the messages — counting both would
    # double every token on the run.
    assert calculated is initial_metrics
    assert calculated.input_tokens == 10
    assert calculated.output_tokens == 20

    # Duration should be preserved from initial_metrics
    assert calculated.duration == 5.5
    assert calculated.time_to_first_token == 0.5


def test_team_update_session_metrics_accumulates(team):
    """Test that _update_session_metrics correctly accumulates metrics using run_response."""

    session = TeamSession(session_id="test_session")
    session.session_data = {}

    # First Run
    run1 = TeamRunOutput(content="run 1")
    run1.metrics = RunMetrics()
    run1.metrics.duration = 2.0
    run1.metrics.input_tokens = 100

    team._update_session_metrics(session, run_response=run1)

    # session_data carries the serialized form, so metrics survive a round-trip to the DB.
    # SessionMetrics accumulates tokens and cost; duration stays a run-level metric.
    metrics1 = session.session_data["session_metrics"]
    assert metrics1["input_tokens"] == 100
    assert "duration" not in metrics1

    # Second Run
    run2 = TeamRunOutput(content="run 2")
    run2.metrics = RunMetrics()
    run2.metrics.duration = 3.0
    run2.metrics.input_tokens = 50

    # Should accumulate with previous session metrics
    team._update_session_metrics(session, run_response=run2)

    metrics2 = session.session_data["session_metrics"]

    assert metrics2["input_tokens"] == 150  # 100 + 50


@pytest.mark.asyncio
async def test_asetup_session_resolves_deps_after_state_loaded():
    """Verify callable dependencies are resolved AFTER session state is loaded from DB.

    This is a regression test: if dependency resolution runs before state loading,
    the callable won't see DB-stored session state values.
    """
    from unittest.mock import patch

    import agno.team._run as run_module

    # Create a session with DB-stored state
    db_session = TeamSession(session_id="test-session")
    db_session.session_data = {"session_state": {"from_db": "loaded"}}

    # Track the session_state snapshot at the time _aresolve_run_dependencies is called
    captured_state = {}

    async def capture_state_on_resolve(team, run_context):
        """Capture session_state at dep resolution time, then do actual resolution."""
        captured_state.update(run_context.session_state or {})

    # Create a minimal Team mock (only used to pass to the functions)
    team = MagicMock()

    run_context = RunContext(
        run_id="test-run",
        session_id="test-session",
        session_state={},
        dependencies={"some_dep": lambda: "value"},
    )

    # Mock the submodule functions at their source modules (where they're imported FROM)
    with (
        patch("agno.team._init._has_async_db", return_value=False),
        patch("agno.team._storage._read_or_create_session", return_value=db_session),
        patch("agno.team._storage._update_metadata", return_value=None),
        patch("agno.team._init._initialize_session_state", side_effect=lambda team, session_state, **kw: session_state),
        patch(
            "agno.team._storage._load_session_state",
            side_effect=lambda team, session, session_state: {
                **session_state,
                **session.session_data.get("session_state", {}),
            },
        ),
        patch.object(run_module, "_aresolve_run_dependencies", side_effect=capture_state_on_resolve),
    ):
        result_session = await _asetup_session(
            team=team,
            run_context=run_context,
            session_id="test-session",
            user_id=None,
            run_id="test-run",
        )

    assert result_session == db_session
    # At the time deps were resolved, session_state should already contain DB values
    assert captured_state.get("from_db") == "loaded"
    # And run_context.session_state should have the loaded value
    assert run_context.session_state["from_db"] == "loaded"
