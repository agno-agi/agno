"""Unit tests for per-user component isolation.

Verifies that component reads, writes and deletes scope by ``user_id`` when one is
supplied, and stay global when it is ``None``. Exercised against SQLite so the suite
needs no external services.
"""

import pytest
from fastapi import HTTPException

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components.components import _validate_referenced_component_ownership


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
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")

        rows, total = db.list_components()
        assert {r["component_id"] for r in rows} == {"c_alice", "c_bob"}
        assert total == 2

    def test_list_scoped_includes_shared(self, db):
        """A shared component lists for every scoped caller, matching read-by-id."""
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")
        _make(db, "c_shared", None)

        rows, total = db.list_components(user_id="alice")
        assert {r["component_id"] for r in rows} == {"c_alice", "c_shared"}
        assert total == 2

    def test_get_component_ownership(self, db):
        _make(db, "c_alice", "alice")

        assert db.get_component("c_alice", user_id="alice") is not None
        assert db.get_component("c_alice", user_id="bob") is None  # cross-user blocked
        assert db.get_component("c_alice") is not None  # unscoped (admin) sees it

    def test_owner_is_persisted(self, db):
        _make(db, "c_alice", "alice")

        assert db.get_component("c_alice")["user_id"] == "alice"

    def test_unowned_component_is_shared(self, db):
        """A component with no owner predates isolation: every scoped caller can read it."""
        _make(db, "c_shared", None)

        assert db.get_component("c_shared", user_id="alice") is not None
        assert db.get_component("c_shared") is not None


class TestScopedWrites:
    def test_delete_scoped(self, db):
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")

        assert db.delete_component("c_alice", user_id="bob") is False
        assert db.get_component("c_alice") is not None

        assert db.delete_component("c_alice", user_id="alice") is True
        assert db.get_component("c_alice") is None
        assert db.get_component("c_bob") is not None

    def test_scoped_delete_spares_shared_component(self, db):
        """A shared component is readable under scope, but only an unscoped caller removes it."""
        _make(db, "c_shared", None)

        assert db.delete_component("c_shared", user_id="alice") is False
        assert db.get_component("c_shared") is not None
        assert db.delete_component("c_shared") is True

    def test_upsert_scoped(self, db):
        _make(db, "c_alice", "alice")

        # A scoped miss fails closed instead of creating a second component for bob
        with pytest.raises(ValueError):
            db.upsert_component(component_id="c_alice", name="hacked", user_id="bob")
        assert db.get_component("c_alice")["name"] != "hacked"

        updated = db.upsert_component(component_id="c_alice", name="my agent", user_id="alice")
        assert updated["name"] == "my agent"

    def test_upsert_does_not_reassign_owner(self, db):
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
    """A stored team must not rehydrate another user's private member."""

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
        # bob's team references alice's private agent, written straight into the DB
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


class TestReferencedComponentOwnershipHelper:
    """Referencing own or shared components is allowed; another user's id is refused. An
    unresolvable id is allowed -- it may be a code-defined component."""

    def _cfg(self, ref):
        return {"steps": [{"name": "s", "agent_id": ref}]}

    def test_own_reference_allowed(self, db):
        _make(db, "c_alice", "alice")
        _validate_referenced_component_ownership(db, self._cfg("c_alice"), None, "alice")

    def test_shared_reference_allowed(self, db):
        _make(db, "c_shared", None)
        _validate_referenced_component_ownership(db, self._cfg("c_shared"), None, "alice")

    def test_unscoped_skips_check(self, db):
        _make(db, "c_bob", "bob")
        # An admin (unscoped) caller may reference any component.
        _validate_referenced_component_ownership(db, self._cfg("c_bob"), None, None)

    def test_missing_reference_allowed(self, db):
        # An id in no db row may be a code-defined component, so it is not refused.
        _validate_referenced_component_ownership(db, self._cfg("ghost"), None, "alice")

    def test_foreign_reference_refused(self, db):
        _make(db, "c_bob", "bob")
        with pytest.raises(HTTPException) as exc:
            _validate_referenced_component_ownership(db, self._cfg("c_bob"), None, "alice")
        assert exc.value.status_code == 404


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
