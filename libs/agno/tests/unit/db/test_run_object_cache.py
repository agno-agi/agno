"""The per-turn session read serves history run objects from a cache instead
of rebuilding every run from its dict on every read.

These tests pin the properties the cache could break: the stored dicts remain
canonical and isolated from every caller, writes invalidate exactly the run
they touch, concurrent runs on one session never see each other's state, and
the library paths that change a historical run do it on a copy.
"""

import asyncio

import pytest

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession, TeamSession, WorkflowSession


class MockModel(Model):
    def __init__(self):
        super().__init__(id="mock", name="mock", provider="mock")
        self._r = ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def invoke(self, *a, **k):
        return self._r

    async def ainvoke(self, *a, **k):
        await asyncio.sleep(0.02)
        return self._r

    def invoke_stream(self, *a, **k):
        yield self._r

    async def ainvoke_stream(self, *a, **k):
        yield self._r

    def _parse_provider_response(self, r, **k):
        return r

    def _parse_provider_response_delta(self, r):
        return r


def _seed(db: InMemoryDb, session_id: str = "s1", n_runs: int = 3) -> None:
    db.upsert_session(AgentSession(session_id=session_id, agent_id="a1", user_id="u1"))
    for i in range(n_runs):
        db.upsert_run(
            {"run_id": f"r{i}", "agent_id": "a1", "content": f"content {i}", "status": "COMPLETED"},
            session_id=session_id,
        )


class TestSharedHistoryObjects:
    def test_reads_share_history_run_objects(self):
        """The win itself: two reads of an unchanged session reuse the same
        deserialized run objects, in fresh lists."""
        db = InMemoryDb()
        _seed(db)
        first = db.get_session("s1", session_type=SessionType.AGENT)
        second = db.get_session("s1", session_type=SessionType.AGENT)
        assert first is not second
        assert first.runs is not second.runs
        assert [id(r) for r in first.runs] == [id(r) for r in second.runs]

    def test_session_row_state_is_fresh_per_read(self):
        db = InMemoryDb()
        _seed(db)
        first = db.get_session("s1", session_type=SessionType.AGENT)
        first.session_data = {"poisoned": True}
        first.metadata = {"poisoned": True}
        second = db.get_session("s1", session_type=SessionType.AGENT)
        assert (second.session_data or {}).get("poisoned") is None
        assert (second.metadata or {}).get("poisoned") is None

    def test_content_matches_the_uncached_rebuild(self):
        """The cached objects are byte-for-byte what a fresh rebuild yields."""
        db = InMemoryDb()
        _seed(db, n_runs=5)
        cached = db.get_session("s1", session_type=SessionType.AGENT)
        raw = db.get_session("s1", session_type=SessionType.AGENT, deserialize=False)
        rebuilt = AgentSession.from_dict(raw)
        assert [r.to_dict() for r in cached.runs] == [r.to_dict() for r in rebuilt.runs]

    def test_windowed_reads_are_unaffected(self):
        db = InMemoryDb()
        _seed(db, n_runs=5)
        bounded = db.get_session("s1", session_type=SessionType.AGENT, runs_limit=2)
        assert [r.run_id for r in bounded.runs] == ["r3", "r4"]


