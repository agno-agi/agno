"""Unit tests for InMemoryDb direct-run APIs.

Regression tests for the PR-review finding that InMemoryDb inherited the
BaseDb no-op stubs for ``get_run`` / ``get_runs`` / ``upsert_run`` /
``delete_run`` / ``delete_runs``. Every other adapter overrides these; the
methods below verify InMemoryDb now does too, walking runs stored inline on
the session dict.
"""

from __future__ import annotations

import pytest

from agno.db.base import BaseDb
from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


def _make_run(run_id: str, session_id: str, content: str, agent_id: str = "agent-1") -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id=agent_id,
        session_id=session_id,
        content=content,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content=f"q-{content}"),
            Message(role="assistant", content=f"a-{content}"),
        ],
    )


@pytest.fixture
def db_with_two_sessions():
    """One session with 3 runs, another with 2 runs, so filters can be meaningful."""
    db = InMemoryDb()

    s1 = AgentSession(session_id="s1", agent_id="agent-1", user_id="alice")
    s1.upsert_run(_make_run("r1", "s1", "hello", agent_id="agent-1"))
    s1.upsert_run(_make_run("r2", "s1", "world", agent_id="agent-1"))
    s1.upsert_run(_make_run("r3", "s1", "!", agent_id="agent-1"))
    db.upsert_session(s1)

    s2 = AgentSession(session_id="s2", agent_id="agent-2", user_id="bob")
    s2.upsert_run(_make_run("r4", "s2", "foo", agent_id="agent-2"))
    s2.upsert_run(_make_run("r5", "s2", "bar", agent_id="agent-2"))
    db.upsert_session(s2)
    return db


class TestOverrideStatus:
    """Ensures InMemoryDb no longer inherits the no-op base stubs."""

    @pytest.mark.parametrize("method", ["get_run", "get_runs", "upsert_run", "delete_run", "delete_runs"])
    def test_overrides_base_stub(self, method: str):
        assert getattr(InMemoryDb, method) is not getattr(BaseDb, method), (
            f"InMemoryDb.{method} must override BaseDb.{method} — otherwise callers get "
            "wrong data (None / [] / NotImplementedError) even when runs exist inline on the session."
        )


class TestGetRun:
    def test_returns_run_when_present(self, db_with_two_sessions):
        run = db_with_two_sessions.get_run("r2")
        assert run is not None
        assert run.run_id == "r2"
        assert run.content == "world"

    def test_returns_run_from_second_session(self, db_with_two_sessions):
        run = db_with_two_sessions.get_run("r4")
        assert run is not None
        assert run.session_id == "s2"

    def test_returns_none_for_unknown_run(self, db_with_two_sessions):
        assert db_with_two_sessions.get_run("does-not-exist") is None

    def test_deserialize_false_returns_dict(self, db_with_two_sessions):
        raw = db_with_two_sessions.get_run("r1", deserialize=False)
        assert isinstance(raw, dict)
        assert raw["run_id"] == "r1"

    def test_returns_deepcopy_not_live_reference(self, db_with_two_sessions):
        raw = db_with_two_sessions.get_run("r1", deserialize=False)
        raw["content"] = "MUTATED"
        stored = db_with_two_sessions.get_run("r1", deserialize=False)
        assert stored["content"] == "hello", "caller mutation must not leak into stored state"


