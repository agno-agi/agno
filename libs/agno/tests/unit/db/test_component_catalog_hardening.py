"""Catalog hardening semantics on the SQLite adapter.

The Studio 3.0 catalog contract: archived
ids are reserved and restored explicitly, deletes refuse to break pins,
version numbers are never reused (tombstones), compare-and-set guards are
optional kwargs, publishing re-projects identity onto the component row,
and link writes cannot close a cycle.
"""

import pytest

from agno.db.base import (
    DELETED_CONFIG_STAGE,
    ComponentArchivedError,
    ComponentCycleError,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentLastConfigError,
    ComponentType,
    ComponentVersionConflictError,
)
from agno.db.sqlite import SqliteDb


@pytest.fixture
def db(tmp_path):
    return SqliteDb(id="catalog-hardening-db", db_file=str(tmp_path / "catalog.db"))


def _mk(db, component_id="comp-a", stage="published", config=None):
    component, cfg = db.create_component_with_config(
        component_id=component_id,
        component_type=ComponentType.AGENT,
        name=component_id,
        config=config or {"name": component_id, "instructions": "hi"},
        stage=stage,
    )
    return component, cfg


# ----------------------------------------------------------------------
# Archive and restore
# ----------------------------------------------------------------------


class TestArchiveRestore:
    def test_archived_id_is_reserved(self, db):
        _mk(db)
        assert db.delete_component("comp-a") is True
        assert db.get_component("comp-a") is None
        assert db.get_component("comp-a", include_deleted=True) is not None
        # A create cannot take the id
        with pytest.raises(ValueError, match="not available"):
            _mk(db)
        # An upsert cannot silently reactivate it
        with pytest.raises(ComponentArchivedError):
            db.upsert_component(component_id="comp-a", component_type=ComponentType.AGENT, name="comp-a")
        # Nor can a config write
        with pytest.raises(ComponentArchivedError):
            db.upsert_config("comp-a", config={"name": "zombie"})

    def test_restore_brings_back_published_state(self, db):
        _mk(db)
        db.delete_component("comp-a")
        assert db.restore_component("comp-a") is True
        row = db.get_component("comp-a")
        assert row is not None
        assert row["current_version"] == 1
        # Restoring a live component is a no-op
        assert db.restore_component("comp-a") is False

    def test_second_archive_returns_false(self, db):
        _mk(db)
        assert db.delete_component("comp-a") is True
        assert db.delete_component("comp-a") is False

    def test_scoped_restore_requires_ownership(self, db):
        db.create_component_with_config(
            component_id="owned",
            component_type=ComponentType.AGENT,
            name="owned",
            config={"name": "owned"},
            stage="published",
            user_id="alice",
        )
        db.delete_component("owned", user_id="alice")
        assert db.restore_component("owned", user_id="bob") is False
        assert db.restore_component("owned", user_id="alice") is True


# ----------------------------------------------------------------------
# Dependents guard the delete
# ----------------------------------------------------------------------


class TestDependents:
    def _pin(self, db):
        _mk(db, "child")
        db.create_component_with_config(
            component_id="parent",
            component_type=ComponentType.TEAM,
            name="parent",
            config={"name": "parent", "members": [{"type": "agent", "agent_id": "child"}]},
            stage="published",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "child",
                    "child_component_id": "child",
                    "child_version": 1,
                    "position": 0,
                }
            ],
        )

    def test_delete_refuses_while_pinned(self, db):
        self._pin(db)
        with pytest.raises(ComponentDependencyError, match="parent"):
            db.delete_component("child")
        with pytest.raises(ComponentDependencyError, match="parent"):
            db.delete_component("child", hard_delete=True)

    def test_archiving_the_parent_frees_the_soft_delete_only(self, db):
        self._pin(db)
        db.delete_component("parent")
        # Archive of the child now passes: no ACTIVE parent pins it
        assert db.delete_component("child") is True
        db.restore_component("child")
        # Hard delete still refuses: it would break the archived parent's history
        with pytest.raises(ComponentDependencyError):
            db.delete_component("child", hard_delete=True)

    def test_require_no_dependents_false_skips_the_guard(self, db):
        self._pin(db)
        assert db.delete_component("child", require_no_dependents=False) is True

    def test_active_parents_only_filter(self, db):
        self._pin(db)
        assert len(db.get_dependents("child")) == 1
        assert len(db.get_dependents("child", active_parents_only=True)) == 1
        db.delete_component("parent")
        assert len(db.get_dependents("child")) == 1
        assert len(db.get_dependents("child", active_parents_only=True)) == 0