class TestInvalidation:
    def test_updating_a_run_invalidates_only_that_run(self):
        db = InMemoryDb()
        _seed(db)
        first = db.get_session("s1", session_type=SessionType.AGENT)
        db.upsert_run({"run_id": "r1", "agent_id": "a1", "content": "rewritten", "status": "COMPLETED"}, "s1")
        second = db.get_session("s1", session_type=SessionType.AGENT)
        assert second.runs[1].content == "rewritten"
        assert first.runs[1].content == "content 1"
        assert second.runs[0] is first.runs[0]
        assert second.runs[2] is first.runs[2]

    def test_appending_a_run_shows_up(self):
        db = InMemoryDb()
        _seed(db)
        db.upsert_run({"run_id": "r9", "agent_id": "a1", "content": "new", "status": "COMPLETED"}, "s1")
        assert [r.run_id for r in db.get_session("s1", session_type=SessionType.AGENT).runs] == [
            "r0",
            "r1",
            "r2",
            "r9",
        ]

    def test_deleting_and_recreating_a_session_serves_no_stale_objects(self):
        db = InMemoryDb()
        _seed(db)
        db.get_session("s1", session_type=SessionType.AGENT)
        db.delete_session("s1")
        db.upsert_session(AgentSession(session_id="s1", agent_id="a1", user_id="u1"))
        db.upsert_run({"run_id": "r0", "agent_id": "a1", "content": "fresh", "status": "COMPLETED"}, "s1")
        session = db.get_session("s1", session_type=SessionType.AGENT)
        assert [r.content for r in session.runs] == ["fresh"]

    def test_a_caller_held_run_dict_cannot_rewrite_the_store(self):
        """upsert_run keeps its own copy: mutating the dict afterwards must
        change neither the stored dicts nor what reads return."""
        db = InMemoryDb()
        db.upsert_session(AgentSession(session_id="s1", agent_id="a1", user_id="u1"))
        held = {"run_id": "r0", "agent_id": "a1", "content": "original", "status": "COMPLETED"}
        db.upsert_run(held, "s1")
        held["content"] = "mutated after the fact"
        raw = db.get_session("s1", session_type=SessionType.AGENT, deserialize=False)
        assert raw["runs"][0]["content"] == "original"
        assert db.get_session("s1", session_type=SessionType.AGENT).runs[0].content == "original"


class TestStoreIsolation:
    def test_mutating_a_returned_run_never_reaches_the_stored_dicts(self):
        """The stored dicts are canonical: whatever a caller does to returned
        objects, a deserialize=False read reflects only what was written."""
        db = InMemoryDb()
        _seed(db)
        session = db.get_session("s1", session_type=SessionType.AGENT)
        session.runs[0].content = "caller vandalism"
        session.runs.append(RunOutput(run_id="bogus", agent_id="a1"))
        raw = db.get_session("s1", session_type=SessionType.AGENT, deserialize=False)
        assert raw["runs"][0]["content"] == "content 0"
        assert [r["run_id"] for r in raw["runs"]] == ["r0", "r1", "r2"]

    def test_deserialize_false_reads_are_deep_copies(self):
        db = InMemoryDb()
        _seed(db)
        raw = db.get_session("s1", session_type=SessionType.AGENT, deserialize=False)
        raw["runs"][0]["content"] = "mutated"
        again = db.get_session("s1", session_type=SessionType.AGENT, deserialize=False)
        assert again["runs"][0]["content"] == "content 0"


class TestConcurrentRuns:
    @pytest.mark.asyncio
    async def test_concurrent_aruns_on_one_session_do_not_cross_contaminate(self):
        """Two arun() calls in flight on one session: each run's response and
        the final history stay consistent, and neither sees the other's
        in-flight state."""
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, add_history_to_context=True, telemetry=False)
        await agent.arun("seed", session_id="shared", user_id="u1")

        first, second = await asyncio.gather(
            agent.arun("first branch", session_id="shared", user_id="u1"),
            agent.arun("second branch", session_id="shared", user_id="u1"),
        )
        assert first.run_id != second.run_id
        assert first.content == "ok" and second.content == "ok"

        session = db.get_session("shared", session_type=SessionType.AGENT)
        stored_ids = {r.run_id for r in session.runs}
        assert {first.run_id, second.run_id} <= stored_ids
        # Each stored run carries only its own input.
        by_id = {r.run_id: r for r in session.runs}
        assert by_id[first.run_id].input.input_content == "first branch"
        assert by_id[second.run_id].input.input_content == "second branch"

    @pytest.mark.asyncio
    async def test_concurrent_sessions_stay_isolated(self):
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, add_history_to_context=True, telemetry=False)
        await asyncio.gather(
            agent.arun("alpha", session_id="sa", user_id="ua"),
            agent.arun("beta", session_id="sb", user_id="ub"),
        )
        sa = db.get_session("sa", session_type=SessionType.AGENT)
        sb = db.get_session("sb", session_type=SessionType.AGENT)
        assert [r.input.input_content for r in sa.runs] == ["alpha"]
        assert [r.input.input_content for r in sb.runs] == ["beta"]
        assert sa.user_id == "ua" and sb.user_id == "ub"


