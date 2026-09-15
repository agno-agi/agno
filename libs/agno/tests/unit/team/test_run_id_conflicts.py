"""A team run cannot write over a stored run that is not its own.

``run_id`` can be supplied by the caller, and storage used to accept a
conflicting one as an update, replacing a stored run that may belong to
another session or user. Creation is now a strict insert, and every write
after it is scoped to the run's own session, effective user and component:
a run handed an id that is already taken executes and returns normally, and
its save is refused instead of landing on the stored run.
"""

import asyncio
import time
from typing import Any, AsyncIterator, Iterator, Optional

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team._storage import _upsert_run
from agno.team.team import Team


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self, content: str = "ok"):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(content=content, role="assistant", response_usage=MessageMetrics())

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._mock_response

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._mock_response

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._mock_response
        return

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._mock_response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._mock_response


def _make_team(db: Any, response: str = "ok", **kwargs) -> Team:
    """A team whose model answers ``response``, so a landed write is recognisable."""
    return Team(
        name="test-team",
        id="test-team",
        members=[],
        model=MockModel(response),
        db=db,
        telemetry=False,
        **kwargs,
    )


def _stored(db: Any, run_id: str) -> Optional[dict]:
    row = db.get_run(run_id, deserialize=False)
    if row is None:
        return None
    return row.get("run_data") or row


def _owner(db: Any, run_id: str) -> Optional[str]:
    """The user the stored run belongs to, whichever row shape came back."""
    row = db.get_run(run_id, deserialize=False) or {}
    return row.get("user_id") or (row.get("run_data") or {}).get("user_id")


@pytest.fixture(params=["in_memory", "sqlite"])
def db(request, tmp_path):
    if request.param == "in_memory":
        return InMemoryDb()
    return SqliteDb(db_file=str(tmp_path / "runs.db"))


class TestNormalRuns:
    def test_a_generated_id_still_persists(self, db):
        team = _make_team(db)

        result = team.run("hi", session_id="s1")

        assert _stored(db, result.run_id) is not None
        assert _stored(db, result.run_id)["status"] == RunStatus.completed.value

    def test_an_explicit_fresh_id_still_persists(self, db):
        team = _make_team(db)

        result = team.run("hi", session_id="s1", run_id="chosen")

        assert result.run_id == "chosen"
        assert _stored(db, "chosen")["status"] == RunStatus.completed.value

    def test_two_turns_in_one_session_both_persist(self, db):
        team = _make_team(db)

        first = team.run("one", session_id="s1")
        second = team.run("two", session_id="s1")

        assert first.run_id != second.run_id
        assert _stored(db, first.run_id) is not None
        assert _stored(db, second.run_id) is not None

    @pytest.mark.asyncio
    async def test_async_runs_still_persist(self, db):
        team = _make_team(db)

        result = await team.arun("hi", session_id="s1")

        assert _stored(db, result.run_id)["status"] == RunStatus.completed.value

    @pytest.mark.asyncio
    async def test_background_runs_still_reach_a_terminal_status(self, db):
        team = _make_team(db)

        result = await team.arun("hi", session_id="s1", background=True)
        # Poll to a TERMINAL status: the run passes through RUNNING on its way,
        # and breaking on the first non-initial status raced that transition
        terminal = {RunStatus.completed.value, RunStatus.error.value, RunStatus.cancelled.value}
        deadline = time.monotonic() + 10
        while True:
            row = _stored(db, result.run_id)
            assert row is not None, "the background run stored no row"
            if row["status"] in terminal:
                break
            assert time.monotonic() < deadline, f"background run stuck at {row['status']}"
            await asyncio.sleep(0.01)

        assert row["status"] == RunStatus.completed.value
        assert row["content"] == "ok"

    def test_a_streaming_run_still_persists(self, db):
        team = _make_team(db)

        events = list(team.run("hi", session_id="s1", run_id="streamed", stream=True))

        assert events
        assert _stored(db, "streamed")["status"] == RunStatus.completed.value
        assert _stored(db, "streamed")["content"] == "ok"

    @pytest.mark.asyncio
    async def test_an_async_streaming_run_still_persists(self, db):
        team = _make_team(db)

        events = [event async for event in team.arun("hi", session_id="s1", run_id="streamed", stream=True)]

        assert events
        assert _stored(db, "streamed")["status"] == RunStatus.completed.value