# ----------------------------------------------------------------------
# Compare-and-set guards
# ----------------------------------------------------------------------


class TestGuards:
    def test_append_guard(self, db):
        _mk(db)
        with pytest.raises(ComponentVersionConflictError):
            db.upsert_config("comp-a", config={"name": "v2"}, expected_latest_version=7)
        row = db.upsert_config("comp-a", config={"name": "v2"}, expected_latest_version=1)
        assert row["version"] == 2

    def test_set_current_guard(self, db):
        _mk(db)
        db.upsert_config("comp-a", config={"name": "v2"}, stage="published")
        with pytest.raises(ComponentVersionConflictError):
            db.set_current_version("comp-a", 1, expected_current_version=1)
        assert db.set_current_version("comp-a", 1, expected_current_version=2) is True

    def test_delete_component_guard(self, db):
        _mk(db)
        with pytest.raises(ComponentVersionConflictError):
            db.delete_component("comp-a", expected_current_version=9)
        assert db.delete_component("comp-a", expected_current_version=1) is True


# ----------------------------------------------------------------------
# Tombstones: numbers are never reused
# ----------------------------------------------------------------------


class TestTombstones:
    def _stack(self, db):
        _mk(db)  # v1 published (current)
        db.upsert_config("comp-a", config={"name": "v2"})  # draft
        db.upsert_config("comp-a", config={"name": "v3"})  # draft

    def test_deleted_version_is_buried_not_freed(self, db):
        self._stack(db)
        assert db.delete_config("comp-a", 2) is True
        versions = [c["version"] for c in db.list_configs("comp-a")]
        assert versions == [3, 1]
        all_versions = [c["version"] for c in db.list_configs("comp-a", include_deleted=True)]
        assert all_versions == [3, 2, 1]
        assert db.get_config("comp-a", version=2) is None
        buried = db.get_config("comp-a", version=2, include_deleted=True)
        assert buried is not None and buried["stage"] == DELETED_CONFIG_STAGE
        # The next append continues past the high-water mark
        row = db.upsert_config("comp-a", config={"name": "v4"})
        assert row["version"] == 4

    def test_deleting_the_latest_never_recycles_its_number(self, db):
        self._stack(db)
        db.delete_config("comp-a", 3)
        row = db.upsert_config("comp-a", config={"name": "again"})
        assert row["version"] == 4

    def test_delete_config_guards(self, db):
        self._stack(db)
        with pytest.raises(ComponentDraftRequiredError):
            db.delete_config("comp-a", 1)  # published
        db.upsert_config("comp-a", version=3, stage="published")  # v3 now current
        # The stage guard fires first: the current version is always published.
        with pytest.raises(ComponentDraftRequiredError):
            db.delete_config("comp-a", 3)
        db.delete_config("comp-a", 2)
        assert db.delete_config("comp-a", 2) is False  # already tombstoned

    def test_last_visible_version_is_undeletable(self, db):
        db.create_component_with_config(
            component_id="solo",
            component_type=ComponentType.AGENT,
            name="solo",
            config={"name": "solo"},
            stage="draft",
        )
        with pytest.raises(ComponentLastConfigError):
            db.delete_config("solo", 1)

    def test_pinned_version_is_undeletable(self, db):
        self._stack(db)
        db.create_component_with_config(
            component_id="pinner",
            component_type=ComponentType.TEAM,
            name="pinner",
            config={"name": "pinner"},
            stage="published",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "comp-a",
                    "child_component_id": "comp-a",
                    "child_version": 2,
                    "position": 0,
                }
            ],
        )
        with pytest.raises(ComponentDependencyError):
            db.delete_config("comp-a", 2)

    def test_tombstone_frees_its_label(self, db):
        _mk(db)
        db.upsert_config("comp-a", config={"name": "v2"}, label="stable")
        db.delete_config("comp-a", 2)
        row = db.upsert_config("comp-a", config={"name": "v3"}, label="stable")
        assert row["version"] == 3 and row["label"] == "stable"


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------