class TestHistoryEquality:
    @pytest.mark.parametrize("turns", [5, 25])
    def test_history_messages_match_an_uncached_rebuild(self, turns):
        """What the model sees as history must be identical to what a fresh
        from_dict rebuild of the stored dicts yields, at every depth."""
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, add_history_to_context=True, telemetry=False)
        for i in range(turns):
            agent.run(f"turn {i}", session_id="conv", user_id="u1")

        cached = db.get_session("conv", session_type=SessionType.AGENT)
        rebuilt = AgentSession.from_dict(db.get_session("conv", session_type=SessionType.AGENT, deserialize=False))

        cached_messages = [m.to_dict() for m in cached.get_messages()]
        rebuilt_messages = [m.to_dict() for m in rebuilt.get_messages()]
        assert cached_messages == rebuilt_messages
        assert [r.to_dict() for r in cached.runs] == [r.to_dict() for r in rebuilt.runs]


class TestSharedObjectBoundaries:
    """Every library surface that hands a run to a mutator copies at the
    boundary, so the shared cached objects stay clean."""

    def test_get_run_returns_a_copy(self):
        """Background continue, HITL surfaces and the job-queue sweeper all
        fetch via get_run and mutate before persisting; the shared object must
        not carry those mutations."""
        db = InMemoryDb()
        _seed(db)
        session = db.get_session("s1", session_type=SessionType.AGENT)
        fetched = session.get_run("r1")
        fetched.status = RunStatus.cancelled
        fetched.content = "sweeper text"

        later = db.get_session("s1", session_type=SessionType.AGENT)
        assert later.runs[1].status != RunStatus.cancelled
        assert later.runs[1].content == "content 1"

    def test_get_run_output_returns_a_copy(self):
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, telemetry=False)
        response = agent.run("one", session_id="s1", user_id="u1")

        fetched = agent.get_run_output(response.run_id, session_id="s1")
        fetched.status = RunStatus.cancelled
        later = db.get_session("s1", session_type=SessionType.AGENT)
        assert later.get_run(response.run_id).status != RunStatus.cancelled

    def test_get_last_run_output_returns_a_copy(self):
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, telemetry=False)
        agent.run("one", session_id="s1", user_id="u1")

        fetched = agent.get_last_run_output(session_id="s1")
        fetched.content = "vandalized"
        later = db.get_session("s1", session_type=SessionType.AGENT)
        assert later.runs[-1].content != "vandalized"

    def test_poll_then_continue_does_not_mutate_the_shared_history(self):
        """The documented poll-then-continue pattern: the run fetched via
        get_run_output is the caller's own copy, so continue_run(run_response=...)
        -- which deliberately completes the passed object in place (the team
        resume flow relies on that) -- never reaches the shared history."""
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, telemetry=False)
        agent.run("seed", session_id="s1", user_id="u1")
        db.upsert_run(
            {
                "run_id": "r-mid",
                "agent_id": agent.id,
                "user_id": "u1",
                "status": "RUNNING",
                "messages": [{"role": "user", "content": "resume me"}],
            },
            session_id="s1",
        )
        shared = db.get_session("s1", session_type=SessionType.AGENT).runs[-1]
        assert shared.run_id == "r-mid"
        status_before = shared.status
        message_count = len(shared.messages or [])

        provided = agent.get_run_output("r-mid", session_id="s1")
        agent.continue_run(run_response=provided, session_id="s1", user_id="u1")

        # The passed copy completed; the shared history object never moved.
        # (Whether this synthetic seeded run's completion persists is a
        # separate, pre-existing behaviour -- identical on main -- and not
        # what this test pins.)
        assert provided.status != status_before
        assert shared.status == status_before
        assert len(shared.messages or []) == message_count

    def test_threaded_reads_with_run_churn_do_not_crash(self):
        """Concurrent threaded reads of one session while runs are written and
        deleted: reads must never raise (the cache publishes a fresh entry map
        per read instead of mutating a shared one)."""
        import threading

        db = InMemoryDb()
        _seed(db, n_runs=10)
        errors: list = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    db.get_session("s1", session_type=SessionType.AGENT)
                except Exception as exc:
                    errors.append(exc)
                    return

        def writer():
            for i in range(300):
                db.upsert_run(
                    {"run_id": f"rw{i % 7}", "agent_id": "a1", "content": f"v{i}", "status": "COMPLETED"},
                    session_id="s1",
                )
                db.delete_run(f"rw{(i + 3) % 7}")
            stop.set()

        threads = [threading.Thread(target=reader) for _ in range(4)] + [threading.Thread(target=writer)]
        import sys

        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        finally:
            sys.setswitchinterval(old_interval)
        assert errors == []

    def test_sqlite_delete_session_drops_the_cache_entry(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "drop.db"))
        db.upsert_session(AgentSession(session_id="s1", agent_id="a1", user_id="u1"))
        db.upsert_run({"run_id": "r0", "agent_id": "a1", "content": "x", "status": "COMPLETED"}, "s1")
        db.get_session("s1", session_type=SessionType.AGENT)
        assert "s1" in db._run_object_cache._per_session
        db.delete_session("s1")
        assert "s1" not in db._run_object_cache._per_session


