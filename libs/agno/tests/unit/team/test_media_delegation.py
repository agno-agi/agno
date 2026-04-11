"""Tests for team media merge into delegated member kwargs."""

from agno.media import Image
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.session.team import TeamSession
from agno.team._media_delegation import merge_team_media_for_delegation
from agno.team.team import Team


def _team(**kwargs) -> Team:
    return Team(members=[], id="team-1", **kwargs)


def test_flag_off_returns_current_only():
    team = _team(add_team_media_to_delegation=False)
    session = TeamSession(session_id="s1", runs=[])
    cur = Image(url="https://example.com/current.png")
    imgs, v, a, f = merge_team_media_for_delegation(
        team, session, "run-1", images=[cur], videos=None, audio=None, files=None
    )
    assert len(imgs) == 1
    assert imgs[0].url == "https://example.com/current.png"


def test_merges_prior_team_run_input_media():
    team = _team(add_team_media_to_delegation=True, num_history_runs=5)
    old = Image(url="https://example.com/old.png")
    prev = TeamRunOutput(
        run_id="run-prev",
        team_id=team.id,
        status=RunStatus.completed,
        input=TeamRunInput(input_content="past", images=[old]),
    )
    session = TeamSession(session_id="s1", runs=[prev])
    cur = Image(url="https://example.com/current.png")
    imgs, _, _, _ = merge_team_media_for_delegation(
        team, session, "run-now", images=[cur], videos=None, audio=None, files=None
    )
    assert len(imgs) == 2
    assert imgs[0].url == "https://example.com/current.png"
    assert imgs[1].url == "https://example.com/old.png"


def test_excludes_current_run_from_history_sources():
    team = _team(add_team_media_to_delegation=True, num_history_runs=5)
    same = Image(url="https://example.com/same.png")
    current = TeamRunOutput(
        run_id="run-now",
        team_id=team.id,
        status=RunStatus.running,
        input=TeamRunInput(input_content="x", images=[same]),
    )
    session = TeamSession(session_id="s1", runs=[current])
    imgs, _, _, _ = merge_team_media_for_delegation(
        team, session, "run-now", images=[same], videos=None, audio=None, files=None
    )
    assert len(imgs) == 1


def test_deduplicates_same_url():
    team = _team(add_team_media_to_delegation=True, num_history_runs=5)
    shared = Image(url="https://example.com/x.png")
    prev = TeamRunOutput(
        run_id="run-prev",
        team_id=team.id,
        status=RunStatus.completed,
        input=TeamRunInput(input_content="past", images=[shared]),
    )
    session = TeamSession(session_id="s1", runs=[prev])
    imgs, _, _, _ = merge_team_media_for_delegation(
        team, session, "run-now", images=[shared], videos=None, audio=None, files=None
    )
    assert len(imgs) == 1


def test_team_message_attachments():
    team = _team(add_team_media_to_delegation=True, num_history_runs=5)
    msg_img = Image(url="https://example.com/from-msg.png")
    tr = TeamRunOutput(
        run_id="run-1",
        team_id=team.id,
        status=RunStatus.completed,
        input=TeamRunInput(input_content="hi"),
        messages=[Message(role="user", content="see", images=[msg_img])],
    )
    session = TeamSession(session_id="s1", runs=[tr])
    imgs, _, _, _ = merge_team_media_for_delegation(
        team, session, "run-2", images=[], videos=None, audio=None, files=None
    )
    assert len(imgs) == 1
    assert imgs[0].url == "https://example.com/from-msg.png"
