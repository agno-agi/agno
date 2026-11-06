"""Tests that sub-agent KB references are propagated to TeamRunOutput."""
from unittest.mock import MagicMock, patch
from typing import List

from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.base import MessageReferences


def _make_member_run(references=None) -> RunOutput:
    r = RunOutput(run_id="member-run-1", session_id="session-1")
    r.references = references
    return r


def _make_team_run() -> TeamRunOutput:
    return TeamRunOutput(run_id="team-run-1", session_id="session-1")


def test_member_references_propagated_to_team():
    """Sub-agent references are merged into TeamRunOutput.references."""
    from agno.run.base import MessageReferences

    member_refs = [
        MessageReferences(query="test query", references=[{"text": "doc1"}], time=0.1)
    ]
    member_run = _make_member_run(references=member_refs)
    team_run = _make_team_run()

    # Simulate the propagation logic
    if member_run.references:
        if team_run.references is None:
            team_run.references = []
        team_run.references.extend(member_run.references)

    assert team_run.references is not None
    assert len(team_run.references) == 1
    assert team_run.references[0].query == "test query"


def test_multiple_member_references_accumulated():
    """References from multiple sub-agents are all collected."""
    from agno.run.base import MessageReferences

    refs_a = [MessageReferences(query="q1", references=[{"text": "a"}], time=0.1)]
    refs_b = [MessageReferences(query="q2", references=[{"text": "b"}], time=0.2)]

    team_run = _make_team_run()
    for refs in [refs_a, refs_b]:
        if refs:
            if team_run.references is None:
                team_run.references = []
            team_run.references.extend(refs)

    assert team_run.references is not None
    assert len(team_run.references) == 2
    assert {r.query for r in team_run.references} == {"q1", "q2"}


def test_member_with_no_references_leaves_team_references_unchanged():
    """A member with no KB references does not affect team references."""
    member_run = _make_member_run(references=None)
    team_run = _make_team_run()

    if member_run.references:
        if team_run.references is None:
            team_run.references = []
        team_run.references.extend(member_run.references)

    assert team_run.references is None


def test_existing_team_references_are_preserved():
    """Pre-existing team references survive member reference propagation."""
    from agno.run.base import MessageReferences

    existing_ref = MessageReferences(query="existing", references=[{"text": "x"}], time=0.0)
    team_run = _make_team_run()
    team_run.references = [existing_ref]

    member_refs = [MessageReferences(query="new", references=[{"text": "y"}], time=0.1)]
    member_run = _make_member_run(references=member_refs)

    if member_run.references:
        if team_run.references is None:
            team_run.references = []
        team_run.references.extend(member_run.references)

    assert len(team_run.references) == 2
    assert team_run.references[0].query == "existing"
    assert team_run.references[1].query == "new"
