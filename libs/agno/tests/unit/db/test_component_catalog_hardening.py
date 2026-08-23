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

    def test_zero_expects_no_live_version_on_first_publish(self, db):
        """A never-published component has a NULL live pointer, which no
        integer equals; 0 spells "I expect nothing to be live" so a guarded
        first publish is satisfiable - and refused once something is."""
        _mk(db, stage="draft")
        assert db.get_component("comp-a")["current_version"] is None
        with pytest.raises(ComponentVersionConflictError):
            db.upsert_config("comp-a", version=1, stage="published", expected_current_version=1)
        assert db.get_component("comp-a")["current_version"] is None
        row = db.upsert_config("comp-a", version=1, stage="published", expected_current_version=0)
        assert row["stage"] == "published"
        assert db.get_component("comp-a")["current_version"] == 1
        # Now something is live: the same guard is a genuine conflict.
        db.upsert_config("comp-a", config={"name": "v2"}, stage="draft")
        with pytest.raises(ComponentVersionConflictError):
            db.upsert_config("comp-a", version=2, stage="published", expected_current_version=0)
        assert db.get_component("comp-a")["current_version"] == 1

    def test_zero_expects_no_live_version_on_delete(self, db):
        _mk(db, stage="draft")
        with pytest.raises(ComponentVersionConflictError):
            db.delete_component("comp-a", expected_current_version=1)
        assert db.get_component("comp-a") is not None
        assert db.delete_component("comp-a", expected_current_version=0) is True
        assert db.get_component("comp-a") is None

    def test_zero_conflicts_with_a_live_version_on_delete(self, db):
        _mk(db)  # published: current is 1
        with pytest.raises(ComponentVersionConflictError):
            db.delete_component("comp-a", expected_current_version=0)
        assert db.get_component("comp-a") is not None


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
        # A DRAFT parent may pin a draft child (only PUBLISHED parents require
        # published children); deleting the pinned draft is still refused.
        db.create_component_with_config(
            component_id="pinner",
            component_type=ComponentType.TEAM,
            name="pinner",
            config={"name": "pinner"},
            stage="draft",
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


class TestPublishProjectionOwnership:
    """The projection writes only the fields the published config owns.

    description and metadata are also first-class row columns, set through
    the component routes and present in no config version, so publishing a
    config that does not carry them must leave the columns alone. A scoped
    actor's provenance stamp rides in every config's metadata, so stamp-only
    metadata does not count as carried unless the version says so with the
    metadata_authored marker.
    """

    STAMP = {"studio": {"last_actor": "builder-1", "last_action": "edit"}}

    def _operator_row(self, db):
        _mk(db)
        db.upsert_component(
            component_id="comp-a",
            component_type=ComponentType.AGENT,
            name="comp-a",
            description="operator note",
            metadata={"team": "ops"},
        )

    def test_a_config_without_the_fields_leaves_the_row_alone(self, db):
        self._operator_row(db)
        db.upsert_config("comp-a", config={"name": "comp-a", "instructions": "v2"}, stage="published")
        row = db.get_component("comp-a")
        assert row["description"] == "operator note"
        assert row["metadata"] == {"team": "ops"}

    def test_stamp_only_metadata_leaves_the_row_alone(self, db):
        self._operator_row(db)
        db.upsert_config("comp-a", config={"name": "comp-a", "metadata": dict(self.STAMP)}, stage="published")
        assert db.get_component("comp-a")["metadata"] == {"team": "ops"}

    def test_the_authored_marker_makes_stamp_only_metadata_win(self, db):
        self._operator_row(db)
        db.upsert_config(
            "comp-a",
            config={"name": "comp-a", "metadata": dict(self.STAMP), "metadata_authored": True},
            stage="published",
        )
        assert db.get_component("comp-a")["metadata"] == self.STAMP

    def test_an_explicit_empty_description_still_clears(self, db):
        self._operator_row(db)
        db.upsert_config("comp-a", config={"name": "comp-a", "description": ""}, stage="published")
        assert not db.get_component("comp-a")["description"]

    def test_an_explicit_empty_metadata_still_clears(self, db):
        self._operator_row(db)
        db.upsert_config("comp-a", config={"name": "comp-a", "metadata": {}}, stage="published")
        assert not db.get_component("comp-a")["metadata"]

    def test_a_publish_flip_of_a_bare_draft_leaves_the_row_alone(self, db):
        self._operator_row(db)
        db.upsert_config("comp-a", config={"name": "comp-a", "instructions": "v2"})
        db.upsert_config("comp-a", version=2, stage="published")
        row = db.get_component("comp-a")
        assert row["description"] == "operator note"
        assert row["metadata"] == {"team": "ops"}


class TestPublishProjectionOfNonMappingMetadata:
    """Probing an arbitrary metadata value for keys must not turn a write into
    an error, and a value that cannot be stored must not reach the column.

    The stamp-only test asks metadata for its keys, which only a mapping has.
    Anything else cannot be a row's metadata either, so the projection skips
    it: the publish goes through as it did before this projection existed, the
    config keeps what the caller sent, and the column is left alone the way it
    is for every other key the projection does not own.
    """

    def _operator_row(self, db):
        _mk(db)
        db.upsert_component(
            component_id="comp-a",
            component_type=ComponentType.AGENT,
            name="comp-a",
            metadata={"team": "ops"},
        )

    @pytest.mark.parametrize("metadata", [5, "hello", ["a", "b"], ["studio"], 0.5, True])
    def test_a_non_mapping_metadata_publishes_and_leaves_the_row_column_alone(self, db, metadata):
        self._operator_row(db)
        config = db.upsert_config("comp-a", config={"name": "comp-a", "metadata": metadata}, stage="published")
        assert config["config"]["metadata"] == metadata
        assert db.get_component("comp-a")["metadata"] == {"team": "ops"}


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

        # Either order is legitimate, and which one runs is a scheduling
        # detail, so the invariant is that exactly one MUTATION lands - not
        # that a particular call raised.
        #
        # Pointer move first: the archive's CAS sees current_version moved and
        # raises. Archive first: the pointer move finds an archived row and
        # reports False, the same verdict its pre-check gives for a row that
        # was already archived (pinned in test_component_archive_race.py).
        landed = [r for r in results if r[0] == "ok" and r[1] is not False]
        assert len(landed) == 1, results

        archived = db.get_component(cid, include_deleted=True)["deleted_at"] is not None
        if archived:
            # The archive won, so the pointer must not have moved onto it.
            assert db.get_component(cid, include_deleted=True)["current_version"] == 2
            assert any(r[0] == "ok" and r[1] is False for r in results), results
        else:
            # The pointer move won, so the archive must have reported the conflict.
            errs = [r[1] for r in results if r[0] == "err"]
            assert errs and isinstance(errs[0], ComponentVersionConflictError), results
            assert db.get_component(cid)["current_version"] == 1

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

    def test_guarded_first_publish_race_has_one_winner(self, db):
        """Two first publishers both expecting no live version (0): the guard
        rides the UPDATE as IS NULL, so exactly one lands."""
        from agno.db.base import ComponentType, ComponentVersionConflictError

        cid = "first-publish-race"
        db.create_component_with_config(
            component_id=cid,
            component_type=ComponentType.AGENT,
            name=cid,
            config={"name": cid, "instructions": "v1"},
            stage="draft",
        )
        db.upsert_config(component_id=cid, config={"name": cid, "instructions": "v2"}, stage="draft")
        assert db.get_component(cid)["current_version"] is None
        results = self._race(
            lambda: db.upsert_config(component_id=cid, version=1, stage="published", expected_current_version=0),
            lambda: db.upsert_config(component_id=cid, version=2, stage="published", expected_current_version=0),
        )
        outcomes = sorted(r[0] for r in results)
        assert outcomes == ["err", "ok"], results
        errs = [r[1] for r in results if r[0] == "err"]
        assert isinstance(errs[0], ComponentVersionConflictError)
        winner = [r[1] for r in results if r[0] == "ok"][0]["version"]
        assert db.get_component(cid)["current_version"] == winner


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


class TestHardDeleteSucceeds:
    """A populated component (configs + links, FK-constrained on Postgres)
    hard-deletes in one call; the CAS conflict path still refuses. The FK
    order regression made every populated hard delete raise on Postgres while
    the suite only exercised the refusal path."""

    def _populated(self, db, cid="hd-comp"):
        from agno.db.base import ComponentType

        db.create_component_with_config(
            component_id=f"{cid}-child",
            component_type=ComponentType.AGENT,
            name=f"{cid}-child",
            config={"name": f"{cid}-child"},
            stage="published",
        )
        db.create_component_with_config(
            component_id=cid,
            component_type=ComponentType.TEAM,
            name=cid,
            config={"name": cid},
            stage="published",
            links=[
                {
                    "link_kind": "member",
                    "link_key": f"{cid}-child",
                    "child_component_id": f"{cid}-child",
                    "child_version": 1,
                    "position": 0,
                }
            ],
        )
        return cid

    def test_populated_hard_delete_succeeds(self, db):
        cid = self._populated(db)
        assert db.delete_component(cid, hard_delete=True, require_no_dependents=False) is True
        assert db.get_component(cid, include_deleted=True) is None
        assert db.get_config(component_id=cid, version=1) is None

    def test_guarded_hard_delete_conflicts_on_stale_pointer(self, db):
        from agno.db.base import ComponentVersionConflictError

        cid = self._populated(db, cid="hd-guarded")
        with pytest.raises(ComponentVersionConflictError):
            db.delete_component(cid, hard_delete=True, expected_current_version=99, require_no_dependents=False)
        assert db.get_component(cid) is not None
        assert db.get_config(component_id=cid, version=1) is not None

    def test_guarded_hard_delete_succeeds_with_matching_pointer(self, db):
        cid = self._populated(db, cid="hd-match")
        assert (
            db.delete_component(cid, hard_delete=True, expected_current_version=1, require_no_dependents=False) is True
        )


class TestWorkflowPinGuards:
    """The pin guards must cover the kinds Step.get_links actually emits
    (step_agent/step_team/step_workflow) - a guard written against a bare
    "step" kind held for teams and silently skipped every workflow."""

    def _wf_with_step_child(self, db, kind="step_agent", cid="wfp"):
        from agno.db.base import ComponentType

        child_type = {"step_agent": ComponentType.AGENT, "step_team": ComponentType.TEAM}.get(
            kind, ComponentType.WORKFLOW
        )
        db.create_component_with_config(
            component_id=f"{cid}-child",
            component_type=child_type,
            name=f"{cid}-child",
            config={"name": f"{cid}-child"},
            stage="draft",
        )
        db.create_component_with_config(
            component_id=cid,
            component_type=ComponentType.WORKFLOW,
            name=cid,
            config={"name": cid, "steps": []},
            stage="draft",
            links=[
                {
                    "link_kind": kind,
                    "link_key": f"{cid}-child",
                    "child_component_id": f"{cid}-child",
                    "child_version": 1,
                    "position": 0,
                }
            ],
        )
        return cid

    @pytest.mark.parametrize("kind", ["step_agent", "step_team", "step_workflow"])
    def test_publish_refuses_draft_step_child_for_every_kind(self, db, kind):
        from agno.db.base import ComponentDependencyError

        cid = self._wf_with_step_child(db, kind=kind, cid=f"wfp-{kind}")
        with pytest.raises(ComponentDependencyError, match=f"wfp-{kind}-child"):
            db.upsert_config(component_id=cid, version=1, stage="published")

    def test_publish_passes_once_step_child_published(self, db):
        cid = self._wf_with_step_child(db, cid="wfp-ok")
        db.upsert_config(component_id=f"{cid}-child", version=1, stage="published")
        result = db.upsert_config(component_id=cid, version=1, stage="published")
        assert result["stage"] == "published"

    def test_restore_refuses_archived_step_child(self, db):
        from agno.db.base import ComponentDependencyError

        cid = self._wf_with_step_child(db, cid="wfr")
        db.upsert_config(component_id=f"{cid}-child", version=1, stage="published")
        db.upsert_config(component_id=cid, version=1, stage="published")
        db.delete_component(cid, hard_delete=False)
        db.delete_component(f"{cid}-child", hard_delete=False)
        with pytest.raises(ComponentDependencyError, match=f"{cid}-child"):
            db.restore_component(cid)
        assert db.restore_component(f"{cid}-child") is True
        assert db.restore_component(cid) is True


class TestDeterministicCASInterleaving:
    """Deterministic (non-probabilistic) proof that each guard rides the write:
    a competing write commits BETWEEN a caller's read and its guarded op, so
    the guarded op sees a stale expected value and MUST conflict. A
    check-then-write mutation (guard on a pre-read, not the write) passes the
    happy path but fails here every time - no flake."""

    def _comp(self, db, cid="cas", versions=2):
        from agno.db.base import ComponentType

        db.create_component_with_config(
            component_id=cid,
            component_type=ComponentType.AGENT,
            name=cid,
            config={"name": cid, "v": 1},
            stage="published",
        )
        for i in range(2, versions + 1):
            db.upsert_config(cid, config={"name": cid, "v": i}, stage="draft")
            db.upsert_config(cid, version=i, stage="published")
        return cid

    def test_set_current_conflicts_after_a_competing_move(self, db):
        from agno.db.base import ComponentVersionConflictError

        cid = self._comp(db, versions=3)  # current = 3
        # Reader A intends expected_current_version=3. A competing writer moves
        # the pointer to 1 first; A's guarded op must now conflict.
        assert db.set_current_version(cid, 2, expected_current_version=3) is True  # competitor -> current 2
        with pytest.raises(ComponentVersionConflictError):
            db.set_current_version(cid, 1, expected_current_version=3)
        assert db.get_component(cid)["current_version"] == 2

    def test_guarded_append_conflicts_after_a_competing_append(self, db):
        from agno.db.base import ComponentVersionConflictError

        cid = self._comp(db, versions=2)  # latest visible = 2
        db.upsert_config(cid, config={"name": cid, "v": 3}, stage="draft", expected_latest_version=2)  # competitor -> 3
        with pytest.raises(ComponentVersionConflictError):
            db.upsert_config(cid, config={"name": cid, "v": 99}, stage="draft", expected_latest_version=2)

    def test_archive_conflicts_after_a_competing_pointer_move(self, db):
        from agno.db.base import ComponentVersionConflictError

        cid = self._comp(db, versions=3)  # current = 3
        db.set_current_version(cid, 2, expected_current_version=3)  # competitor -> current 2
        with pytest.raises(ComponentVersionConflictError):
            db.delete_component(cid, hard_delete=False, expected_current_version=3)
        assert db.get_component(cid) is not None  # not archived


class TestArchiveFreezesTheWholeHistory:
    """Archive reserves the id and keeps every version so restore can bring
    them back. A writer that skips the archived check breaks that promise
    quietly: the version is gone, and restore cannot tell.
    """

    def _archived_with_draft(self, db, component_id="frozen"):
        _mk(db, component_id, stage="published")
        draft = db.upsert_config(component_id, config={"name": component_id, "instructions": "v2"})
        db.delete_component(component_id)
        return draft["version"]

    def test_delete_config_refuses_a_draft_of_an_archived_component(self, db):
        draft_version = self._archived_with_draft(db)
        with pytest.raises(ComponentArchivedError):
            db.delete_config("frozen", version=draft_version)

    def test_the_draft_survives_the_refusal(self, db):
        draft_version = self._archived_with_draft(db)
        with pytest.raises(ComponentArchivedError):
            db.delete_config("frozen", version=draft_version)
        db.restore_component("frozen")
        stages = {c["version"]: c["stage"] for c in db.list_configs("frozen", include_config=False)}
        assert stages[draft_version] == "draft"

    def test_every_other_writer_refuses_the_same_way(self, db):
        """The guard delete_config was missing is the one its siblings have."""
        self._archived_with_draft(db)
        with pytest.raises(ComponentArchivedError):
            db.upsert_config("frozen", config={"name": "frozen"})
        with pytest.raises(ComponentArchivedError):
            db.upsert_component(component_id="frozen", component_type=ComponentType.AGENT, name="frozen")

    def test_a_live_component_still_deletes_its_draft(self, db):
        _mk(db, "live", stage="published")
        draft = db.upsert_config("live", config={"name": "live", "instructions": "v2"})
        assert db.delete_config("live", version=draft["version"]) is True

    def test_the_owner_scope_still_answers_first(self, db):
        """A foreign caller must not learn that the row is archived."""
        db.create_component_with_config(
            component_id="alice-frozen",
            component_type=ComponentType.AGENT,
            name="alice-frozen",
            config={"name": "alice-frozen"},
            stage="published",
            user_id="alice",
        )
        draft = db.upsert_config("alice-frozen", config={"name": "alice-frozen", "instructions": "v2"})
        db.delete_component("alice-frozen", user_id="alice")
        assert db.delete_config("alice-frozen", version=draft["version"], user_id="bob") is False


class TestThePointerMeansPublished:
    """``current_version`` is what the platform runs, and the catalog's
    visibility predicate reads "has a current version" as published -- so a
    pointer at an unpublished version does not merely serve the wrong config,
    it puts a private component on the platform.

    set_current_version has always enforced this. upsert_component takes the
    same column and checked only for a tombstone, so it was the way around it.
    """

    def test_a_draft_version_cannot_become_current(self, db):
        _mk(db, "ptr", stage="draft")
        with pytest.raises(ValueError, match="draft"):
            db.upsert_component(component_id="ptr", component_type=ComponentType.AGENT, name="ptr", current_version=1)
        assert db.get_component("ptr")["current_version"] is None

    def test_a_missing_version_cannot_become_current(self, db):
        _mk(db, "ptr2", stage="published")
        with pytest.raises(ValueError, match="missing"):
            db.upsert_component(
                component_id="ptr2", component_type=ComponentType.AGENT, name="ptr2", current_version=99
            )

    def test_a_published_version_still_can(self, db):
        _mk(db, "ptr3", stage="published")
        db.upsert_config("ptr3", config={"name": "ptr3", "v": 2}, stage="published")
        db.upsert_component(component_id="ptr3", component_type=ComponentType.AGENT, name="ptr3", current_version=2)
        assert db.get_component("ptr3")["current_version"] == 2

    def test_the_draft_component_stays_invisible_to_others(self, db):
        """The reason the invariant matters under share-on-publish."""
        db.create_component_with_config(
            component_id="ptr4",
            component_type=ComponentType.AGENT,
            name="ptr4",
            config={"name": "ptr4"},
            stage="draft",
            user_id="alice",
        )
        with pytest.raises(ValueError):
            db.upsert_component(
                component_id="ptr4",
                component_type=ComponentType.AGENT,
                name="ptr4",
                current_version=1,
                user_id="alice",
            )
        assert db.get_component("ptr4", user_id="bob") is None