class TestGetRuns:
    def test_returns_all_runs_when_no_filter(self, db_with_two_sessions):
        ids = [r.run_id for r in db_with_two_sessions.get_runs()]
        assert set(ids) == {"r1", "r2", "r3", "r4", "r5"}

    def test_filters_by_session_id(self, db_with_two_sessions):
        ids = [r.run_id for r in db_with_two_sessions.get_runs(session_id="s1")]
        assert ids == ["r1", "r2", "r3"], "session_id filter + default sort by run_index"

    def test_filters_by_user_id(self, db_with_two_sessions):
        ids = [r.run_id for r in db_with_two_sessions.get_runs(user_id="bob")]
        assert set(ids) == {"r4", "r5"}

    def test_filters_by_agent_id(self, db_with_two_sessions):
        ids = [r.run_id for r in db_with_two_sessions.get_runs(agent_id="agent-1")]
        assert set(ids) == {"r1", "r2", "r3"}

    def test_filters_by_status(self, db_with_two_sessions):
        # Every seeded run has RunStatus.completed
        ids = [r.run_id for r in db_with_two_sessions.get_runs(status=RunStatus.completed)]
        assert len(ids) == 5

    def test_status_filter_supports_string_value(self, db_with_two_sessions):
        ids = [r.run_id for r in db_with_two_sessions.get_runs(status="COMPLETED")]
        assert len(ids) == 5

    def test_status_filter_no_match(self, db_with_two_sessions):
        assert db_with_two_sessions.get_runs(status=RunStatus.error) == []

    def test_deserialize_false_returns_tuple_with_total(self, db_with_two_sessions):
        rows, total = db_with_two_sessions.get_runs(session_id="s1", deserialize=False)
        assert total == 3
        assert [r["run_id"] for r in rows] == ["r1", "r2", "r3"]

    def test_limit_and_page(self, db_with_two_sessions):
        page1 = db_with_two_sessions.get_runs(session_id="s1", limit=2, page=1)
        page2 = db_with_two_sessions.get_runs(session_id="s1", limit=2, page=2)
        assert [r.run_id for r in page1] == ["r1", "r2"]
        assert [r.run_id for r in page2] == ["r3"]

    def test_limit_without_page_returns_first_n(self, db_with_two_sessions):
        page = db_with_two_sessions.get_runs(session_id="s1", limit=1)
        assert [r.run_id for r in page] == ["r1"]

    def test_combined_filters(self, db_with_two_sessions):
        # user_id=alice AND agent_id=agent-1 == same set (both apply to s1)
        ids = [r.run_id for r in db_with_two_sessions.get_runs(user_id="alice", agent_id="agent-1")]
        assert set(ids) == {"r1", "r2", "r3"}

    def test_combined_filters_no_overlap(self, db_with_two_sessions):
        # user_id=alice but agent_id=agent-2 -> no rows
        assert db_with_two_sessions.get_runs(user_id="alice", agent_id="agent-2") == []


class TestUpsertRun:
    def test_insert_new_run_into_existing_session(self, db_with_two_sessions):
        new_run = _make_run("rNEW", "s1", "brand new")
        db_with_two_sessions.upsert_run(run=new_run, session_id="s1", user_id="alice")
        ids = [r.run_id for r in db_with_two_sessions.get_runs(session_id="s1")]
        assert "rNEW" in ids
        # And retrievable directly
        got = db_with_two_sessions.get_run("rNEW")
        assert got is not None and got.content == "brand new"

    def test_update_existing_run_replaces_in_place(self, db_with_two_sessions):
        updated = _make_run("r1", "s1", "hello-updated")
        db_with_two_sessions.upsert_run(run=updated, session_id="s1", user_id="alice")
        got = db_with_two_sessions.get_run("r1")
        assert got.content == "hello-updated"
        # Should still be exactly one row for r1
        ids = [r.run_id for r in db_with_two_sessions.get_runs(session_id="s1")]
        assert ids.count("r1") == 1

    def test_update_preserves_original_run_index(self, db_with_two_sessions):
        # Simulate an existing run with a specific run_index
        db_with_two_sessions._sessions["s1"]["runs"][0]["run_index"] = 42
        updated = _make_run("r1", "s1", "updated")
        db_with_two_sessions.upsert_run(run=updated, session_id="s1", user_id="alice", run_index=99)
        rows, _ = db_with_two_sessions.get_runs(session_id="s1", deserialize=False)
        r1_row = next(r for r in rows if r["run_id"] == "r1")
        assert r1_row["run_index"] == 42, "update must preserve original run_index, not overwrite with 99"

    def test_insert_uses_provided_run_index_when_not_in_run_data(self, db_with_two_sessions):
        new_run = _make_run("rNEW", "s1", "with index")
        db_with_two_sessions.upsert_run(run=new_run, session_id="s1", user_id="alice", run_index=7)
        rows, _ = db_with_two_sessions.get_runs(session_id="s1", deserialize=False)
        row = next(r for r in rows if r["run_id"] == "rNEW")
        assert row.get("run_index") == 7

    def test_unknown_session_is_a_noop(self, db_with_two_sessions):
        new_run = _make_run("rGHOST", "nonexistent-session", "orphan")
        db_with_two_sessions.upsert_run(run=new_run, session_id="nonexistent-session")
        assert db_with_two_sessions.get_run("rGHOST") is None
        # Nothing added to any real session either
        assert "rGHOST" not in [r.run_id for r in db_with_two_sessions.get_runs()]

    def test_missing_run_id_raises(self, db_with_two_sessions):
        with pytest.raises(ValueError, match="run_id"):
            db_with_two_sessions.upsert_run(run={"content": "no id"}, session_id="s1")


