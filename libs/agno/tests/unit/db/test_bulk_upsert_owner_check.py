"""``upsert_sessions`` must apply the same owner check as ``upsert_session``.

The single-row upsert refuses to update a stored session whose ``user_id``
differs from the incoming one, which is what backs ``user_isolation=True`` on
AgentOS. The MySQL and SingleStore bulk paths had no such check, so a batch
containing another user's ``session_id`` reassigned the stored row to the new
user and overwrote its data.

Neither backend can be started in unit tests, so these tests cover the pure
filtering helper that makes the decision, plus the wiring that calls it inside
each adapter's bulk transaction.
"""

from __future__ import annotations

import inspect

import pytest

from agno.session.agent import AgentSession


def _session(user_id, marker: str, session_id: str = "shared") -> AgentSession:
    return AgentSession(
        session_id=session_id,
        agent_id="a1",
        user_id=user_id,
        session_data={"session_state": {"owner": marker}},
        created_at=1000,
        updated_at=1000,
    )


class TestFilterSessionsByOwner:
    """The rule: an owned session is only writable by its owner; an unowned
    session can be claimed by anyone."""

    @pytest.fixture(params=["mysql", "singlestore"])
    def filter_fn(self, request):
        if request.param == "mysql":
            from agno.db.mysql.utils import filter_sessions_by_owner
        else:
            from agno.db.singlestore.utils import filter_sessions_by_owner
        return filter_sessions_by_owner

    def test_another_users_session_is_dropped(self, filter_fn):
        incoming = [_session("bob", "bob-data")]
        assert filter_fn({"shared": "alice"}, incoming) == []

    def test_owners_own_session_is_kept(self, filter_fn):
        incoming = [_session("alice", "v2")]
        assert filter_fn({"shared": "alice"}, incoming) == incoming

    def test_unowned_stored_session_can_be_claimed(self, filter_fn):
        incoming = [_session("bob", "bob-data")]
        assert filter_fn({"shared": None}, incoming) == incoming

    def test_new_session_is_kept(self, filter_fn):
        incoming = [_session("bob", "bob-data")]
        assert filter_fn({}, incoming) == incoming

    def test_anonymous_write_over_owned_session_is_dropped(self, filter_fn):
        """A None incoming user_id must not take over an owned row."""
        incoming = [_session(None, "anon-data")]
        assert filter_fn({"shared": "alice"}, incoming) == []

    def test_only_the_mismatched_sessions_are_dropped(self, filter_fn):
        mine = _session("alice", "mine", session_id="s1")
        theirs = _session("bob", "theirs", session_id="s2")
        fresh = _session("bob", "fresh", session_id="s3")

        kept = filter_fn({"s1": "alice", "s2": "alice"}, [mine, theirs, fresh])

        assert kept == [mine, fresh]

    def test_empty_batch(self, filter_fn):
        assert filter_fn({}, []) == []

    def test_duplicate_id_in_batch_keeps_only_the_first_owner(self, filter_fn):
        """A batch carrying one id under two owners must not let the last
        write take over the row the first one just created."""
        alice = _session("alice", "alice-data")
        bob = _session("bob", "bob-data")

        assert filter_fn({}, [alice, bob]) == [alice]

    def test_duplicate_id_in_batch_under_one_owner_is_kept(self, filter_fn):
        first = _session("alice", "v1")
        second = _session("alice", "v2")

        assert filter_fn({}, [first, second]) == [first, second]

    def test_duplicate_id_claiming_an_unowned_row(self, filter_fn):
        """The first writer claims the unowned row; a second owner is dropped."""
        bob = _session("bob", "bob-data")
        carol = _session("carol", "carol-data")

        assert filter_fn({"shared": None}, [bob, carol]) == [bob]


class TestBulkUpsertWiring:
    """The filter has to run inside the write transaction, before any write."""

    @pytest.fixture(
        params=[
            ("agno.db.mysql.mysql", "MySQLDb", "fetch_session_owners"),
            ("agno.db.mysql.async_mysql", "AsyncMySQLDb", "afetch_session_owners"),
            ("agno.db.singlestore.singlestore", "SingleStoreDb", "fetch_session_owners"),
        ],
        ids=["mysql", "async_mysql", "singlestore"],
    )
    def adapter(self, request):
        module_path, cls_name, fetch_name = request.param
        try:
            module = __import__(module_path, fromlist=[cls_name])
        except ImportError:
            pytest.skip(f"{module_path} driver not installed")
        return module, getattr(module, cls_name), fetch_name

    def test_bulk_upsert_filters_by_owner(self, adapter):
        _, cls, fetch_name = adapter
        src = inspect.getsource(cls.upsert_sessions)

        assert fetch_name in src
        assert src.count("filter_sessions_by_owner") == 3

    def test_owner_check_precedes_the_first_write(self, adapter):
        _, cls, fetch_name = adapter
        src = inspect.getsource(cls.upsert_sessions)

        # The insert statements must all come after the ownership filter.
        assert src.index(fetch_name) < src.index("insert(table)")

    def test_owner_read_is_inside_the_write_transaction(self, adapter):
        """Reading owners outside the transaction would leave a race window."""
        _, cls, fetch_name = adapter
        src = inspect.getsource(cls.upsert_sessions)

        assert src.index("sess.begin()") < src.index(fetch_name)