class TestSqliteRunObjectCache:
    """The SQL-adapter cache keys on raw row text, so shared objects and
    cross-process visibility follow from the rows alone."""

    @pytest.fixture
    def sqlite_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        return SqliteDb(db_file=str(tmp_path / "cache.db"))

    def _seed(self, db, n_runs: int = 3) -> None:
        db.upsert_session(AgentSession(session_id="s1", agent_id="a1", user_id="u1"))
        for i in range(n_runs):
            db.upsert_run(
                {"run_id": f"r{i}", "agent_id": "a1", "content": f"content {i}", "status": "COMPLETED"},
                session_id="s1",
            )

    def test_reads_share_history_run_objects(self, sqlite_db):
        self._seed(sqlite_db)
        first = sqlite_db.get_session("s1", session_type=SessionType.AGENT)
        second = sqlite_db.get_session("s1", session_type=SessionType.AGENT)
        assert first.runs is not second.runs
        assert [id(r) for r in first.runs] == [id(r) for r in second.runs]

    def test_updating_a_run_invalidates_only_that_run(self, sqlite_db):
        self._seed(sqlite_db)
        first = sqlite_db.get_session("s1", session_type=SessionType.AGENT)
        sqlite_db.upsert_run({"run_id": "r1", "agent_id": "a1", "content": "rewritten", "status": "COMPLETED"}, "s1")
        second = sqlite_db.get_session("s1", session_type=SessionType.AGENT)
        assert second.runs[1].content == "rewritten"
        assert first.runs[1].content == "content 1"
        assert second.runs[0] is first.runs[0]
        assert second.runs[2] is first.runs[2]

    def test_another_writer_to_the_same_file_is_seen(self, sqlite_db, tmp_path):
        """A second adapter instance (stand-in for another process) writes a
        run; this instance's next read reflects it -- the text-keyed token
        cannot serve state the rows no longer hold."""
        from agno.db.sqlite import SqliteDb

        self._seed(sqlite_db)
        sqlite_db.get_session("s1", session_type=SessionType.AGENT)

        other = SqliteDb(db_file=str(tmp_path / "cache.db"))
        other.upsert_run(
            {"run_id": "r1", "agent_id": "a1", "content": "written elsewhere", "status": "COMPLETED"}, "s1"
        )

        again = sqlite_db.get_session("s1", session_type=SessionType.AGENT)
        assert again.runs[1].content == "written elsewhere"

    def test_content_matches_the_uncached_rebuild(self, sqlite_db):
        self._seed(sqlite_db, n_runs=5)
        cached = sqlite_db.get_session("s1", session_type=SessionType.AGENT)
        raw = sqlite_db.get_session("s1", session_type=SessionType.AGENT, deserialize=False)
        rebuilt = AgentSession.from_dict(raw)
        assert [r.to_dict() for r in cached.runs] == [r.to_dict() for r in rebuilt.runs]

    def test_mutating_a_returned_run_never_reaches_the_rows(self, sqlite_db):
        self._seed(sqlite_db)
        session = sqlite_db.get_session("s1", session_type=SessionType.AGENT)
        session.runs[0].content = "caller vandalism"
        raw = sqlite_db.get_session("s1", session_type=SessionType.AGENT, deserialize=False)
        assert raw["runs"][0]["content"] == "content 0"


