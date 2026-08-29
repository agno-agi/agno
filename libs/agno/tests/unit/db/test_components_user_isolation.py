"""Unit tests for per-user component isolation.

Verifies that component reads, writes and deletes scope by ``user_id`` when one is
supplied, and stay global when it is ``None``. Exercised against SQLite so the suite
needs no external services.

Isolation is asymmetric by design, and the split runs through this whole file:
writes are owner-scoped always, while reads scope on *stage*. A draft is the
owner's alone; publishing puts a component on the platform, so a published row
reads across owners and an archived one is withdrawn again. Read tests therefore
pin both halves -- a foreign draft invisible, a foreign published row visible --
because a filter that hides everything passes the first half on its own.
"""

import pytest
from fastapi import HTTPException

from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.routers.components.components import _validate_referenced_component_ownership


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "components_isolation.db"))


def _make(db, component_id, user_id, component_type=ComponentType.AGENT, stage="published"):
    """Create a component owned by ``user_id``.

    Defaults to published -- on the platform for everyone. Pass ``stage="draft"``
    for the owner-private case.
    """
    db.create_component_with_config(
        component_id=component_id,
        component_type=component_type,
        name=component_id,
        config={"name": component_id},
        stage=stage,
        user_id=user_id,
    )


def _draft(db, component_id, user_id, component_type=ComponentType.AGENT):
    _make(db, component_id, user_id, component_type, stage="draft")


class TestScopedReads:
    def test_list_hides_another_owners_draft(self, db):
        _make(db, "c_alice", "alice")
        _draft(db, "c_bob", "bob")

        alice_rows, alice_total = db.list_components(user_id="alice")
        assert [r["component_id"] for r in alice_rows] == ["c_alice"]
        assert alice_total == 1

    def test_list_includes_another_owners_published_component(self, db):
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")

        alice_rows, alice_total = db.list_components(user_id="alice")
        assert {r["component_id"] for r in alice_rows} == {"c_alice", "c_bob"}
        assert alice_total == 2

    def test_list_hides_another_owners_archived_component(self, db):
        """Archiving is the off-switch: it withdraws a published component from
        everyone else, including under include_deleted, which relaxes the
        tombstone filter for the owner's own history only."""
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")
        assert db.delete_component("c_bob", user_id="bob") is True

        rows, total = db.list_components(user_id="alice", include_deleted=True)
        assert {r["component_id"] for r in rows} == {"c_alice"}
        assert total == 1
        owned, _ = db.list_components(user_id="bob", include_deleted=True)
        assert "c_bob" in {r["component_id"] for r in owned}

    def test_list_unscoped_sees_all(self, db):
        _make(db, "c_alice", "alice")
        _make(db, "c_bob", "bob")

        rows, total = db.list_components()
        assert {r["component_id"] for r in rows} == {"c_alice", "c_bob"}
        assert total == 2

    def test_list_scoped_includes_shared(self, db):
        """A shared component lists for every scoped caller, matching read-by-id."""
        _make(db, "c_alice", "alice")
        _draft(db, "c_bob", "bob")
        _make(db, "c_shared", None)

        rows, total = db.list_components(user_id="alice")
        assert {r["component_id"] for r in rows} == {"c_alice", "c_shared"}
        assert total == 2

    def test_get_component_ownership(self, db):
        """Stage decides the read; ownership still decides the write."""
        _draft(db, "c_draft", "alice")
        _make(db, "c_published", "alice")

        assert db.get_component("c_draft", user_id="alice") is not None
        assert db.get_component("c_draft", user_id="bob") is None  # draft is alice's alone
        assert db.get_component("c_draft") is not None  # unscoped (admin) sees it

        assert db.get_component("c_published", user_id="bob") is not None  # on the platform
        # Seeing is not touching: the write stays owner-scoped.
        assert db.delete_component("c_published", user_id="bob") is False

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


class TestScopedConfigWrites:
    """The config writers are owner-scoped the same way the component writers are.

    Publishing shares a component for reading; writes are owner-scoped always.
    The scope is enforced on the component row inside the write transaction,
    so a foreign or shared row answers exactly as a missing one and nothing
    is written.
    """

    def test_upsert_config_scoped(self, db):
        _make(db, "c_alice", "alice")

        with pytest.raises(ValueError, match="not found"):
            db.upsert_config(component_id="c_alice", config={"name": "hacked"}, stage="published", user_id="bob")
        assert len(db.list_configs("c_alice")) == 1

        appended = db.upsert_config(component_id="c_alice", config={"name": "mine"}, user_id="alice")
        assert appended["version"] == 2

    def test_upsert_config_scoped_refuses_shared_row(self, db):
        _make(db, "c_shared", None)

        with pytest.raises(ValueError, match="not found"):
            db.upsert_config(component_id="c_shared", config={"name": "hacked"}, user_id="alice")
        # An unscoped caller (operator) still writes.
        appended = db.upsert_config(component_id="c_shared", config={"name": "ok"})
        assert appended["version"] == 2

    def test_delete_config_scoped(self, db):
        _make(db, "c_alice", "alice")
        db.upsert_config(component_id="c_alice", config={"name": "draft"}, stage="draft", user_id="alice")

        assert db.delete_config("c_alice", version=2, user_id="bob") is False
        assert len(db.list_configs("c_alice")) == 2

        assert db.delete_config("c_alice", version=2, user_id="alice") is True

    def test_delete_config_scoped_answers_false_before_stage_verdicts(self, db):
        """A foreign probe learns nothing from stage: a published version and
        an archived component both answer the same False a missing version
        answers, never the owner's ComponentDraftRequiredError."""
        _make(db, "c_alice", "alice")
        assert db.delete_config("c_alice", version=1, user_id="bob") is False
        assert len(db.list_configs("c_alice")) == 1

        _make(db, "c_gone", "alice")
        assert db.delete_component("c_gone", user_id="alice") is True
        assert db.delete_config("c_gone", version=1, user_id="bob") is False

    def test_set_current_version_scoped(self, db):
        _make(db, "c_alice", "alice")
        db.upsert_config(component_id="c_alice", config={"name": "v2"}, stage="published", user_id="alice")
        assert db.get_component("c_alice")["current_version"] == 2

        assert db.set_current_version("c_alice", version=1, user_id="bob") is False
        assert db.get_component("c_alice")["current_version"] == 2

        assert db.set_current_version("c_alice", version=1, user_id="alice") is True
        assert db.get_component("c_alice")["current_version"] == 1

    def test_unscoped_config_writes_stay_global(self, db):
        _make(db, "c_alice", "alice")

        appended = db.upsert_config(component_id="c_alice", config={"name": "operator"}, stage="published")
        assert appended["version"] == 2
        assert db.set_current_version("c_alice", version=1) is True