class TestDeleteRun:
    def test_delete_existing_run(self, db_with_two_sessions):
        assert db_with_two_sessions.delete_run("r2") is True
        assert db_with_two_sessions.get_run("r2") is None
        # Others in the same session still present
        ids = [r.run_id for r in db_with_two_sessions.get_runs(session_id="s1")]
        assert set(ids) == {"r1", "r3"}

    def test_delete_unknown_run_returns_false(self, db_with_two_sessions):
        assert db_with_two_sessions.delete_run("does-not-exist") is False

    def test_delete_updates_session_updated_at(self, db_with_two_sessions):
        stored = db_with_two_sessions._sessions["s1"]
        # Set updated_at to a sentinel low value so we can detect the bump without sleeping.
        stored["updated_at"] = 1
        db_with_two_sessions.delete_run("r1")
        assert stored["updated_at"] > 1

    def test_delete_last_run_leaves_empty_list(self, db_with_two_sessions):
        for rid in ["r4", "r5"]:
            db_with_two_sessions.delete_run(rid)
        assert db_with_two_sessions.get_runs(session_id="s2") == []


class TestDeleteRuns:
    def test_bulk_delete_multiple(self, db_with_two_sessions):
        db_with_two_sessions.delete_runs(["r1", "r3", "r5"])
        remaining = {r.run_id for r in db_with_two_sessions.get_runs()}
        assert remaining == {"r2", "r4"}

    def test_bulk_delete_ignores_unknowns(self, db_with_two_sessions):
        db_with_two_sessions.delete_runs(["r1", "does-not-exist", "also-nope"])
        remaining = {r.run_id for r in db_with_two_sessions.get_runs()}
        assert remaining == {"r2", "r3", "r4", "r5"}

    def test_empty_list_is_a_noop(self, db_with_two_sessions):
        db_with_two_sessions.delete_runs([])
        assert len(list(db_with_two_sessions.get_runs())) == 5


class TestParityWithUpsertSession:
    """upsert_session still works (v2.x inline path) — the new run APIs are additive."""

    def test_upsert_session_still_writes_runs_inline(self):
        db = InMemoryDb()
        s = AgentSession(session_id="sx", agent_id="agent-1", user_id="u1")
        s.upsert_run(_make_run("r1", "sx", "one"))
        s.upsert_run(_make_run("r2", "sx", "two"))
        db.upsert_session(s)
        # Runs discoverable via get_run and get_runs, without any explicit upsert_run call
        assert db.get_run("r1") is not None
        assert db.get_run("r2") is not None
        assert [r.run_id for r in db.get_runs(session_id="sx")] == ["r1", "r2"]

    def test_upsert_run_after_upsert_session_stays_consistent(self):
        db = InMemoryDb()
        s = AgentSession(session_id="sy", agent_id="agent-1", user_id="u1")
        s.upsert_run(_make_run("r1", "sy", "one"))
        db.upsert_session(s)
        # Add a new run purely through the direct API
        db.upsert_run(run=_make_run("r2", "sy", "two"), session_id="sy", user_id="u1")
        # Both surfaces agree
        assert [r.run_id for r in db.get_runs(session_id="sy")] == ["r1", "r2"]
