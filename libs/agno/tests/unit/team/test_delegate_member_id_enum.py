"""
Unit tests for constraining `delegate_task_to_member`'s `member_id` argument to
an enum of the team's actually-delegatable member IDs.

Without this, `member_id` is a free-text string and a model can hallucinate an
ID that was never in the team (e.g. confusing a routing/classification label
with a member name), which fails at call time with "Member with ID ... not
found" instead of being constrained up front by the tool schema.
"""

from agno.agent.agent import Agent
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._tools import _get_delegatable_member_ids
from agno.team.team import Team


def _run_context() -> RunContext:
    return RunContext(session_state={}, run_id="test-run", session_id="test-session")


def test_get_delegatable_member_ids_flat_team():
    team = Team(
        name="Flat Team",
        members=[
            Agent(name="Billing Agent", id="billing-agent"),
            Agent(name="Fulfilment Agent", id="fulfilment-agent"),
            Agent(name="Assurance Agent", id="assurance-agent"),
        ],
    )

    assert _get_delegatable_member_ids(team, run_context=_run_context()) == [
        "billing-agent",
        "fulfilment-agent",
        "assurance-agent",
    ]


def test_get_delegatable_member_ids_includes_nested_subteam_members():
    sub_team = Team(
        name="Sub Team",
        id="sub-team",
        members=[
            Agent(name="Nested Agent A", id="nested-agent-a"),
            Agent(name="Nested Agent B", id="nested-agent-b"),
        ],
    )
    team = Team(
        name="Parent Team",
        members=[
            Agent(name="Top Agent", id="top-agent"),
            sub_team,
        ],
    )

    member_ids = _get_delegatable_member_ids(team, run_context=_run_context())

    # The subteam itself is delegatable (as a single unit) ...
    assert "top-agent" in member_ids
    assert "sub-team" in member_ids
    # ... and so are its own members, since _find_member_by_id recurses into subteams.
    assert "nested-agent-a" in member_ids
    assert "nested-agent-b" in member_ids


def test_get_delegatable_member_ids_empty_team_returns_empty_list():
    team = Team(name="Empty Team", members=[])

    assert _get_delegatable_member_ids(team, run_context=_run_context()) == []


def test_delegate_task_to_member_schema_has_member_id_enum():
    team = Team(
        name="Router Team",
        members=[
            Agent(name="Billing Agent", id="billing-agent"),
            Agent(name="Fulfilment Agent", id="fulfilment-agent"),
        ],
    )

    function = team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        run_context=_run_context(),
        team_run_context={},
    )

    assert function.parameters["properties"]["member_id"]["enum"] == [
        "billing-agent",
        "fulfilment-agent",
    ]


def test_delegate_task_to_member_still_rejects_ids_outside_the_enum():
    """The enum steers the model, but the runtime check remains the source of truth."""
    team = Team(
        name="Router Team",
        members=[Agent(name="Billing Agent", id="billing-agent")],
    )

    function = team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        run_context=_run_context(),
        team_run_context={},
    )

    response = list(function.entrypoint(member_id="non-billing-agent", task="Do the thing"))
    assert "Member with ID non-billing-agent not found in the team or any subteams" in response[0]


def test_delegate_task_to_members_plural_mode_has_no_member_id_param():
    """delegate_to_all_members=True fans out to every member — there's no member_id
    argument to constrain, so the enum injection must not run (and must not crash)."""
    team = Team(
        name="Fan-out Team",
        members=[
            Agent(name="Billing Agent", id="billing-agent"),
            Agent(name="Fulfilment Agent", id="fulfilment-agent"),
        ],
        delegate_to_all_members=True,
    )

    function = team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        run_context=_run_context(),
        team_run_context={},
    )

    assert "member_id" not in function.parameters["properties"]
