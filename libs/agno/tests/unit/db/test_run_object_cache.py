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
from agno.session import AgentSession


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
        another reader holds must keep its message list."""
        db = InMemoryDb()
        agent = Agent(model=MockModel(), db=db, telemetry=False)
        response = agent.run("one", session_id="s1", user_id="u1")

        shared = db.get_session("s1", session_type=SessionType.AGENT).runs[0]
        messages_before = list(shared.messages or [])

        try:
            agent.continue_run(run_id=response.run_id, session_id="s1", user_id="u1")
        except Exception:
            # A completed run may refuse to continue; the mutation contract is
            # what this test pins, not continuability.
            pass

        assert list(shared.messages or []) == messages_before