class TestHardenedMutators:
    def test_regenerate_flips_status_on_a_copy(self):
        """_mark_run_regenerated must not write through a shared history
        object: another session view read before the flip keeps its status."""
        from agno.agent._run import _mark_run_regenerated

        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, telemetry=False)
        agent.run("one", session_id="s1", user_id="u1")

        before = db.get_session("s1", session_type=SessionType.AGENT)
        target_run = before.runs[0]
        session_view = db.get_session("s1", session_type=SessionType.AGENT)

        _mark_run_regenerated(agent, session_view, target_run.run_id)

        # The other reader's object is untouched; the store has the flip.
        assert target_run.status != RunStatus.regenerated
        after = db.get_session("s1", session_type=SessionType.AGENT)
        assert after.runs[0].status == RunStatus.regenerated
        # The mutated session view sees its own flip.
        assert session_view.runs[0].status == RunStatus.regenerated

    def test_continue_run_does_not_mutate_the_shared_history_object(self):
        """continue_run works on a copy of the stored run: the shared object
        another reader holds must keep its status and message list. An
        in-flight (RUNNING) run is the case that matters -- a completed run is
        force-forked, and the fork path copies on its own."""
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, telemetry=False)
        agent.run("seed", session_id="s1", user_id="u1")
        db.upsert_run(
            {
                "run_id": "r-mid",
                "agent_id": agent.id,
                "user_id": "u1",
                "status": "RUNNING",
                "messages": [
                    {"role": "user", "content": "resume me"},
                ],
            },
            session_id="s1",
        )

        shared = db.get_session("s1", session_type=SessionType.AGENT).get_run("r-mid")
        assert shared is not None
        status_before = shared.status
        message_count_before = len(shared.messages or [])

        agent.continue_run(run_id="r-mid", session_id="s1", user_id="u1")

        # The continue completed and persisted its own copy; the shared
        # object another reader holds is untouched.
        assert shared.status == status_before
        assert len(shared.messages or []) == message_count_before
        stored = db.get_session("s1", session_type=SessionType.AGENT).get_run("r-mid")
        assert stored.status != status_before


# ---------------------------------------------------------------------------
# Team sessions
# ---------------------------------------------------------------------------


def _member_response_dict(idx: int) -> dict:
    """A member response carrying data every member storage flag can scrub.

    Message and media ids are explicit: deserialization mints fresh ids for
    entries without one, and the rebuild-equality tests compare two
    independent deserializations."""
    return {
        "run_id": f"m{idx}",
        "agent_id": "member-agent",
        "content": f"member answer {idx}",
        "status": "COMPLETED",
        "images": [{"id": f"img-{idx}", "url": "http://x/out.png"}],
        "messages": [
            {"id": f"msg-{idx}-0", "role": "assistant", "tool_calls": [{"id": f"tc{idx}", "type": "function"}]},
            {"id": f"msg-{idx}-1", "role": "tool", "tool_call_id": f"tc{idx}", "content": "tool result"},
            {"id": f"msg-{idx}-2", "role": "assistant", "content": f"member answer {idx}"},
            {"id": f"msg-{idx}-3", "role": "user", "content": "old turn", "from_history": True},
        ],
    }


def _seed_team(db, session_id: str = "t1", n_runs: int = 3, with_member_data: bool = False) -> None:
    db.upsert_session(TeamSession(session_id=session_id, team_id="tm1", user_id="u1"))
    for i in range(n_runs):
        run = {"run_id": f"r{i}", "team_id": "tm1", "content": f"content {i}", "status": "COMPLETED"}
        if with_member_data:
            run["member_responses"] = [_member_response_dict(i)]
        db.upsert_run(run, session_id=session_id)


