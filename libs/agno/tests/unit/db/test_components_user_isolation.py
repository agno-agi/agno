"""Unit tests for per-user component isolation.

Locks in the contract that component reads/writes/deletes scope by ``user_id``
when one is supplied (the OS passes the caller's id under user_isolation), and
stay global when it is ``None`` (single-user / admin).

Component persistence is implemented by the SQLite and Postgres adapters only;
SQLite is exercised here so the suite needs no external services.
"""

import pytest

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "components_isolation.db"))


def _make(db, component_id, user_id, component_type=ComponentType.AGENT):
    """Create a published component owned by ``user_id``."""
    db.create_component_with_config(
        component_id=component_id,
        component_type=component_type,
        name=component_id,
        config={"name": component_id},
        stage="published",
        user_id=user_id,
    )


class TestScopedReads:
    def test_list_scoped_to_owner(self, db):
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")

        alice_rows, alice_total = db.list_components(user_id="alice")
        assert [r["component_id"] for r in alice_rows] == ["c_alice"]
        assert alice_total == 1

    def test_list_unscoped_sees_all(self, db):
        """user_id=None (admin / single-user) sees every component."""
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")

        rows, total = db.list_components()
        assert {r["component_id"] for r in rows} == {"c_alice", "c_bob"}
        assert total == 2

    def test_get_component_ownership(self, db):
        _make(db, "c_alice", "alice")

        assert db.get_component("c_alice", user_id="alice") is not None
        assert db.get_component("c_alice", user_id="bob") is None  # cross-user blocked
        assert db.get_component("c_alice") is not None  # unscoped (admin) sees it

    def test_owner_is_persisted(self, db):
        _make(db, "c_alice", "alice")

        assert db.get_component("c_alice")["user_id"] == "alice"


class TestScopedWrites:
    def test_delete_scoped(self, db):
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")

        # bob cannot delete alice's component
        assert db.delete_component("c_alice", user_id="bob") is False
        assert db.get_component("c_alice") is not None

        # alice can delete her own
        assert db.delete_component("c_alice", user_id="alice") is True
        assert db.get_component("c_alice") is None
        # bob's component untouched
        assert db.get_component("c_bob") is not None

    def test_upsert_scoped(self, db):
        _make(db, "c_alice", "alice")

        # bob cannot update alice's component -> fails closed instead of creating
        with pytest.raises(ValueError):
            db.upsert_component(component_id="c_alice", name="hacked", user_id="bob")
        assert db.get_component("c_alice")["name"] != "hacked"

        # alice can update her own
        updated = db.upsert_component(component_id="c_alice", name="my agent", user_id="alice")
        assert updated["name"] == "my agent"

    def test_upsert_does_not_reassign_owner(self, db):
        """A scoped update must not silently move the component to another owner."""
        _make(db, "c_alice", "alice")

        db.upsert_component(component_id="c_alice", name="renamed", user_id="alice")

        assert db.get_component("c_alice")["user_id"] == "alice"


class TestComponentIdIsTakenIsGeneric:
    def test_duplicate_id_does_not_confirm_other_users_component(self, db):
        """The clash error must not reveal that another user owns that id."""
        _make(db, "c_alice", "alice")

        with pytest.raises(ValueError) as exc:
            _make(db, "c_alice", "bob")

        assert "already exists" not in str(exc.value)


class TestNestedRehydrationScope:
    """The owner ContextVar must stop a stored team from rehydrating another
    user's private member, even when the reference was smuggled straight into
    the DB (bypassing the route-level ownership check on create)."""

    def _make_team(self, db, component_id, user_id, members):
        db.create_component_with_config(
            component_id=component_id,
            component_type=ComponentType.TEAM,
            name=component_id,
            config={"name": component_id, "members": members},
            stage="published",
            user_id=user_id,
        )

    def test_foreign_private_member_not_rehydrated_for_owner(self, db):
        from agno.team.team import get_team_by_id

        _make(db, "alice_agent", "alice")
        # bob's team references alice's private agent directly in the DB.
        self._make_team(db, "bob_team", "bob", [{"type": "agent", "agent_id": "alice_agent"}])

        team = get_team_by_id(db=db, id="bob_team", user_id="bob")
        assert team is not None
        assert "alice_agent" not in [getattr(m, "id", None) for m in (team.members or [])]

    def test_cross_user_team_load_blocked(self, db):
        from agno.team.team import get_team_by_id

        self._make_team(db, "bob_team", "bob", [])

        assert get_team_by_id(db=db, id="bob_team", user_id="alice") is None

    def test_admin_unscoped_resolves_member(self, db):
        from agno.team.team import get_team_by_id

        _make(db, "alice_agent", "alice")
        self._make_team(db, "bob_team", "bob", [{"type": "agent", "agent_id": "alice_agent"}])

        team = get_team_by_id(db=db, id="bob_team", user_id=None)
        assert "alice_agent" in [getattr(m, "id", None) for m in (team.members or [])]


class TestNoCrossLeak:
    def test_totals_are_per_user(self, db):
        for i in range(3):
            _make(db, f"a{i}", "alice")
        for i in range(2):
            _make(db, f"b{i}", "bob")

        _, alice_total = db.list_components(user_id="alice")
        _, bob_total = db.list_components(user_id="bob")
        _, grand_total = db.list_components()
        assert (alice_total, bob_total, grand_total) == (3, 2, 5)

    def test_type_filter_and_owner_filter_compose(self, db):
        _make(db, "a_agent", "alice", ComponentType.AGENT)
        _make(db, "a_team", "alice", ComponentType.TEAM)
        _make(db, "b_agent", "bob", ComponentType.AGENT)

        rows, total = db.list_components(component_type=ComponentType.AGENT, user_id="alice")
        assert [r["component_id"] for r in rows] == ["a_agent"]
        assert total == 1
