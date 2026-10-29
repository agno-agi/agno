"""An agent run cannot overwrite a stored run that is not its own.

``run_id`` can be supplied by the caller, and storage used to accept a
conflicting one as an update, replacing a stored run that may belong to
another session or user. Creation is now a strict insert, and every later
write is scoped to the run's own session, effective user and component: a run
handed an id that is already taken executes normally, and its save is refused
rather than landing on the stored run.

The boundaries that refusal draws are the session, the user and the component.
A caller reusing an id inside the scope the stored row already holds presents
exactly what the run's own second save would, so that write is allowed; see
``TestReusingAStoredId``.
"""

import asyncio
import time
from typing import Any, AsyncIterator, Iterator, Optional

import pytest

from agno.agent._storage import upsert_run
from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


class MockModel(Model):
    """Minimal offline model: returns a canned text response without any network call."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.instructions = None
        self._mock_response = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

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


def _make_agent(db: Any, **kwargs) -> Agent:
    return Agent(name="test-agent", id="test-agent", model=MockModel(), db=db, telemetry=False, **kwargs)


def _stored(db: Any, run_id: str) -> Optional[dict]:
    row = db.get_run(run_id, deserialize=False)
    if row is None:
        return None
    return row.get("run_data") or row


def _owner(db: Any, run_id: str) -> Optional[str]:
    """The user the stored run belongs to, whichever row shape came back."""
    row = db.get_run(run_id, deserialize=False) or {}
    return row.get("user_id") or (row.get("run_data") or {}).get("user_id")


def _asked(db: Any, run_id: str) -> Any:
    """What the stored run was asked, which is what tells two turns apart.

    Every turn here answers "ok", so the input is the only field that says
    which run the stored row belongs to.
    """
    value = (_stored(db, run_id) or {}).get("input")
    return value.get("input_content") if isinstance(value, dict) else value


@pytest.fixture(params=["in_memory", "sqlite"])
def db(request, tmp_path):
    if request.param == "in_memory":
        return InMemoryDb()
    return SqliteDb(db_file=str(tmp_path / "runs.db"))


class TestNormalRuns:
    def test_a_generated_id_still_persists(self, db):
        agent = _make_agent(db)

        result = agent.run("hi", session_id="s1")

        assert _stored(db, result.run_id) is not None
        assert _stored(db, result.run_id)["status"] == RunStatus.completed.value

    def test_an_explicit_fresh_id_still_persists(self, db):
        agent = _make_agent(db)

        result = agent.run("hi", session_id="s1", run_id="chosen")

        assert result.run_id == "chosen"
        assert _stored(db, "chosen")["status"] == RunStatus.completed.value

    def test_two_turns_in_one_session_both_persist(self, db):
        agent = _make_agent(db)

        first = agent.run("one", session_id="s1")
        second = agent.run("two", session_id="s1")

        assert first.run_id != second.run_id
        assert _stored(db, first.run_id) is not None
        assert _stored(db, second.run_id) is not None

    @pytest.mark.asyncio
    async def test_async_runs_still_persist(self, db):
        agent = _make_agent(db)

        result = await agent.arun("hi", session_id="s1")

        assert _stored(db, result.run_id)["status"] == RunStatus.completed.value

    @pytest.mark.asyncio
    async def test_background_runs_still_reach_a_terminal_status(self, db):
        agent = _make_agent(db)

        result = await agent.arun("hi", session_id="s1", background=True)
        # Poll to a TERMINAL status: the run passes through RUNNING on its way,
        # and breaking on the first stored status raced that transition
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
        agent = _make_agent(db)

        events = list(agent.run("hi", session_id="s1", run_id="streamed", stream=True))

        assert events
        assert _stored(db, "streamed")["status"] == RunStatus.completed.value
        assert _stored(db, "streamed")["content"] == "ok"

    @pytest.mark.asyncio
    async def test_an_async_streaming_run_still_persists(self, db):
        agent = _make_agent(db)

        events = [event async for event in agent.arun("hi", session_id="s1", run_id="streamed", stream=True)]

        assert events
        assert _stored(db, "streamed")["status"] == RunStatus.completed.value


class TestReusingAStoredId:
    """A run handed a taken id executes, and its save cannot reach the stored run.

    Each refusal asserts the whole stored row is byte-for-byte what it was,
    and every case that names a user asserts the owner column too, since
    leaving the run readable by the wrong user is the same loss as replacing
    its content.
    """

    def test_a_reuse_inside_the_stored_scope_is_the_runs_own_write(self, db):
        """Nothing distinguishes this from the run saving itself a second time.

        The scope a write presents is its session, user and component. A
        caller reusing an id within the same scope presents exactly what the
        stored row holds, which is also what every lifecycle transition of the
        run itself presents, so the write lands. The boundaries asserted below
        are what the scope refuses.
        """
        agent = _make_agent(db)
        agent.run("first", session_id="s1", user_id="u1", run_id="taken")

        agent.run("second", session_id="s1", user_id="u1", run_id="taken")

        assert _asked(db, "taken") == "second"
        assert _owner(db, "taken") == "u1"

    def test_another_session_cannot_overwrite_the_stored_run(self, db):
        agent = _make_agent(db)
        agent.run("victim turn", session_id="victim", run_id="taken")
        original = _stored(db, "taken")

        agent.run("attacker turn", session_id="attacker", run_id="taken")

        assert _stored(db, "taken") == original
        assert _asked(db, "taken") == "victim turn"

    def test_another_user_cannot_overwrite_the_stored_run(self, db):
        """Same session, so the user is the only fact that differs."""
        agent = _make_agent(db)
        agent.run("victim turn", session_id="s1", user_id="victim-user", run_id="taken")
        original = _stored(db, "taken")

        agent.run("attacker turn", session_id="s1", user_id="attacker-user", run_id="taken")

        assert _stored(db, "taken") == original
        assert _owner(db, "taken") == "victim-user"

    def test_another_users_session_cannot_overwrite_the_stored_run(self, db):
        agent = _make_agent(db)
        agent.run("victim turn", session_id="victim", user_id="victim-user", run_id="taken")
        original = _stored(db, "taken")

        agent.run("attacker turn", session_id="attacker", user_id="attacker-user", run_id="taken")

        assert _stored(db, "taken") == original
        assert _owner(db, "taken") == "victim-user"

    def test_another_session_cannot_claim_an_anonymous_stored_run(self, db):
        """The session refuses this write; naming a user would not have.

        An unowned row is adopted by the first write that knows a user, so in
        the stored row's own session this caller would land and the row would
        become theirs. Here the sessions differ, which is the fact the refusal
        rests on, and being unowned does not soften it: an anonymous row is no
        more reachable from another session than an owned one.
        """
        agent = _make_agent(db)
        agent.run("victim turn", session_id="victim", run_id="taken")
        original = _stored(db, "taken")

        agent.run("attacker turn", session_id="attacker", user_id="attacker-user", run_id="taken")

        assert _stored(db, "taken") == original
        assert _owner(db, "taken") is None

    def test_two_identity_less_callers_do_not_reach_each_others_runs(self, db):
        """Neither caller names a user, so the session is all the scope has."""
        agent = _make_agent(db)
        agent.run("first", session_id="s1", run_id="taken")
        original = _stored(db, "taken")

        agent.run("second", session_id="s2", run_id="taken")

        assert _stored(db, "taken") == original
        assert _asked(db, "taken") == "first"

    def test_the_refused_run_still_executes_and_returns_its_output(self, db):
        """The refusal is a storage decision, not a rejected request."""
        agent = _make_agent(db)
        agent.run("first", session_id="s1", run_id="taken")
        calls = {"count": 0}
        original_invoke = agent.model.invoke

        def counting_invoke(*args, **kwargs):
            calls["count"] += 1
            return original_invoke(*args, **kwargs)

        agent.model.invoke = counting_invoke  # type: ignore[method-assign]

        result = agent.run("second", session_id="s2", run_id="taken")

        assert calls["count"] == 1
        assert result.run_id == "taken"
        assert result.status == RunStatus.completed
        assert result.content == "ok"

    def test_a_sync_streaming_run_does_not_overwrite_the_stored_run(self, db):
        agent = _make_agent(db)
        agent.run("first", session_id="s1", run_id="taken")
        original = _stored(db, "taken")

        events = list(agent.run("second", session_id="s2", run_id="taken", stream=True))

        assert events
        assert _stored(db, "taken") == original

    @pytest.mark.asyncio
    async def test_an_async_run_does_not_overwrite_the_stored_run(self, db):
        agent = _make_agent(db)
        await agent.arun("first", session_id="s1", run_id="taken")
        original = _stored(db, "taken")

        await agent.arun("second", session_id="s2", user_id="other", run_id="taken")

        assert _stored(db, "taken") == original
        assert _owner(db, "taken") is None

    @pytest.mark.asyncio
    async def test_an_async_streaming_run_does_not_overwrite_the_stored_run(self, db):
        agent = _make_agent(db)
        await agent.arun("first", session_id="s1", run_id="taken")
        original = _stored(db, "taken")

        events = [event async for event in agent.arun("second", session_id="s2", run_id="taken", stream=True)]

        assert events
        assert _stored(db, "taken") == original

    def test_a_run_without_a_database_still_reuses_the_id(self):
        agent = Agent(name="test-agent", id="test-agent", model=MockModel(), telemetry=False)

        first = agent.run("first", session_id="s1", run_id="taken")
        second = agent.run("second", session_id="s1", run_id="taken")

        assert first.run_id == second.run_id == "taken"


class TestLifecycleAfterTheFirstSave:
    """Transitions written after the first save go through the scoped update.

    These use the framework's own per-run save helper, which is what the HITL,
    resume, background and terminal paths all call.
    """

    def _seeded(self, db: Any, session_id: str = "s1", user_id: Optional[str] = None) -> tuple:
        """An agent whose session exists, and an unsaved run to drive through it.

        The seed turn is what creates the session row; a run has nothing to
        attach to without one, and its strict create reports the session
        missing rather than inventing it.
        """
        agent = _make_agent(db)
        agent.run("seed", session_id=session_id, user_id=user_id)
        run = RunOutput(run_id="r1", session_id=session_id, agent_id=agent.id, user_id=user_id)
        return agent, run

    def test_pause_then_resume_then_completion_all_land(self, db):
        agent, run = self._seeded(db, user_id="u1")

        run.status = RunStatus.paused
        upsert_run(agent, run=run, session_id="s1", user_id="u1", run_index=1)
        assert _stored(db, "r1")["status"] == RunStatus.paused.value

        run.status = RunStatus.running
        upsert_run(agent, run=run, session_id="s1", user_id="u1")
        assert _stored(db, "r1")["status"] == RunStatus.running.value

        run.status = RunStatus.completed
        run.content = "done"
        upsert_run(agent, run=run, session_id="s1", user_id="u1")
        assert _stored(db, "r1")["status"] == RunStatus.completed.value
        assert _stored(db, "r1")["content"] == "done"

    def test_a_resume_by_another_user_is_refused(self, db):
        agent, run = self._seeded(db, user_id="u1")
        run.status = RunStatus.paused
        upsert_run(agent, run=run, session_id="s1", user_id="u1", run_index=1)
        paused = _stored(db, "r1")

        run.content = "attacker"
        run.status = RunStatus.completed
        upsert_run(agent, run=run, session_id="s1", user_id="attacker")

        assert _stored(db, "r1") == paused
        assert _owner(db, "r1") == "u1"

    def test_a_resume_from_another_session_is_refused(self, db):
        agent, run = self._seeded(db, user_id="u1")
        run.status = RunStatus.paused
        upsert_run(agent, run=run, session_id="s1", user_id="u1", run_index=1)
        paused = _stored(db, "r1")

        run.content = "attacker"
        run.status = RunStatus.completed
        upsert_run(agent, run=run, session_id="attacker-session", user_id="u1")

        assert _stored(db, "r1") == paused

    def test_a_save_for_a_run_that_was_never_stored_still_creates_it(self, db):
        """Paths whose run has no row yet, such as a forked run, keep working."""
        agent = _make_agent(db)
        agent.run("seed", session_id="s1")
        run = RunOutput(run_id="unstored", session_id="s1", agent_id=agent.id, content="forked")

        upsert_run(agent, run=run, session_id="s1", run_index=1)

        assert _stored(db, "unstored")["content"] == "forked"

    @pytest.mark.asyncio
    async def test_an_async_scoped_save_refuses_another_owner(self, db):
        from agno.agent._storage import aupsert_run

        agent = _make_agent(db)
        await agent.arun("seed", session_id="s1", user_id="u1")
        run = RunOutput(run_id="r1", session_id="s1", agent_id=agent.id, user_id="u1", content="original")
        await aupsert_run(agent, run=run, session_id="s1", user_id="u1", run_index=1)

        attacker = RunOutput(run_id="r1", session_id="s1", agent_id=agent.id, user_id="u2", content="attacker")
        await aupsert_run(agent, run=attacker, session_id="s1", user_id="u2")

        assert _stored(db, "r1")["content"] == "original"
        assert _owner(db, "r1") == "u1"


class TestMemberAndWorkflowRuns:
    def test_a_member_agent_writes_no_run_row_of_its_own(self, db):
        """A member's run row is owned by the team that saves it."""
        agent = _make_agent(db)
        agent.team_id = "some-team"

        agent.run("hi", session_id="s1", run_id="member")

        assert _stored(db, "member") is None

    def test_a_workflow_leg_writes_no_run_row_of_its_own(self, db):
        agent = _make_agent(db)
        agent.workflow_id = "some-workflow"

        agent.run("hi", session_id="s1", run_id="leg")

        assert _stored(db, "leg") is None

    def test_a_save_naming_another_workflow_is_refused(self, db):
        """The component is scoped alongside the session and the user."""
        agent = _make_agent(db)
        agent.run("seed", session_id="s1")
        leg = RunOutput(run_id="leg", session_id="s1", agent_id=agent.id, workflow_id="wf-a", content="leg output")
        upsert_run(agent, run=leg, session_id="s1", run_index=1)

        other = RunOutput(run_id="leg", session_id="s1", agent_id=agent.id, workflow_id="wf-b", content="stolen")
        upsert_run(agent, run=other, session_id="s1")

        assert _stored(db, "leg")["content"] == "leg output"

    def test_an_adapter_without_the_pair_keeps_saving(self):
        """The shipped adapters that report UNSUPPORTED must be unaffected.

        Such an adapter has no strict create and no scoped update, so the save
        stays on the legacy path: both writes reach it, the second one
        included, and nothing here refuses either.
        """

        class UnportedDb:
            supports_atomic_run_creation = False

            def __init__(self):
                self.saves: list = []

            def upsert_run(self, run, session_id, user_id=None, run_index=None):
                self.saves.append((run.run_id, session_id, run.content))
                return True

        agent = _make_agent(InMemoryDb())
        unported = UnportedDb()
        agent.db = unported  # type: ignore[assignment]

        upsert_run(
            agent,
            run=RunOutput(run_id="r1", session_id="s1", agent_id=agent.id, content="first"),
            session_id="s1",
            run_index=0,
        )
        upsert_run(
            agent,
            run=RunOutput(run_id="r1", session_id="other", agent_id=agent.id, content="second"),
            session_id="other",
            run_index=0,
        )

        assert unported.saves == [("r1", "s1", "first"), ("r1", "other", "second")]