class TestTeamRunObjectCache:
    def test_reads_share_history_run_objects(self):
        db = InMemoryDb()
        _seed_team(db)
        first = db.get_session("t1", session_type=SessionType.TEAM)
        second = db.get_session("t1", session_type=SessionType.TEAM)
        assert first is not second
        assert first.runs is not second.runs
        assert [id(r) for r in first.runs] == [id(r) for r in second.runs]

    def test_content_matches_the_uncached_rebuild(self):
        """Team runs with member responses and a member agent run at the top
        level come back byte-for-byte what a fresh rebuild yields."""
        db = InMemoryDb()
        _seed_team(db, with_member_data=True)
        db.upsert_run(
            {"run_id": "ma1", "agent_id": "member-agent", "content": "standalone", "status": "COMPLETED"},
            session_id="t1",
        )
        cached = db.get_session("t1", session_type=SessionType.TEAM)
        raw = db.get_session("t1", session_type=SessionType.TEAM, deserialize=False)
        rebuilt = TeamSession.from_dict(raw)
        assert [r.to_dict() for r in cached.runs] == [r.to_dict() for r in rebuilt.runs]

    def test_updating_a_run_invalidates_only_that_run(self):
        db = InMemoryDb()
        _seed_team(db)
        first = db.get_session("t1", session_type=SessionType.TEAM)
        db.upsert_run({"run_id": "r1", "team_id": "tm1", "content": "rewritten", "status": "COMPLETED"}, "t1")
        second = db.get_session("t1", session_type=SessionType.TEAM)
        assert second.runs[1].content == "rewritten"
        assert first.runs[1].content == "content 1"
        assert second.runs[0] is first.runs[0]
        assert second.runs[2] is first.runs[2]

    def test_mutating_a_returned_run_never_reaches_the_stored_dicts(self):
        db = InMemoryDb()
        _seed_team(db, with_member_data=True)
        session = db.get_session("t1", session_type=SessionType.TEAM)
        session.runs[0].content = "caller vandalism"
        session.runs[0].member_responses[0].content = "member vandalism"
        raw = db.get_session("t1", session_type=SessionType.TEAM, deserialize=False)
        assert raw["runs"][0]["content"] == "content 0"
        assert raw["runs"][0]["member_responses"][0]["content"] == "member answer 0"

    def test_get_run_returns_a_copy(self):
        """The team background continue, HITL surfaces and the job-queue
        sweeper fetch via get_run and mutate before persisting; the shared
        object must not carry those mutations."""
        db = InMemoryDb()
        _seed_team(db)
        session = db.get_session("t1", session_type=SessionType.TEAM)
        fetched = session.get_run("r1")
        fetched.status = RunStatus.cancelled
        fetched.content = "sweeper text"

        later = db.get_session("t1", session_type=SessionType.TEAM)
        assert later.runs[1].status != RunStatus.cancelled
        assert later.runs[1].content == "content 1"


class TestTeamSaveScrubIsolation:
    """save_session/save_run with store_member_responses=True scrub member
    responses per member storage flags on a storage view, never on the loaded
    (shared) run objects."""

    def _team(self, db):
        from agno.team import Team

        member = Agent(
            name="member",
            id="member-agent",
            store_media=False,
            store_tool_messages=False,
            store_history_messages=False,
        )
        return Team(id="tm1", members=[member], db=db, store_member_responses=True, telemetry=False)

    def test_save_session_scrubs_the_store_not_the_shared_runs(self):
        db = InMemoryDb()
        # Stored runs carry member data the member's current flags would
        # scrub (written before the flags were turned off).
        _seed_team(db, with_member_data=True)
        team = self._team(db)

        session = db.get_session("t1", session_type=SessionType.TEAM)
        shared_member = session.runs[0].member_responses[0]
        # Deleting the row first routes this save through the one path where
        # upsert_session serializes the session's own runs (a v3 update
        # carries the stored list forward instead), so the storage view is
        # observable in the store.
        db.delete_session("t1")
        team.save_session(session=session)

        # The shared run objects keep their member data...
        assert any(m.role == "tool" for m in shared_member.messages or [])
        assert any(m.from_history for m in shared_member.messages or [])
        assert shared_member.images
        # ...while the store holds the scrubbed view.
        raw = db.get_session("t1", session_type=SessionType.TEAM, deserialize=False)
        stored_member = raw["runs"][0]["member_responses"][0]
        assert all(m.get("role") != "tool" for m in stored_member.get("messages") or [])
        assert all(not m.get("from_history") for m in stored_member.get("messages") or [])
        assert not stored_member.get("images")

    def test_save_run_scrubs_the_store_not_the_shared_run(self):
        from agno.team._session import save_run

        db = InMemoryDb()
        _seed_team(db, with_member_data=True)
        team = self._team(db)

        session = db.get_session("t1", session_type=SessionType.TEAM)
        shared_run = session.runs[1]
        save_run(team, run=shared_run, session_id="t1", user_id="u1")

        assert any(m.role == "tool" for m in shared_run.member_responses[0].messages or [])
        raw = db.get_session("t1", session_type=SessionType.TEAM, deserialize=False)
        stored_member = raw["runs"][1]["member_responses"][0]
        assert all(m.get("role") != "tool" for m in stored_member.get("messages") or [])

    def test_already_scrubbed_history_is_reused_not_copied(self):
        """A save of already-scrubbed history detects nothing to remove and
        reuses the loaded run objects for the storage view."""
        from agno.team._session import _scrub_member_responses_storage_view, save_run

        db = InMemoryDb()
        _seed_team(db, with_member_data=True)
        team = self._team(db)
        session = db.get_session("t1", session_type=SessionType.TEAM)
        for i, run in enumerate(session.runs):
            save_run(team, run=run, session_id="t1", user_id="u1", run_index=i)

        reloaded = db.get_session("t1", session_type=SessionType.TEAM)
        for run in reloaded.runs:
            assert _scrub_member_responses_storage_view(team, run) is run