class TestConflictingIds:
    """A run whose id is taken runs to completion; only its save is refused.

    Each refusal asserts the STORED run: its content is still the victim's,
    and every case that names a user asserts its owner is unchanged. That is
    the property worth having -- whether the intruding run itself succeeded is
    the caller's business, but the stored run belongs to somebody else. The
    last case here is the deliberate exception, where the scope the write
    presents is the stored row's own and the write lands.
    """

    def test_the_run_completes_even_though_its_save_is_refused(self, db):
        _make_team(db).run("victim turn", session_id="victim", user_id="victim-user", run_id="taken")

        result = _make_team(db, response="attacker").run(
            "attacker turn", session_id="attacker", user_id="attacker-user", run_id="taken"
        )

        assert result.status == RunStatus.completed
        assert result.content == "attacker"
        assert _stored(db, "taken")["content"] == "ok"
        assert _owner(db, "taken") == "victim-user"

    def test_another_user_in_the_same_session_cannot_overwrite_the_stored_run(self, db):
        _make_team(db).run("victim turn", session_id="s1", user_id="victim-user", run_id="taken")
        original = _stored(db, "taken")

        _make_team(db, response="attacker").run(
            "attacker turn", session_id="s1", user_id="attacker-user", run_id="taken"
        )

        assert _stored(db, "taken") == original
        assert _stored(db, "taken")["content"] == "ok"
        assert _owner(db, "taken") == "victim-user"

    def test_another_session_cannot_overwrite_the_stored_run(self, db):
        _make_team(db).run("victim turn", session_id="victim", user_id="u1", run_id="taken")
        original = _stored(db, "taken")

        _make_team(db, response="attacker").run("attacker turn", session_id="attacker", user_id="u1", run_id="taken")

        assert _stored(db, "taken") == original
        assert _stored(db, "taken")["content"] == "ok"
        assert _owner(db, "taken") == "u1"

    def test_another_session_cannot_claim_an_anonymous_stored_run(self, db):
        """The session refuses this write; naming a user would not have.

        An unowned row is adopted by the first write that knows a user, so in
        the stored row's own session this caller would land and the row would
        become theirs. Here the sessions differ, which is the fact the refusal
        rests on, and being unowned does not soften it: an anonymous row is no
        more reachable from another session than an owned one.
        """
        _make_team(db).run("victim turn", session_id="victim", run_id="taken")
        original = _stored(db, "taken")

        _make_team(db, response="attacker").run(
            "attacker turn", session_id="attacker", user_id="attacker-user", run_id="taken"
        )

        assert _stored(db, "taken") == original
        assert _stored(db, "taken")["content"] == "ok"
        assert _owner(db, "taken") is None

    def test_two_identity_less_callers_cannot_overwrite_each_other(self, db):
        _make_team(db).run("first", session_id="s1", run_id="taken")
        original = _stored(db, "taken")

        _make_team(db, response="attacker").run("second", session_id="s2", run_id="taken")

        assert _stored(db, "taken") == original
        assert _stored(db, "taken")["content"] == "ok"

    def test_the_runs_own_owner_and_session_still_reach_its_row(self, db):
        """The deliberate limit of the scope, and why the boundary is where it is.

        A save presenting the row's own session and owner is exactly what a
        pause, a resume and a terminal write present, so it has to land. A
        reused id inside one owner's own session is therefore indistinguishable
        from that run saving again, and lands too.
        """
        team = _make_team(db)
        team.run("first", session_id="s1", user_id="u1", run_id="taken")

        _make_team(db, response="second").run("second", session_id="s1", user_id="u1", run_id="taken")

        assert _stored(db, "taken")["content"] == "second"
        assert _owner(db, "taken") == "u1"