class TestReads:
    def test_current_config_never_falls_back_to_a_draft(self, db):
        db.create_component_with_config(
            component_id="draft-only",
            component_type=ComponentType.AGENT,
            name="draft-only",
            config={"name": "draft-only"},
            stage="draft",
        )
        assert db.get_current_config("draft-only") is None
        # The permissive read still falls back for detail surfaces
        assert db.get_config("draft-only") is not None

    def test_latest_config_skips_tombstones(self, db):
        _mk(db)
        db.upsert_config("comp-a", config={"name": "v2"})
        db.delete_config("comp-a", 2)
        latest = db.get_latest_config("comp-a")
        assert latest is not None and latest["version"] == 1

    def test_bulk_latest_configs(self, db):
        _mk(db, "one")
        _mk(db, "two")
        result = db.get_latest_configs({"one", "two", "missing"})
        assert result["one"]["version"] == 1
        assert result["two"]["version"] == 1
        assert result["missing"] is None


# ----------------------------------------------------------------------
# The current pointer never dispatches a tombstone
# ----------------------------------------------------------------------


def _tombstoned_v2(db):
    """comp-a with v1 published (current) and v2 tombstoned."""
    _mk(db)
    db.upsert_config("comp-a", config={"name": "dead"})  # v2 draft
    db.delete_config("comp-a", 2)  # tombstone v2


def _corrupt_pointer(db, component_id: str, version: int) -> None:
    """Point current_version at an arbitrary version via raw SQL.

    set_current_version and upsert_component refuse this state, so the
    corruption these tests exercise can only arrive from outside the API -
    which is exactly what this raw write reproduces.
    """
    table = db._get_table(table_type="components")
    with db.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.component_id == component_id).values(current_version=version))


class TestPointerTombstones:
    def test_get_config_never_serves_a_tombstone_via_the_pointer(self, db):
        _tombstoned_v2(db)
        _corrupt_pointer(db, "comp-a", 2)
        # The pointer read and the current read agree: nothing is served
        assert db.get_config("comp-a") is None
        assert db.get_current_config("comp-a") is None
        # The explicit escape hatch still reaches the tombstone
        buried = db.get_config("comp-a", version=2, include_deleted=True)
        assert buried is not None and buried["stage"] == DELETED_CONFIG_STAGE

    def test_upsert_component_refuses_a_tombstoned_current_version(self, db):
        _tombstoned_v2(db)
        with pytest.raises(ValueError, match="deleted config"):
            db.upsert_component(component_id="comp-a", current_version=2)
        assert db.get_component("comp-a")["current_version"] == 1

    def test_set_current_version_refuses_a_tombstone(self, db):
        _tombstoned_v2(db)
        with pytest.raises(ValueError, match="published"):
            db.set_current_version("comp-a", 2)
        assert db.get_component("comp-a")["current_version"] == 1


# ----------------------------------------------------------------------
# Publish projection
# ----------------------------------------------------------------------


class TestPublishProjection:
    def test_publish_reprojects_identity_onto_the_row(self, db):
        _mk(db)
        db.upsert_config(
            "comp-a",
            config={"name": "Renamed", "description": "fresh", "metadata": {"k": "v"}},
            stage="published",
        )
        row = db.get_component("comp-a")
        assert row["current_version"] == 2
        assert row["name"] == "Renamed"
        assert row["description"] == "fresh"
        assert (row["metadata"] or {}).get("k") == "v"

    def test_publish_flip_projects_the_stored_config(self, db):
        _mk(db)
        db.upsert_config("comp-a", config={"name": "Flipped", "description": "draft first"})
        db.upsert_config("comp-a", version=2, stage="published")
        row = db.get_component("comp-a")
        assert row["current_version"] == 2
        assert row["name"] == "Flipped"