class TestSqliteTeamRunObjectCache:
    @pytest.fixture
    def sqlite_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        return SqliteDb(db_file=str(tmp_path / "team-cache.db"))

    def test_reads_share_history_run_objects(self, sqlite_db):
        _seed_team(sqlite_db)
        first = sqlite_db.get_session("t1", session_type=SessionType.TEAM)
        second = sqlite_db.get_session("t1", session_type=SessionType.TEAM)
        assert first.runs is not second.runs
        assert [id(r) for r in first.runs] == [id(r) for r in second.runs]

    def test_updating_a_run_invalidates_only_that_run(self, sqlite_db):
        _seed_team(sqlite_db)
        first = sqlite_db.get_session("t1", session_type=SessionType.TEAM)
        sqlite_db.upsert_run({"run_id": "r1", "team_id": "tm1", "content": "rewritten", "status": "COMPLETED"}, "t1")
        second = sqlite_db.get_session("t1", session_type=SessionType.TEAM)
        assert second.runs[1].content == "rewritten"
        assert first.runs[1].content == "content 1"
        assert second.runs[0] is first.runs[0]
        assert second.runs[2] is first.runs[2]

    def test_another_writer_to_the_same_file_is_seen(self, sqlite_db, tmp_path):
        from agno.db.sqlite import SqliteDb

        _seed_team(sqlite_db)
        sqlite_db.get_session("t1", session_type=SessionType.TEAM)

        other = SqliteDb(db_file=str(tmp_path / "team-cache.db"))
        other.upsert_run(
            {"run_id": "r1", "team_id": "tm1", "content": "written elsewhere", "status": "COMPLETED"}, "t1"
        )

        again = sqlite_db.get_session("t1", session_type=SessionType.TEAM)
        assert again.runs[1].content == "written elsewhere"

    def test_content_matches_the_uncached_rebuild(self, sqlite_db):
        _seed_team(sqlite_db, with_member_data=True)
        cached = sqlite_db.get_session("t1", session_type=SessionType.TEAM)
        raw = sqlite_db.get_session("t1", session_type=SessionType.TEAM, deserialize=False)
        rebuilt = TeamSession.from_dict(raw)
        assert [r.to_dict() for r in cached.runs] == [r.to_dict() for r in rebuilt.runs]


class TestTeamHardenedMutators:
    def test_team_regenerate_flips_status_on_a_copy(self):
        from unittest.mock import MagicMock

        from agno.team._run import _mark_team_run_regenerated

        db = InMemoryDb()
        _seed_team(db)
        team = MagicMock()
        team.db = db
        team.parent_team_id = None
        team.workflow_id = None
        team.store_member_responses = True

        before = db.get_session("t1", session_type=SessionType.TEAM)
        target_run = before.runs[0]
        session_view = db.get_session("t1", session_type=SessionType.TEAM)

        _mark_team_run_regenerated(team, session_view, target_run.run_id)

        # The other reader's object is untouched; the store has the flip.
        assert target_run.status != RunStatus.regenerated
        after = db.get_session("t1", session_type=SessionType.TEAM)
        assert after.runs[0].status == RunStatus.regenerated
        # The mutated session view sees its own flip.
        assert session_view.runs[0].status == RunStatus.regenerated