class TestComponentIdentity:
    """A team and an agent never share a run row, even inside one session.

    The component ids are part of the scope, so neither one's save can reach
    a row the other created. Both directions go through the team's own save
    helper, which is the path every lifecycle write takes.
    """

    def test_a_team_run_cannot_overwrite_an_agents_row(self, db):
        team = _make_team(db)
        team.run("seed", session_id="s1")
        agent_run = RunOutput(run_id="shared", session_id="s1", agent_id="member-agent", content="agent output")
        _upsert_run(team, run=agent_run, session_id="s1", run_index=1)

        team_run = TeamRunOutput(run_id="shared", session_id="s1", team_id=team.id, content="team output")
        _upsert_run(team, run=team_run, session_id="s1")

        assert _stored(db, "shared")["content"] == "agent output"

    def test_an_agent_run_cannot_overwrite_a_teams_row(self, db):
        team = _make_team(db)
        parent = team.run("hi", session_id="s1")

        agent_run = RunOutput(
            run_id=parent.run_id,
            session_id="s1",
            agent_id="member-agent",
            parent_run_id=parent.run_id,
            content="agent output",
        )
        _upsert_run(team, run=agent_run, session_id="s1")

        assert _stored(db, parent.run_id)["content"] == "ok"


class TestLifecycleAfterTheFirstSave:
    """Transitions written after the run's own row exists go through the
    scoped update, which is what the HITL, resume, background and terminal
    paths all reach."""

    def _stored_run(self, db: Any, session_id: str = "s1", user_id: Optional[str] = None) -> tuple:
        team = _make_team(db)
        # A real turn first, so the run rows have the session row they attach to
        team.run("seed", session_id=session_id, user_id=user_id)
        run = TeamRunOutput(
            run_id="r1",
            session_id=session_id,
            team_id=team.id,
            user_id=user_id,
            status=RunStatus.running,
        )
        _upsert_run(team, run=run, session_id=session_id, user_id=user_id, run_index=1)
        return team, run

    def test_pause_then_resume_then_completion_all_land(self, db):
        team, run = self._stored_run(db, user_id="u1")

        run.status = RunStatus.paused
        _upsert_run(team, run=run, session_id="s1", user_id="u1")
        assert _stored(db, "r1")["status"] == RunStatus.paused.value

        run.status = RunStatus.running
        _upsert_run(team, run=run, session_id="s1", user_id="u1")
        assert _stored(db, "r1")["status"] == RunStatus.running.value

        run.status = RunStatus.completed
        run.content = "done"
        _upsert_run(team, run=run, session_id="s1", user_id="u1")
        assert _stored(db, "r1")["status"] == RunStatus.completed.value
        assert _stored(db, "r1")["content"] == "done"

    def test_a_resume_by_another_user_is_refused(self, db):
        team, run = self._stored_run(db, user_id="u1")
        run.status = RunStatus.paused
        _upsert_run(team, run=run, session_id="s1", user_id="u1")
        paused = _stored(db, "r1")

        run.content = "attacker"
        run.status = RunStatus.completed
        _upsert_run(team, run=run, session_id="s1", user_id="attacker")

        assert _stored(db, "r1") == paused

    def test_a_resume_from_another_session_is_refused(self, db):
        team, run = self._stored_run(db, user_id="u1")
        run.status = RunStatus.paused
        _upsert_run(team, run=run, session_id="s1", user_id="u1")
        paused = _stored(db, "r1")

        run.content = "attacker"
        run.status = RunStatus.completed
        _upsert_run(team, run=run, session_id="attacker-session", user_id="u1")

        assert _stored(db, "r1") == paused

    def test_a_save_for_a_run_that_was_never_stored_still_creates_it(self, db):
        """A forked run, and every other path whose first write is its only one."""
        team = _make_team(db)
        team.run("seed", session_id="s1")
        run = TeamRunOutput(run_id="unstored", session_id="s1", team_id=team.id, content="forked")

        _upsert_run(team, run=run, session_id="s1", run_index=1)

        assert _stored(db, "unstored")["content"] == "forked"

    @pytest.mark.asyncio
    async def test_the_async_save_refuses_another_owner_too(self, db):
        from agno.team._storage import _aupsert_run

        team = _make_team(db)
        await team.arun("seed", session_id="s1", user_id="u1")
        run = TeamRunOutput(run_id="r1", session_id="s1", team_id=team.id, user_id="u1", content="original")
        await _aupsert_run(team, run=run, session_id="s1", user_id="u1", run_index=1)

        attacker = TeamRunOutput(run_id="r1", session_id="s1", team_id=team.id, user_id="u2", content="attacker")
        await _aupsert_run(team, run=attacker, session_id="s1", user_id="u2")

        assert _stored(db, "r1")["content"] == "original"
        assert _owner(db, "r1") == "u1"


