"""
Unit tests for constraining `delegate_task_to_member`'s `member_id` argument to
an enum of the team's direct member IDs.

Without this, `member_id` is a free-text string and a model can hallucinate an
ID that was never in the team (e.g. confusing a routing/classification label
with a member name), which fails at call time with "Member with ID ... not
found" instead of being constrained up front by the tool schema.
"""

from agno.agent.agent import Agent
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.team import Team


def _delegate_function(team: Team):
    return team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        run_context=RunContext(session_state={}, run_id="test-run", session_id="test-session"),
        team_run_context={},
    )


def test_delegate_task_to_member_schema_has_member_id_enum():
    team = Team(
        name="Router Team",
        members=[
            Agent(name="Billing Agent", id="billing-agent"),
            Agent(name="Fulfilment Agent", id="fulfilment-agent"),
            Agent(name="Assurance Agent", id="assurance-agent"),
        ],
    )

    function = _delegate_function(team)

    assert function.parameters["properties"]["member_id"]["enum"] == [
        "billing-agent",
        "fulfilment-agent",
        "assurance-agent",
    ]


def test_member_id_enum_excludes_inner_subteam_members():
    """Only direct members are delegable by this leader, matching the roster, which hides inner ids."""
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
        members=[Agent(name="Top Agent", id="top-agent"), sub_team],
    )

    function = _delegate_function(team)

    assert function.parameters["properties"]["member_id"]["enum"] == ["top-agent", "sub-team"]


def test_empty_team_has_no_member_id_enum():
    team = Team(name="Empty Team", members=[])

    function = _delegate_function(team)

    assert "enum" not in function.parameters["properties"]["member_id"]


def test_delegate_task_to_member_still_rejects_ids_outside_the_enum():
    """The enum steers the model, but the runtime check remains the source of truth."""
    team = Team(
        name="Router Team",
        members=[Agent(name="Billing Agent", id="billing-agent")],
    )

    function = _delegate_function(team)

    response = list(function.entrypoint(member_id="non-billing-agent", task="Do the thing"))
    assert "Member with ID non-billing-agent not found in the team or any subteams" in response[0]


def test_delegate_task_to_members_plural_mode_has_no_member_id_param():
    """delegate_to_all_members=True fans out to every member, so there is no member_id to constrain."""
    team = Team(
        name="Fan-out Team",
        members=[
            Agent(name="Billing Agent", id="billing-agent"),
            Agent(name="Fulfilment Agent", id="fulfilment-agent"),
        ],
        delegate_to_all_members=True,
    )

    function = _delegate_function(team)

    assert "member_id" not in function.parameters["properties"]