# ---------------------------------------------------------------------------
# Workflow sessions
# ---------------------------------------------------------------------------


def _seed_workflow(db, session_id: str = "w1", n_runs: int = 3) -> None:
    db.upsert_session(WorkflowSession(session_id=session_id, workflow_id="wf1", user_id="u1"))
    for i in range(n_runs):
        db.upsert_run(
            {"run_id": f"wr{i}", "workflow_id": "wf1", "content": f"content {i}", "status": "COMPLETED"},
            session_id=session_id,
        )
        # A step's agent run shares the workflow's session id; the session's
        # own runs list must not surface it.
        db.upsert_run(
            {
                "run_id": f"sr{i}",
                "agent_id": "step-agent",
                "content": f"step {i}",
                "status": "COMPLETED",
                "parent_run_id": f"wr{i}",
            },
            session_id=session_id,
        )


class TestWorkflowRunObjectCache:
    def test_reads_share_history_run_objects(self):
        db = InMemoryDb()
        _seed_workflow(db)
        first = db.get_session("w1", session_type=SessionType.WORKFLOW)
        second = db.get_session("w1", session_type=SessionType.WORKFLOW)
        assert first is not second
        assert [id(r) for r in first.runs] == [id(r) for r in second.runs]

    def test_step_runs_are_filtered_like_the_uncached_rebuild(self):
        db = InMemoryDb()
        _seed_workflow(db)
        cached = db.get_session("w1", session_type=SessionType.WORKFLOW)
        raw = db.get_session("w1", session_type=SessionType.WORKFLOW, deserialize=False)
        rebuilt = WorkflowSession.from_dict(raw)
        assert [r.run_id for r in cached.runs] == ["wr0", "wr1", "wr2"]
        assert [r.to_dict() for r in cached.runs] == [r.to_dict() for r in rebuilt.runs]

    def test_mutating_a_returned_run_never_reaches_the_stored_dicts(self):
        db = InMemoryDb()
        _seed_workflow(db)
        session = db.get_session("w1", session_type=SessionType.WORKFLOW)
        session.runs[0].content = "caller vandalism"
        raw = db.get_session("w1", session_type=SessionType.WORKFLOW, deserialize=False)
        stored = {r["run_id"]: r for r in raw["runs"]}
        assert stored["wr0"]["content"] == "content 0"

    def test_get_run_returns_a_copy(self):
        """The workflow continue pipeline and the queue worker fetch via
        get_run and mutate before persisting; the shared object must not
        carry those mutations."""
        db = InMemoryDb()
        _seed_workflow(db)
        session = db.get_session("w1", session_type=SessionType.WORKFLOW)
        fetched = session.get_run("wr1")
        fetched.status = RunStatus.cancelled
        fetched.content = "sweeper text"

        later = db.get_session("w1", session_type=SessionType.WORKFLOW)
        assert later.get_run("wr1").status != RunStatus.cancelled

    def test_sqlite_reads_share_and_invalidate_per_run(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "wf-cache.db"))
        _seed_workflow(db)
        first = db.get_session("w1", session_type=SessionType.WORKFLOW)
        second = db.get_session("w1", session_type=SessionType.WORKFLOW)
        assert [id(r) for r in first.runs] == [id(r) for r in second.runs]

        db.upsert_run({"run_id": "wr1", "workflow_id": "wf1", "content": "rewritten", "status": "COMPLETED"}, "w1")
        third = db.get_session("w1", session_type=SessionType.WORKFLOW)
        assert [r.run_id for r in third.runs] == ["wr0", "wr1", "wr2"]
        assert third.runs[1].content == "rewritten"
        assert first.runs[1].content == "content 1"
        assert third.runs[0] is first.runs[0]
        assert third.runs[2] is first.runs[2]

    def test_sqlite_content_matches_the_uncached_rebuild(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "wf-rebuild.db"))
        _seed_workflow(db)
        cached = db.get_session("w1", session_type=SessionType.WORKFLOW)
        raw = db.get_session("w1", session_type=SessionType.WORKFLOW, deserialize=False)
        rebuilt = WorkflowSession.from_dict(raw)
        assert [r.to_dict() for r in cached.runs] == [r.to_dict() for r in rebuilt.runs]
