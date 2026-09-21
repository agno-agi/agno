"""Session hand-off from a team to its delegated sub-teams.

Sub-teams skip the database read in ``_read_or_create_session()`` so that only the root team
owns persistence. Without an in-memory hand-off that leaves a sub-team with ``runs=[]``, so it
cannot resolve history for its own members and nested delegation (Root -> Middle -> Leaf) runs
with no multi-turn context.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.agent.agent import Agent
from agno.models.message import Message
from agno.run.base import RunContext, RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._default_tools import _get_delegate_task_function
from agno.team._storage import (
    _aread_or_create_session,
    _hand_session_to_sub_team,
    _read_or_create_session,
    _release_session_from_sub_team,
)
from agno.team._tools import _get_history_for_member_agent
from agno.team.team import Team

SESSION_ID = "shared-session"


def _root_session() -> TeamSession:
    """A root session holding one finished turn of Root -> Middle -> Leaf delegation."""
    leaf_run = TeamRunOutput(
        run_id="leaf-run-1",
        team_id="leaf-team",
        parent_run_id="middle-run-1",
        session_id=SESSION_ID,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Leaf request"),
            Message(role="assistant", content="Leaf response"),
        ],
    )
    middle_run = TeamRunOutput(
        run_id="middle-run-1",
        team_id="middle-team",
        parent_run_id="root-run-1",
        session_id=SESSION_ID,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Middle request"),
            Message(role="assistant", content="Middle response"),
        ],
        member_responses=[leaf_run],
    )
    root_run = TeamRunOutput(
        run_id="root-run-1",
        team_id="root-team",
        session_id=SESSION_ID,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Root request"),
            Message(role="assistant", content="Root response"),
        ],
        member_responses=[middle_run],
    )
    return TeamSession(session_id=SESSION_ID, team_id="root-team", runs=[root_run])


def _leaf_team() -> Team:
    return Team(id="leaf-team", name="Leaf Team", members=[], add_history_to_context=True)


def _middle_team(leaf: Team) -> Team:
    middle = Team(id="middle-team", name="Middle Team", members=[leaf], add_history_to_context=True)
    # Set by _initialize_member() when the root team delegates to this sub-team.
    middle.parent_team_id = "root-team"
    return middle


class TestSubTeamSessionHandOff:
    def test_sub_team_session_starts_empty_without_hand_off(self):
        """Baseline: a sub-team never reads the database, so its session has no runs."""
        middle = _middle_team(_leaf_team())

        session = _read_or_create_session(middle, session_id=SESSION_ID)

        assert not session.runs

    def test_hand_off_seeds_sub_team_session_with_parent_runs(self):
        """After the hand-off the sub-team sees the shared run tree."""
        root_session = _root_session()
        middle = _middle_team(_leaf_team())

        _hand_session_to_sub_team(middle, root_session)
        session = _read_or_create_session(middle, session_id=SESSION_ID)

        assert [run.run_id for run in session.runs] == ["root-run-1"]  # type: ignore[union-attr]

    def test_sub_team_resolves_history_for_its_own_member(self):
        """The depth-2 case from the report: Middle must find Leaf's history."""
        root_session = _root_session()
        leaf = _leaf_team()
        middle = _middle_team(leaf)

        _hand_session_to_sub_team(middle, root_session)
        middle_session = _read_or_create_session(middle, session_id=SESSION_ID)
        history = _get_history_for_member_agent(middle, middle_session, leaf)

        assert [message.content for message in history] == ["Leaf request", "Leaf response"]

    def test_sub_team_finds_no_history_without_hand_off(self):
        """Without the hand-off the same lookup returns nothing."""
        leaf = _leaf_team()
        middle = _middle_team(leaf)

        middle_session = _read_or_create_session(middle, session_id=SESSION_ID)

        assert _get_history_for_member_agent(middle, middle_session, leaf) == []

    def test_sub_team_runs_do_not_leak_into_the_parent_session(self):
        """The sub-team gets its own run list, so it cannot write into the parent's session."""
        root_session = _root_session()
        middle = _middle_team(_leaf_team())

        _hand_session_to_sub_team(middle, root_session)
        middle_session = _read_or_create_session(middle, session_id=SESSION_ID)
        middle_session.upsert_run(TeamRunOutput(run_id="middle-run-2", team_id="middle-team", session_id=SESSION_ID))

        assert [run.run_id for run in root_session.runs] == ["root-run-1"]  # type: ignore[union-attr]
        assert [run.run_id for run in middle_session.runs] == ["root-run-1", "middle-run-2"]  # type: ignore[union-attr]

    def test_hand_off_is_idempotent(self):
        """Re-reading the session must not duplicate the parent's runs."""
        root_session = _root_session()
        middle = _middle_team(_leaf_team())
        middle.cache_session = True

        _hand_session_to_sub_team(middle, root_session)
        _read_or_create_session(middle, session_id=SESSION_ID)
        session = _read_or_create_session(middle, session_id=SESSION_ID)

        assert [run.run_id for run in session.runs] == ["root-run-1"]  # type: ignore[union-attr]

    def test_cached_sub_team_session_picks_up_new_parent_runs(self):
        """A cached sub-team session is refreshed from the parent between turns."""
        root_session = _root_session()
        middle = _middle_team(_leaf_team())
        middle.cache_session = True

        _hand_session_to_sub_team(middle, root_session)
        _read_or_create_session(middle, session_id=SESSION_ID)

        root_session.upsert_run(TeamRunOutput(run_id="root-run-2", team_id="root-team", session_id=SESSION_ID))
        session = _read_or_create_session(middle, session_id=SESSION_ID)

        assert [run.run_id for run in session.runs] == ["root-run-1", "root-run-2"]  # type: ignore[union-attr]

    def test_release_clears_the_reference(self):
        """The parent session is not kept alive after the delegated run finishes."""
        root_session = _root_session()
        middle = _middle_team(_leaf_team())

        _hand_session_to_sub_team(middle, root_session)
        _release_session_from_sub_team(middle)

        assert middle._delegated_session is None
        assert not _read_or_create_session(middle, session_id=SESSION_ID).runs

    def test_agent_members_are_not_handed_a_team_session(self):
        """Only sub-teams get the hand-off; agents receive history through their input."""
        agent = Agent(id="member-agent", name="Member Agent")

        _hand_session_to_sub_team(agent, _root_session())
        _release_session_from_sub_team(agent)

        assert not hasattr(agent, "_delegated_session")

    def test_root_team_is_not_affected(self):
        """A team that is not delegated to keeps loading its own session."""
        root_session = _root_session()
        root = Team(id="root-team", name="Root Team", members=[])

        _hand_session_to_sub_team(root, root_session)
        session = _read_or_create_session(root, session_id=SESSION_ID)

        assert not session.runs

    def test_a_different_session_id_is_never_seeded(self):
        """The hand-off only applies to the session the parent is actually running."""
        root_session = _root_session()
        middle = _middle_team(_leaf_team())

        _hand_session_to_sub_team(middle, root_session)
        session = _read_or_create_session(middle, session_id="some-other-session")

        assert not session.runs

    @pytest.mark.asyncio
    async def test_async_hand_off_seeds_sub_team_session(self):
        """The async delegation path behaves like the sync one."""
        root_session = _root_session()
        leaf = _leaf_team()
        middle = _middle_team(leaf)

        _hand_session_to_sub_team(middle, root_session)
        middle_session = await _aread_or_create_session(middle, session_id=SESSION_ID)
        history = _get_history_for_member_agent(middle, middle_session, leaf)

        assert [message.content for message in history] == ["Leaf request", "Leaf response"]