# ----------------------------------------------------------------------
# Cycles
# ----------------------------------------------------------------------


class TestCycles:
    def test_self_link_refused(self, db):
        _mk(db, "selfish")
        with pytest.raises(ComponentCycleError):
            db.upsert_config(
                "selfish",
                config={"name": "selfish"},
                links=[
                    {
                        "link_kind": "member",
                        "link_key": "selfish",
                        "child_component_id": "selfish",
                        "child_version": 1,
                        "position": 0,
                    }
                ],
            )

    def test_two_node_cycle_refused(self, db):
        _mk(db, "a")
        _mk(db, "b")
        db.upsert_config(
            "a",
            config={"name": "a"},
            links=[
                {"link_kind": "member", "link_key": "b", "child_component_id": "b", "child_version": 1, "position": 0}
            ],
        )
        with pytest.raises(ComponentCycleError):
            db.upsert_config(
                "b",
                config={"name": "b"},
                links=[
                    {
                        "link_kind": "member",
                        "link_key": "a",
                        "child_component_id": "a",
                        "child_version": 1,
                        "position": 0,
                    }
                ],
            )

    def test_link_to_archived_child_refused(self, db):
        _mk(db, "gone")
        _mk(db, "keeper")
        db.delete_component("gone")
        with pytest.raises(ComponentArchivedError):
            db.upsert_config(
                "keeper",
                config={"name": "keeper"},
                links=[
                    {
                        "link_kind": "member",
                        "link_key": "gone",
                        "child_component_id": "gone",
                        "child_version": 1,
                        "position": 0,
                    }
                ],
            )

    def test_shared_child_dag_is_not_a_cycle(self, db):
        _mk(db, "shared-child")
        for parent in ("p1", "p2"):
            db.create_component_with_config(
                component_id=parent,
                component_type=ComponentType.TEAM,
                name=parent,
                config={"name": parent},
                stage="published",
                links=[
                    {
                        "link_kind": "member",
                        "link_key": "shared-child",
                        "child_component_id": "shared-child",
                        "child_version": 1,
                        "position": 0,
                    }
                ],
            )
        graph = db.load_component_graph("p1")
        assert graph is not None and not graph.get("cycle_detected")

    def test_graph_loader_stubs_a_legacy_cycle(self, db):
        # A cycle can no longer be written through the API; simulate legacy
        # data by inserting the closing edge directly.
        _mk(db, "y")
        db.create_component_with_config(
            component_id="x",
            component_type=ComponentType.TEAM,
            name="x",
            config={"name": "x"},
            stage="published",
            links=[
                {"link_kind": "member", "link_key": "y", "child_component_id": "y", "child_version": 1, "position": 0}
            ],
        )
        links_table = db._get_table(table_type="component_links")
        with db.Session() as sess, sess.begin():
            sess.execute(
                links_table.insert().values(
                    parent_component_id="y",
                    parent_version=1,
                    link_kind="member",
                    link_key="x",
                    child_component_id="x",
                    child_version=1,
                    position=0,
                    created_at=0,
                )
            )
        graph = db.load_component_graph("x")
        assert graph is not None

        def _has_cycle_stub(node):
            if node is None:
                return False
            if node.get("cycle_detected"):
                return True
            return any(_has_cycle_stub(child.get("graph")) for child in node.get("children", []))

        assert _has_cycle_stub(graph)


