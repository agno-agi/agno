"""Unit tests for InMemoryDb session storage keyed by session_id.

Sessions are stored in a dict keyed by session_id so get_session and
upsert_session are O(1) instead of scanning a list. These tests pin the
semantics that must survive the rekey: insertion order in listings,
filtering and pagination, the upsert owner guard, deepcopy isolation,
and the metrics helpers that iterate all sessions.
"""

from agno.db.base import SessionType
from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.session import AgentSession, TeamSession


def _agent_session(session_id: str, agent_id: str = "a1", user_id: str = "alice", created_at: int = 1000):
    return AgentSession(session_id=session_id, agent_id=agent_id, user_id=user_id, created_at=created_at)


class TestUpsertAndGetSession:
    def test_insert_then_get_roundtrip(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))

        session = db.get_session("s1", session_type=SessionType.AGENT)
        assert session is not None
        assert session.session_id == "s1"
        assert session.agent_id == "a1"

    def test_get_returns_dict_when_deserialize_false(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))

        raw = db.get_session("s1", deserialize=False)
        assert isinstance(raw, dict)
        assert raw["session_id"] == "s1"
        assert raw["session_type"] == SessionType.AGENT.value

    def test_get_unknown_session_returns_none(self):
        db = InMemoryDb()
        assert db.get_session("missing") is None

    def test_get_with_wrong_user_id_returns_none(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", user_id="alice"))
        assert db.get_session("s1", user_id="bob") is None
        assert db.get_session("s1", user_id="alice") is not None

    def test_insert_sets_created_and_updated_at(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", created_at=1234))
        raw = db.get_session("s1", deserialize=False)
        assert raw["created_at"] == 1234
        assert raw["updated_at"] == 1234

    def test_update_replaces_single_entry(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", created_at=1000))
        updated = _agent_session("s1", created_at=1000)
        updated.session_data = {"session_name": "renamed"}
        db.upsert_session(updated)

        assert len(db._sessions) == 1
        raw = db.get_session("s1", deserialize=False)
        assert raw["session_data"]["session_name"] == "renamed"
        assert raw["updated_at"] >= raw["created_at"]

    def test_returned_dict_is_a_copy(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        raw = db.get_session("s1", deserialize=False)
        raw["user_id"] = "MUTATED"
        assert db.get_session("s1", deserialize=False)["user_id"] == "alice"

    def test_store_is_isolated_from_upsert_input(self):
        db = InMemoryDb()
        session = _agent_session("s1")
        session.session_data = {"session_name": "before"}
        db.upsert_session(session)
        session.session_data["session_name"] = "after"
        assert db.get_session("s1", deserialize=False)["session_data"]["session_name"] == "before"


class TestUpsertOwnerGuard:
    def test_other_users_write_is_rejected(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", user_id="alice"))

        result = db.upsert_session(_agent_session("s1", user_id="bob"))
        assert result is None
        assert db.get_session("s1", deserialize=False)["user_id"] == "alice"

    def test_unowned_session_can_be_claimed(self):
        db = InMemoryDb()
        db.upsert_session(AgentSession(session_id="s1", agent_id="a1", user_id=None, created_at=1000))

        result = db.upsert_session(_agent_session("s1", user_id="alice"))
        assert result is not None
        assert db.get_session("s1", deserialize=False)["user_id"] == "alice"

    def test_same_session_id_different_component_overwrites(self):
        # Mirrors the SQL adapters: session_id is the sole conflict key, so a
        # same-owner write with a different component id updates the row
        # instead of creating a duplicate session_id entry.
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", agent_id="a1"))
        db.upsert_session(_agent_session("s1", agent_id="a2"))

        assert len(db._sessions) == 1
        assert db.get_session("s1", deserialize=False)["agent_id"] == "a2"

    def test_same_session_id_different_type_overwrites(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        db.upsert_session(TeamSession(session_id="s1", team_id="t1", user_id="alice", created_at=1000))

        assert len(db._sessions) == 1
        raw = db.get_session("s1", deserialize=False)
        assert raw["session_type"] == SessionType.TEAM.value
        assert raw["team_id"] == "t1"


class TestUpsertSessionsBulk:
    def test_bulk_upsert_stores_all(self):
        db = InMemoryDb()
        results = db.upsert_sessions([_agent_session("s1"), _agent_session("s2"), None])
        assert len(results) == 2
        assert db.get_session("s1") is not None
        assert db.get_session("s2") is not None


class TestGetSessionsSemantics:
    def _seed(self, db):
        db.upsert_session(_agent_session("s1", agent_id="a1", user_id="alice", created_at=1000))
        db.upsert_session(_agent_session("s2", agent_id="a2", user_id="bob", created_at=3000))
        db.upsert_session(TeamSession(session_id="s3", team_id="t1", user_id="alice", created_at=2000))

    def test_unsorted_listing_preserves_insertion_order(self):
        db = InMemoryDb()
        self._seed(db)
        rows, total = db.get_sessions(deserialize=False)
        assert total == 3
        assert [r["session_id"] for r in rows] == ["s1", "s2", "s3"]

    def test_update_keeps_position_in_listing(self):
        db = InMemoryDb()
        self._seed(db)
        db.upsert_session(_agent_session("s1", agent_id="a1", user_id="alice", created_at=1000))
        rows, _ = db.get_sessions(deserialize=False)
        assert [r["session_id"] for r in rows] == ["s1", "s2", "s3"]

    def test_filter_by_user_id(self):
        db = InMemoryDb()
        self._seed(db)
        rows, total = db.get_sessions(user_id="alice", deserialize=False)
        assert total == 2
        assert {r["session_id"] for r in rows} == {"s1", "s3"}

    def test_filter_by_session_type(self):
        db = InMemoryDb()
        self._seed(db)
        sessions = db.get_sessions(session_type=SessionType.TEAM)
        assert [s.session_id for s in sessions] == ["s3"]

    def test_filter_by_component_id(self):
        db = InMemoryDb()
        self._seed(db)
        rows, total = db.get_sessions(session_type=SessionType.AGENT, component_id="a2", deserialize=False)
        assert total == 1
        assert rows[0]["session_id"] == "s2"

    def test_sorting_and_pagination(self):
        db = InMemoryDb()
        self._seed(db)
        page1, total = db.get_sessions(sort_by="created_at", sort_order="desc", limit=2, page=1, deserialize=False)
        page2, _ = db.get_sessions(sort_by="created_at", sort_order="desc", limit=2, page=2, deserialize=False)
        assert total == 3
        assert [r["session_id"] for r in page1] == ["s2", "s3"]
        assert [r["session_id"] for r in page2] == ["s1"]

    def test_timestamp_range_filter(self):
        db = InMemoryDb()
        self._seed(db)
        rows, total = db.get_sessions(start_timestamp=1500, end_timestamp=2500, deserialize=False)
        assert total == 1
        assert rows[0]["session_id"] == "s3"


class TestDeleteSessions:
    def test_delete_existing_returns_true(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        assert db.delete_session("s1") is True
        assert db.get_session("s1") is None

    def test_delete_unknown_returns_false(self):
        db = InMemoryDb()
        assert db.delete_session("missing") is False

    def test_bulk_delete_ignores_unknown_ids(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        db.upsert_session(_agent_session("s2"))
        db.delete_sessions(["s1", "missing"])
        assert db.get_session("s1") is None
        assert db.get_session("s2") is not None


class TestMetricsHelpersOverSessions:
    def test_all_sessions_visible_for_metrics(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", created_at=1000))
        db.upsert_session(_agent_session("s2", created_at=2000))
        sessions = db._get_all_sessions_for_metrics_calculation()
        assert len(sessions) == 2
        assert {s["created_at"] for s in sessions} == {1000, 2000}

    def test_metrics_range_filter(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", created_at=1000))
        db.upsert_session(_agent_session("s2", created_at=2000))
        sessions = db._get_all_sessions_for_metrics_calculation(start_timestamp=1500)
        assert len(sessions) == 1
        assert sessions[0]["created_at"] == 2000

    def test_starting_date_uses_earliest_session(self):
        from datetime import datetime, timezone

        db = InMemoryDb()
        db.upsert_session(_agent_session("s1", created_at=2000))
        db.upsert_session(_agent_session("s2", created_at=1000))
        starting_date = db._get_metrics_calculation_starting_date([])
        assert starting_date == datetime.fromtimestamp(1000, tz=timezone.utc).date()


class TestSessionRowAndRuns:
    """The session row is serialized without runs; the stored runs list is
    maintained incrementally by upsert_run. Saving the session row must
    neither drop those runs nor re-serialize them on every save."""

    def test_update_preserves_runs_written_by_upsert_run(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        db.upsert_run({"run_id": "r1", "content": "one"}, session_id="s1")
        db.upsert_run({"run_id": "r2", "content": "two"}, session_id="s1")

        # A later session-row update must carry the stored runs forward
        db.upsert_session(_agent_session("s1"))

        raw = db.get_session("s1", deserialize=False)
        assert [r["run_id"] for r in raw["runs"]] == ["r1", "r2"]

    def test_update_ignores_stale_runs_on_the_incoming_session(self):
        from agno.run.agent import RunOutput

        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        db.upsert_run({"run_id": "r1", "content": "stored"}, session_id="s1")

        stale = _agent_session("s1")
        stale.runs = [RunOutput(run_id="stale-run", content="should not land")]
        db.upsert_session(stale)

        raw = db.get_session("s1", deserialize=False)
        assert [r["run_id"] for r in raw["runs"]] == ["r1"]

    def test_insert_serializes_incoming_runs(self):
        from agno.run.agent import RunOutput

        db = InMemoryDb()
        session = _agent_session("s1")
        session.runs = [RunOutput(run_id="r1", agent_id="a1", content="imported")]
        db.upsert_session(session)

        raw = db.get_session("s1", deserialize=False)
        assert raw["runs"][0]["run_id"] == "r1"

        roundtrip = db.get_session("s1", session_type=SessionType.AGENT)
        assert roundtrip.runs and roundtrip.runs[0].run_id == "r1"

    def test_upsert_return_carries_the_incoming_runs_not_the_stored_history(self):
        """The write-path return matches the SQL adapters: the caller gets its
        own runs back by reference, never a rebuild of the stored history --
        which kept every save O(session length). The stored runs stay put."""
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        db.upsert_run({"run_id": "r1", "content": "one"}, session_id="s1")

        result = db.upsert_session(_agent_session("s1"), deserialize=False)
        assert result["runs"] == []

        raw = db.get_session("s1", deserialize=False)
        assert [r["run_id"] for r in raw["runs"]] == ["r1"]

    def test_stored_runs_are_isolated_from_the_returned_copy(self):
        db = InMemoryDb()
        db.upsert_session(_agent_session("s1"))
        db.upsert_run({"run_id": "r1", "content": "one"}, session_id="s1")

        incoming = _agent_session("s1")
        result = db.upsert_session(incoming, deserialize=False)
        result["session_data"] = {"poisoned": True}
        result["runs"].append({"run_id": "bogus"})

        raw = db.get_session("s1", deserialize=False)
        assert (raw.get("session_data") or {}).get("poisoned") is None
        assert [r["run_id"] for r in raw["runs"]] == ["r1"]