class TestBorrowedRunsAreGivenBack:
    """With ``cache_session=True`` the merge writes into the cached session itself, so the
    borrowed runs have to be removed again when the delegated run ends - otherwise they
    outlive the delegation and show up in the sub-team's own session."""

    @staticmethod
    def _cached_middle_team() -> Team:
        middle = _middle_team(_leaf_team())
        middle.cache_session = True
        middle._cached_session = TeamSession(
            session_id=SESSION_ID,
            team_id="middle-team",
            runs=[
                TeamRunOutput(
                    run_id="middle-own-run",
                    team_id="middle-team",
                    session_id=SESSION_ID,
                    status=RunStatus.completed,
                )
            ],
        )
        return middle

    def test_release_takes_the_borrowed_runs_back_out_of_the_cache(self):
        middle = self._cached_middle_team()
        root_session = _root_session()

        _hand_session_to_sub_team(middle, root_session)
        assert [run.run_id for run in _read_or_create_session(middle, session_id=SESSION_ID).runs] == [
            "root-run-1",
            "middle-own-run",
        ]

        _release_session_from_sub_team(middle)

        # The sub-team keeps its own run and gives the parent's run back.
        assert [run.run_id for run in middle._cached_session.runs] == ["middle-own-run"]
        assert [run.run_id for run in _read_or_create_session(middle, session_id=SESSION_ID).runs] == ["middle-own-run"]

    def test_parent_runs_do_not_leak_into_a_later_standalone_read(self):
        middle = self._cached_middle_team()

        _hand_session_to_sub_team(middle, _root_session())
        _read_or_create_session(middle, session_id=SESSION_ID)
        _release_session_from_sub_team(middle)

        session = _read_or_create_session(middle, session_id=SESSION_ID)

        assert all(run.team_id == "middle-team" for run in session.runs)

    def test_a_missing_release_is_repaired_by_the_next_hand_off(self):
        """A member run that raises something other than RunCancelledException skips the
        release, so the next hand-off has to clean up before borrowing again."""
        middle = self._cached_middle_team()

        _hand_session_to_sub_team(middle, _root_session())
        _read_or_create_session(middle, session_id=SESSION_ID)
        # ... delegated run blows up here, so _release_session_from_sub_team() never runs.

        _hand_session_to_sub_team(middle, _root_session())
        _release_session_from_sub_team(middle)

        assert [run.run_id for run in middle._cached_session.runs] == ["middle-own-run"]


