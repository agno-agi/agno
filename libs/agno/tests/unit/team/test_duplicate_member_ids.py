"""Direct-member ids are a namespace-local primary key.

Duplicate ids — explicit or via get_member_id name fallback — must fail
closed at construction or factory resolution so HITL continue cannot
first-match approved args onto the wrong sibling.
"""

import pytest

from agno.agent import Agent
from agno.run import RunContext
from agno.team.team import Team
from agno.utils.callables import aresolve_callable_members, resolve_callable_members
from agno.utils.string import url_safe_string
from agno.utils.team import get_member_id, validate_unique_member_ids


def _run_context() -> RunContext:
    return RunContext(run_id="test-run", session_id="test-session")


def test_explicit_duplicate_ids_rejected_at_construction():
    with pytest.raises(ValueError, match="Duplicate member id") as exc_info:
        Team(
            name="Crew",
            members=[
                Agent(id="shared", name="Left"),
                Agent(id="shared", name="Right"),
            ],
        )

    message = str(exc_info.value)
    assert "shared" in message
    assert "Left" in message
    assert "Right" in message
    assert "Crew" in message


def test_name_fallback_collisions_rejected_at_construction():
    """url_safe_string maps Right Team / right_team / RightTeam to right-team."""
    assert url_safe_string("Right Team") == "right-team"
    assert url_safe_string("right_team") == "right-team"
    assert url_safe_string("RightTeam") == "right-team"
    assert get_member_id(Agent(name="Right Team")) == "right-team"
    assert get_member_id(Agent(name="right_team")) == "right-team"
    assert get_member_id(Agent(name="RightTeam")) == "right-team"

    with pytest.raises(ValueError, match="Duplicate member id") as exc_info:
        Team(
            name="Router Team",
            members=[
                Agent(name="Right Team"),
                Agent(name="right_team"),
            ],
        )

    message = str(exc_info.value)
    assert "right-team" in message
    assert "Right Team" in message
    assert "right_team" in message
    assert "normalized 'right-team'" in message

    with pytest.raises(ValueError, match="right-team"):
        Team(
            name="Router Team",
            members=[
                Agent(name="Right Team"),
                Agent(name="RightTeam"),
            ],
        )


def test_explicit_id_collides_with_name_fallback():
    with pytest.raises(ValueError, match="right-team"):
        Team(
            name="Crew",
            members=[
                Agent(id="right-team", name="Left"),
                Agent(name="Right Team"),
            ],
        )


def test_unique_member_ids_accepted():
    team = Team(
        name="Crew",
        members=[
            Agent(id="left", name="Left"),
            Agent(id="right", name="Right"),
        ],
    )
    assert [get_member_id(m) for m in team.members] == ["left", "right"]


def test_same_member_id_under_different_subteams_allowed():
    """Path identity disambiguates; uniqueness is per parent team."""
    left = Team(id="left-team", name="Left Team", members=[Agent(id="leaf", name="Left Leaf")])
    right = Team(id="right-team", name="Right Team", members=[Agent(id="leaf", name="Right Leaf")])
    root = Team(id="root", name="Root", members=[left, right])
    assert [get_member_id(m) for m in root.members] == ["left-team", "right-team"]
    assert get_member_id(left.members[0]) == "leaf"
    assert get_member_id(right.members[0]) == "leaf"


def test_callable_factory_duplicate_ids_rejected_before_delegation():
    def factory():
        return [Agent(id="dup", name="A"), Agent(id="dup", name="B")]

    team = Team(name="Dynamic", members=factory)
    with pytest.raises(ValueError, match="Duplicate member id") as exc_info:
        resolve_callable_members(team, _run_context())

    assert "dup" in str(exc_info.value)


def test_callable_factory_name_fallback_collision_rejected():
    def factory():
        return [Agent(name="Right Team"), Agent(name="right_team")]

    team = Team(name="Dynamic", members=factory)
    with pytest.raises(ValueError, match="right-team"):
        resolve_callable_members(team, _run_context())


@pytest.mark.asyncio
async def test_async_callable_factory_duplicate_ids_rejected():
    async def factory():
        return [Agent(id="dup", name="A"), Agent(id="dup", name="B")]

    team = Team(name="Dynamic", members=factory)
    with pytest.raises(ValueError, match="Duplicate member id"):
        await aresolve_callable_members(team, _run_context())


def test_set_id_collision_is_rejected():
    """name='RightTeam' becomes id 'rightteam' after set_id, colliding with an explicit id."""
    explicit = Agent(id="rightteam", name="Explicit")
    named = Agent(name="RightTeam")
    # Distinct at construction: explicit id vs url_safe_string("RightTeam") == "right-team"
    team = Team(name="Crew", members=[explicit, named])
    named.set_id()
    assert named.id == "rightteam"
    with pytest.raises(ValueError, match="rightteam"):
        validate_unique_member_ids(team.members, team_name=team.name)


def test_validate_unique_member_ids_reports_normalized_value():
    with pytest.raises(ValueError, match="normalized 'right-team'") as exc_info:
        validate_unique_member_ids(
            [Agent(name="Right Team"), Agent(name="right_team")],
            team_name="Router Team",
        )
    assert "Router Team" in str(exc_info.value)