class TestComponentIdIsTakenIsGeneric:
    def test_duplicate_id_does_not_confirm_other_users_component(self, db):
        """The clash error must not reveal that another user owns that id."""
        _make(db, "c_alice", "alice")

        with pytest.raises(ValueError) as exc:
            _make(db, "c_alice", "bob")

        assert "already exists" not in str(exc.value)


class TestNestedRehydrationScope:
    """A stored team must not rehydrate another user's private member."""

    def _make_team(self, db, component_id, user_id, members, stage="published"):
        db.create_component_with_config(
            component_id=component_id,
            component_type=ComponentType.TEAM,
            name=component_id,
            config={"name": component_id, "members": members},
            stage=stage,
            user_id=user_id,
        )

    def test_foreign_draft_member_not_rehydrated_for_owner(self, db):
        from agno.team.team import get_team_by_id

        _draft(db, "alice_agent", "alice")
        # bob's team references alice's draft agent, written straight into the DB
        self._make_team(db, "bob_team", "bob", [{"type": "agent", "agent_id": "alice_agent"}])

        team = get_team_by_id(db=db, id="bob_team", user_id="bob")
        assert team is not None
        assert "alice_agent" not in [getattr(m, "id", None) for m in (team.members or [])]

    def test_foreign_published_member_is_rehydrated(self, db):
        """The point of share-on-publish: bob's team really does run alice's
        published agent, so it has to resolve on the load path too."""
        from agno.team.team import get_team_by_id

        _make(db, "alice_agent", "alice")
        self._make_team(db, "bob_team", "bob", [{"type": "agent", "agent_id": "alice_agent"}])

        team = get_team_by_id(db=db, id="bob_team", user_id="bob")
        assert "alice_agent" in [getattr(m, "id", None) for m in (team.members or [])]

    def test_cross_user_draft_team_load_blocked(self, db):
        from agno.team.team import get_team_by_id

        self._make_team(db, "bob_team", "bob", [], stage="draft")

        assert get_team_by_id(db=db, id="bob_team", user_id="alice") is None

    def test_cross_user_published_team_loads(self, db):
        from agno.team.team import get_team_by_id

        self._make_team(db, "bob_team", "bob", [])

        assert get_team_by_id(db=db, id="bob_team", user_id="alice") is not None

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

    def test_foreign_draft_reference_refused(self, db):
        _draft(db, "c_bob", "bob")
        with pytest.raises(HTTPException) as exc:
            _validate_referenced_component_ownership(db, self._cfg("c_bob"), None, "alice")
        assert exc.value.status_code == 404

    def test_foreign_published_reference_allowed(self, db):
        """Composing another owner's published component is the feature, so the
        REST reference guard has to let it through as well."""
        _make(db, "c_bob", "bob")
        _validate_referenced_component_ownership(db, self._cfg("c_bob"), None, "alice")


class TestNoCrossLeak:
    def test_draft_totals_are_per_user(self, db):
        for i in range(3):
            _draft(db, f"a{i}", "alice")
        for i in range(2):
            _draft(db, f"b{i}", "bob")

        _, alice_total = db.list_components(user_id="alice")
        _, bob_total = db.list_components(user_id="bob")
        _, grand_total = db.list_components()
        assert (alice_total, bob_total, grand_total) == (3, 2, 5)

    def test_published_totals_count_the_whole_platform(self, db):
        """Totals follow visibility, so a published component counts for
        everyone -- the count and the rows must not disagree, or a paginating
        caller loops past the end."""
        for i in range(3):
            _make(db, f"a{i}", "alice")
        for i in range(2):
            _make(db, f"b{i}", "bob")

        alice_rows, alice_total = db.list_components(user_id="alice")
        assert alice_total == 5
        assert len(alice_rows) == 5

    def test_type_filter_and_owner_filter_compose(self, db):
        _make(db, "a_agent", "alice", ComponentType.AGENT)
        _make(db, "a_team", "alice", ComponentType.TEAM)
        _draft(db, "b_agent", "bob", ComponentType.AGENT)

        rows, total = db.list_components(component_type=ComponentType.AGENT, user_id="alice")
        assert [r["component_id"] for r in rows] == ["a_agent"]
        assert total == 1

    def test_type_filter_composes_with_a_published_foreign_row(self, db):
        _make(db, "a_agent", "alice", ComponentType.AGENT)
        _make(db, "b_agent", "bob", ComponentType.AGENT)
        _make(db, "b_team", "bob", ComponentType.TEAM)

        rows, total = db.list_components(component_type=ComponentType.AGENT, user_id="alice")
        assert {r["component_id"] for r in rows} == {"a_agent", "b_agent"}
        assert total == 2