class TestAttribution:
    """A run stays findable by the user it belongs to.

    The save paths resolve identity from different places -- the route's user,
    the session's, the run's own -- so the owner column has to survive
    whichever one wrote the row, and a run must not lose its output because
    two of them disagree.
    """

    def test_a_run_keeps_the_owner_its_session_has(self, db):
        agent = _make_agent(db)
        agent.run("first", session_id="s1", user_id="alice")

        second = agent.run("second", session_id="s1")

        # Asserted on the stored row: the in-memory adapter's get_runs filters
        # by the SESSION's user, so it would pass either way
        assert _owner(db, second.run_id) == "alice"

    def test_an_explicit_user_is_recorded(self, db):
        agent = _make_agent(db)

        result = agent.run("hi", session_id="s1", user_id="alice")

        assert _owner(db, result.run_id) == "alice"

    def test_a_run_issued_without_a_user_on_an_owned_session_still_persists(self, db):
        agent = _make_agent(db)
        agent.run("first", session_id="s1", user_id="u1")

        result = agent.run("second", session_id="s1")

        assert _stored(db, result.run_id)["status"] == RunStatus.completed.value
        assert _stored(db, result.run_id)["content"] == "ok"

    def test_a_run_issued_with_a_user_on_an_unowned_session_still_persists(self, db):
        agent = _make_agent(db)
        agent.run("first", session_id="s1")

        result = agent.run("second", session_id="s1", user_id="u1")

        assert _stored(db, result.run_id)["content"] == "ok"