class TestConcurrentCASWrites:
    """The compare-and-set guards must ride the write itself: with a
    check-then-write shape, two writers expecting the same state both pass
    the check and both win. Each race here asserts exactly one winner and
    exactly one ComponentVersionConflictError."""

    def _race(self, fn_a, fn_b):
        import threading

        barrier = threading.Barrier(2)
        results: list = [None, None]

        def run(slot, fn):
            barrier.wait()
            try:
                results[slot] = ("ok", fn())
            except Exception as e:
                results[slot] = ("err", e)

        threads = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate((fn_a, fn_b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def _component_with_versions(self, db, cid="race-comp", publish_two=True):
        from agno.db.base import ComponentType

        db.create_component_with_config(
            component_id=cid,
            component_type=ComponentType.AGENT,
            name=cid,
            config={"name": cid, "instructions": "v1"},
            stage="published",
        )
        db.upsert_config(component_id=cid, config={"name": cid, "instructions": "v2"}, stage="draft")
        if publish_two:
            db.upsert_config(component_id=cid, version=2, stage="published")
        return cid

    def test_set_current_version_race_has_one_winner(self, db):
        from agno.db.base import ComponentVersionConflictError

        cid = self._component_with_versions(db)  # current is now 2
        results = self._race(
            lambda: db.set_current_version(cid, 1, expected_current_version=2),
            lambda: db.set_current_version(cid, 1, expected_current_version=2),
        )
        outcomes = sorted(r[0] for r in results)
        assert outcomes == ["err", "ok"], results
        errs = [r[1] for r in results if r[0] == "err"]
        assert isinstance(errs[0], ComponentVersionConflictError)

    def test_archive_race_has_one_winner(self, db):
        from agno.db.base import ComponentVersionConflictError

        cid = self._component_with_versions(db)
        results = self._race(
            lambda: db.set_current_version(cid, 1, expected_current_version=2),
            lambda: db.delete_component(cid, hard_delete=False, expected_current_version=2),
        )
        outcomes = sorted(r[0] for r in results)
        assert outcomes == ["err", "ok"], results
        errs = [r[1] for r in results if r[0] == "err"]
        assert isinstance(errs[0], ComponentVersionConflictError)

    def test_guarded_publish_race_has_one_winner(self, db):
        from agno.db.base import ComponentVersionConflictError

        cid = self._component_with_versions(db, publish_two=False)  # current 1, draft 2
        db.upsert_config(component_id=cid, config={"name": cid, "instructions": "v3"}, stage="draft")
        results = self._race(
            lambda: db.upsert_config(component_id=cid, version=2, stage="published", expected_current_version=1),
            lambda: db.upsert_config(component_id=cid, version=3, stage="published", expected_current_version=1),
        )
        outcomes = sorted(r[0] for r in results)
        assert outcomes == ["err", "ok"], results
        errs = [r[1] for r in results if r[0] == "err"]
        assert isinstance(errs[0], ComponentVersionConflictError)


class TestRestorePinnedChildren:
    def _team_with_member(self, db):
        from agno.db.base import ComponentType

        db.create_component_with_config(
            component_id="pin-child",
            component_type=ComponentType.AGENT,
            name="pin-child",
            config={"name": "pin-child"},
            stage="published",
        )
        db.create_component_with_config(
            component_id="pin-parent",
            component_type=ComponentType.TEAM,
            name="pin-parent",
            config={"name": "pin-parent"},
            stage="published",
            links=[
                {
                    "link_kind": "member",
                    "link_key": "pin-child",
                    "child_component_id": "pin-child",
                    "child_version": 1,
                    "position": 0,
                }
            ],
        )

    def test_restore_refuses_while_pinned_child_archived(self, db):
        from agno.db.base import ComponentDependencyError

        self._team_with_member(db)
        db.delete_component("pin-parent", hard_delete=False)
        db.delete_component("pin-child", hard_delete=False)
        with pytest.raises(ComponentDependencyError, match="pin-child"):
            db.restore_component("pin-parent")
        # Children first, then the parent.
        assert db.restore_component("pin-child") is True
        assert db.restore_component("pin-parent") is True

    def test_restore_of_leaf_components_is_unaffected(self, db):
        self._team_with_member(db)
        db.delete_component("pin-parent", hard_delete=False)
        assert db.restore_component("pin-parent") is True
