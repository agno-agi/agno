"""Team.__init__ is keyword-only after members.

Positional arguments past members would otherwise silently rebind whenever a
parameter is added mid-signature.
"""

import pytest

from agno.agent import Agent
from agno.team import Team


def test_members_stays_positional():
    team = Team([Agent(name="member")])
    assert team.members is not None


def test_params_after_members_are_keyword_only():
    with pytest.raises(TypeError):
        Team([Agent(name="member")], "some-id")  # type: ignore[misc]


def test_keyword_construction_unchanged():
    team = Team(members=[Agent(name="member")], id="some-id", name="team")
    assert team.id == "some-id"
    assert team.name == "team"