class TestDelegationWiresTheHandOff:
    """The delegation tool itself must perform (and undo) the hand-off."""

    @staticmethod
    def _delegation_fixture():
        leaf = _leaf_team()
        middle = Team(id="middle-team", name="Middle Team", members=[leaf], add_history_to_context=True)
        root = Team(id="root-team", name="Root Team", members=[middle])
        session = _root_session()
        run_response = TeamRunOutput(run_id="root-run-2", team_id="root-team", session_id=SESSION_ID)
        run_context = RunContext(run_id="root-run-2", session_id=SESSION_ID, session_state={})
        return leaf, middle, root, session, run_response, run_context

    def test_delegation_hands_the_session_to_the_sub_team(self):
        leaf, middle, root, session, run_response, run_context = self._delegation_fixture()
        observed = {}

        def fake_run(*args, **kwargs):
            middle_session = _read_or_create_session(middle, session_id=SESSION_ID)
            observed["handed"] = middle._delegated_session
            observed["leaf_history"] = [
                message.content for message in _get_history_for_member_agent(middle, middle_session, leaf)
            ]
            return TeamRunOutput(run_id="middle-run-2", team_id="middle-team", session_id=SESSION_ID, content="done")

        middle.run = fake_run  # type: ignore[method-assign]

        delegate = _get_delegate_task_function(
            root,
            run_response=run_response,
            run_context=run_context,
            session=session,
            team_run_context={},
            stream=False,
            async_mode=False,
        )
        assert list(delegate.entrypoint(member_id="middle-team", task="do it")) == ["done"]

        assert observed["handed"] is session
        assert observed["leaf_history"] == ["Leaf request", "Leaf response"]
        assert middle._delegated_session is None

    @pytest.mark.asyncio
    async def test_async_delegation_hands_the_session_to_the_sub_team(self):
        leaf, middle, root, session, run_response, run_context = self._delegation_fixture()
        observed = {}

        async def fake_arun(*args, **kwargs):
            middle_session = await _aread_or_create_session(middle, session_id=SESSION_ID)
            observed["handed"] = middle._delegated_session
            observed["leaf_history"] = [
                message.content for message in _get_history_for_member_agent(middle, middle_session, leaf)
            ]
            return TeamRunOutput(run_id="middle-run-2", team_id="middle-team", session_id=SESSION_ID, content="done")

        middle.arun = fake_arun  # type: ignore[method-assign]

        delegate = _get_delegate_task_function(
            root,
            run_response=run_response,
            run_context=run_context,
            session=session,
            team_run_context={},
            stream=False,
            async_mode=True,
        )
        results = [chunk async for chunk in delegate.entrypoint(member_id="middle-team", task="do it")]

        assert results == ["done"]
        assert observed["handed"] is session
        assert observed["leaf_history"] == ["Leaf request", "Leaf response"]
        assert middle._delegated_session is None