class TestIdentityIsResolvedConsistently:
    """The saves that make up one run do not always agree on the user.

    The first save uses the run's resolved user, the terminal save uses the
    session's, and the AgentOS continue route takes it as an optional form
    field. A run must not lose its output because two of those disagree.
    """

    def test_a_run_issued_without_a_user_on_an_owned_session_still_persists(self, db):
        team = _make_team(db)
        team.run("first", session_id="s1", user_id="u1")

        result = team.run("second", session_id="s1")

        assert _stored(db, result.run_id)["status"] == RunStatus.completed.value
        assert _stored(db, result.run_id)["content"] == "ok"

    def test_a_run_issued_with_a_user_on_an_unowned_session_still_persists(self, db):
        team = _make_team(db)
        team.run("first", session_id="s1")

        result = team.run("second", session_id="s1", user_id="u1")

        assert _stored(db, result.run_id)["content"] == "ok"


class TestMemberRunsAndUnportedAdapters:
    def test_a_member_run_is_stored_beside_its_parents_run(self, db):
        """A member's row is written by the parent that owns the turn."""
        team = _make_team(db)
        parent = team.run("hi", session_id="s1")
        member = RunOutput(
            run_id="member",
            session_id="s1",
            agent_id="member-agent",
            parent_run_id=parent.run_id,
            content="member output",
        )

        _upsert_run(team, run=member, session_id="s1", run_index=1)

        assert _stored(db, "member")["content"] == "member output"
        assert _stored(db, parent.run_id)["content"] == "ok"

    def test_a_workflow_leg_still_stores_its_own_run(self, db):
        team = _make_team(db)
        team.run("seed", session_id="s1")
        team.workflow_id = "some-workflow"
        leg = TeamRunOutput(
            run_id="leg",
            session_id="s1",
            team_id=team.id,
            parent_run_id="workflow-run",
            workflow_step_id="step-1",
            content="leg output",
        )

        _upsert_run(team, run=leg, session_id="s1", run_index=1)

        assert _stored(db, "leg")["content"] == "leg output"

    def test_an_adapter_without_the_scoped_pair_keeps_saving(self, db):
        """The shipped adapters that report UNSUPPORTED still take the legacy save."""

        class UnportedDb:
            supports_atomic_run_creation = False

            def __init__(self):
                self.saved: list = []

            def upsert_run(self, run, session_id, user_id=None, run_index=None):
                self.saved.append((run.run_id, session_id))

            def __getattr__(self, name):
                raise AttributeError(name)

        unported = UnportedDb()
        team = _make_team(db)
        team.db = unported  # type: ignore[assignment]
        run = TeamRunOutput(run_id="r1", session_id="s1", team_id=team.id)

        _upsert_run(team, run=run, session_id="s1")
        _upsert_run(team, run=run, session_id="s1")

        assert unported.saved == [("r1", "s1"), ("r1", "s1")]


class TestAttribution:
    """A run stays findable by the user it belongs to.

    A run's saves resolve identity from different places, so the owner column
    has to survive all of them.
    """

    def test_a_run_keeps_the_owner_its_session_has(self, db):
        team = _make_team(db)
        team.run("first", session_id="s1", user_id="alice")

        second = team.run("second", session_id="s1")

        # Asserted on the stored row: the in-memory adapter's get_runs filters
        # by the SESSION's user, so it would pass either way
        assert _owner(db, second.run_id) == "alice"

    def test_an_explicit_user_is_recorded(self, db):
        team = _make_team(db)

        result = team.run("hi", session_id="s1", user_id="alice")

        assert _owner(db, result.run_id) == "alice"
