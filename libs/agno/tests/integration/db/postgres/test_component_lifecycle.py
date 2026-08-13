"""PostgreSQL integration tests for guarded component lifecycle operations."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any, Dict, List, Optional, cast

import pytest
from sqlalchemy import event

from agno.db.base import (
    DELETED_CONFIG_STAGE,
    ComponentAlreadyExistsError,
    ComponentCycleError,
    ComponentDependencyError,
    ComponentDependencyUnavailableError,
    ComponentDraftRequiredError,
    ComponentProjection,
    ComponentType,
    ComponentVersionConflictError,
    ComponentVersionGuard,
)
from agno.db.postgres.postgres import PostgresDb


def _guard(latest_version: Optional[int], current_version: Optional[int]) -> ComponentVersionGuard:
    return ComponentVersionGuard(latest_version=latest_version, current_version=current_version)


def _component_link(child_id: str, *, link_key: str = "step_0") -> Dict[str, Any]:
    return {
        "link_kind": "step_agent",
        "link_key": link_key,
        "child_component_id": child_id,
        "child_version": 1,
        "position": 0,
    }


def _insert_raw_component_link(db: PostgresDb, parent_id: str, child_id: str, *, link_key: str) -> None:
    links_table = db._get_table(table_type="component_links", create_table_if_not_found=True)
    assert links_table is not None
    with db.Session() as session, session.begin():
        session.execute(
            links_table.insert().values(
                parent_component_id=parent_id,
                parent_version=1,
                link_kind="step_agent",
                link_key=link_key,
                child_component_id=child_id,
                child_version=1,
                position=0,
            )
        )


def test_postgres_load_component_graph_bounds_malformed_cycle(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "graph-cycle-a")
    _create_component(postgres_db_real, "graph-cycle-b")
    _insert_raw_component_link(postgres_db_real, "graph-cycle-a", "graph-cycle-b", link_key="to-b")
    _insert_raw_component_link(postgres_db_real, "graph-cycle-b", "graph-cycle-a", link_key="to-a")

    graph = postgres_db_real.load_component_graph("graph-cycle-a")

    assert graph is not None
    cycle = graph["children"][0]["graph"]["children"][0]["graph"]
    assert cycle["component"]["component_id"] == "graph-cycle-a"
    assert cycle["cycle_detected"] is True
    assert cycle["children"] == []


def test_postgres_load_component_graph_expands_shared_child_in_each_dag_branch(
    postgres_db_real: PostgresDb,
) -> None:
    _create_component(postgres_db_real, "graph-shared")
    _create_component(postgres_db_real, "graph-left", links=[_component_link("graph-shared")])
    _create_component(postgres_db_real, "graph-right", links=[_component_link("graph-shared")])
    _create_component(
        postgres_db_real,
        "graph-root",
        links=[
            _component_link("graph-left", link_key="left"),
            _component_link("graph-right", link_key="right"),
        ],
    )

    graph = postgres_db_real.load_component_graph("graph-root")

    assert graph is not None
    shared_graphs = [branch["graph"]["children"][0]["graph"] for branch in graph["children"]]
    assert [item["component"]["component_id"] for item in shared_graphs] == ["graph-shared", "graph-shared"]
    assert all("cycle_detected" not in item for item in shared_graphs)


def _create_component(
    db: PostgresDb,
    component_id: str,
    *,
    component_type: ComponentType = ComponentType.AGENT,
    stage: str = "published",
    name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    links: Optional[List[Dict[str, Any]]] = None,
) -> None:
    db.create_component_with_config(
        component_id=component_id,
        component_type=component_type,
        name=name or component_id,
        config=config or {"name": name or component_id},
        stage=stage,
        links=links,
    )


def test_postgres_generic_read_falls_back_to_latest_draft_and_guarded_append_conflicts(
    postgres_db_real: PostgresDb,
) -> None:
    _create_component(postgres_db_real, "draft-only-agent", stage="draft")
    assert postgres_db_real.get_current_config("draft-only-agent") is None
    draft = postgres_db_real.get_config("draft-only-agent")
    assert draft is not None
    assert draft["version"] == 1
    assert postgres_db_real.get_latest_config("draft-only-agent") == draft

    _create_component(postgres_db_real, "guarded-agent", config={"instructions": "published"})
    created = postgres_db_real.upsert_config(
        "guarded-agent",
        config={"instructions": "writer one"},
        stage="draft",
        guard=_guard(1, 1),
    )
    assert created["version"] == 2

    with pytest.raises(ComponentVersionConflictError):
        postgres_db_real.upsert_config(
            "guarded-agent",
            config={"instructions": "stale writer"},
            stage="draft",
            guard=_guard(1, 1),
        )


def test_postgres_bulk_component_reads_are_complete_bounded_and_single_query(
    postgres_db_real: PostgresDb,
) -> None:
    _create_component(postgres_db_real, "bulk-active", name="Published", config={"name": "Published"})
    postgres_db_real.upsert_config(
        "bulk-active",
        config={"name": "Draft"},
        stage="draft",
        guard=_guard(1, 1),
    )
    _create_component(
        postgres_db_real,
        "bulk-team",
        component_type=ComponentType.TEAM,
    )
    _create_component(postgres_db_real, "bulk-archived")
    assert postgres_db_real.delete_component("bulk-archived")

    statements: List[str] = []

    def record_statement(_conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: bool):
        statements.append(statement)

    event.listen(postgres_db_real.db_engine, "before_cursor_execute", record_statement)
    try:
        rows = postgres_db_real.get_components(
            {"bulk-active", "bulk-team", "bulk-archived", "bulk-missing"},
            include_deleted=True,
        )
    finally:
        event.remove(postgres_db_real.db_engine, "before_cursor_execute", record_statement)

    assert [row["component_id"] for row in rows] == ["bulk-active", "bulk-archived", "bulk-team"]
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
    assert [
        row["component_id"]
        for row in postgres_db_real.get_components(
            {"bulk-active", "bulk-team", "bulk-archived"},
            component_type=ComponentType.AGENT,
        )
    ] == ["bulk-active"]
    assert postgres_db_real.get_components(set()) == []

    statements.clear()
    event.listen(postgres_db_real.db_engine, "before_cursor_execute", record_statement)
    try:
        latest = postgres_db_real.get_latest_configs(
            {"bulk-active", "bulk-archived", "bulk-missing"},
        )
    finally:
        event.remove(postgres_db_real.db_engine, "before_cursor_execute", record_statement)

    assert set(latest) == {"bulk-active", "bulk-archived", "bulk-missing"}
    assert latest["bulk-active"] is not None
    assert latest["bulk-active"]["version"] == 2
    assert latest["bulk-active"]["stage"] == "draft"
    assert latest["bulk-archived"] is None
    assert latest["bulk-missing"] is None
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")

    archived_latest = postgres_db_real.get_latest_configs({"bulk-archived"}, include_deleted=True)
    assert archived_latest["bulk-archived"] is not None
    assert archived_latest["bulk-archived"]["version"] == 1
    assert postgres_db_real.get_latest_configs(set()) == {}


def test_postgres_draft_projection_tracks_latest_only_until_first_publish(postgres_db_real: PostgresDb) -> None:
    _create_component(
        postgres_db_real,
        "draft-projection",
        stage="draft",
        name="Draft one",
        config={"name": "Draft one"},
    )

    postgres_db_real.upsert_config(
        "draft-projection",
        config={"name": "Draft two"},
        stage="draft",
        projection={"name": "Draft two"},
    )
    component = postgres_db_real.get_component("draft-projection")
    assert component is not None
    assert component["current_version"] is None
    assert component["name"] == "Draft two"

    postgres_db_real.upsert_config(
        "draft-projection",
        config={"name": "Published"},
        stage="published",
        projection={"name": "Published"},
    )
    latest_draft = postgres_db_real.upsert_config(
        "draft-projection",
        config={"name": "Must not leak"},
        stage="draft",
        projection={"name": "Must not leak"},
    )

    component = postgres_db_real.get_component("draft-projection")
    assert component is not None
    assert component["current_version"] == 3
    assert component["name"] == "Published"
    assert latest_draft["version"] == 4
    assert postgres_db_real.get_latest_config("draft-projection") == latest_draft
    assert postgres_db_real.get_current_config("draft-projection")["version"] == 3  # type: ignore[index]


def test_postgres_only_draft_cannot_be_deleted_into_a_zombie(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "sole-draft", stage="draft")

    with pytest.raises(ValueError, match="last config.*archive"):
        postgres_db_real.delete_config("sole-draft", 1, guard=_guard(1, None))

    assert [row["version"] for row in postgres_db_real.list_configs("sole-draft")] == [1]
    assert postgres_db_real.get_config("sole-draft", version=1) is not None
    assert postgres_db_real.delete_component("sole-draft", guard=_guard(1, None)) is True


def test_postgres_generic_update_cannot_move_current_pointer(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "pointer-agent", name="Version one")
    postgres_db_real.upsert_config(
        "pointer-agent",
        config={"name": "Version two"},
        stage="published",
        projection={"name": "Version two"},
    )

    with pytest.raises(ValueError, match="set_current_version"):
        postgres_db_real.upsert_component("pointer-agent", current_version=1)

    component = postgres_db_real.get_component("pointer-agent")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Version two"


def test_postgres_mutation_results_are_captured_before_commit(
    postgres_db_real: PostgresDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_public_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("mutation must not perform a post-commit public read")

    monkeypatch.setattr(postgres_db_real, "get_component", fail_public_read)
    monkeypatch.setattr(postgres_db_real, "get_config", fail_public_read)

    component, initial = postgres_db_real.create_component_with_config(
        component_id="atomic-response",
        component_type=ComponentType.AGENT,
        name="Initial",
        config={"name": "Initial"},
        stage="published",
    )
    updated = postgres_db_real.upsert_component("atomic-response", name="Updated")
    draft = postgres_db_real.upsert_config(
        "atomic-response",
        config={"name": "Draft"},
        stage="draft",
        guard=_guard(1, 1),
    )

    assert component["component_id"] == "atomic-response"
    assert initial["version"] == 1
    assert updated["name"] == "Updated"
    assert draft["version"] == 2
    assert draft["stage"] == "draft"


def test_postgres_publish_and_rollback_update_pointer_and_projection(postgres_db_real: PostgresDb) -> None:
    _create_component(
        postgres_db_real,
        "release-agent",
        name="Version one",
        config={"instructions": "v1"},
    )
    draft = postgres_db_real.upsert_config(
        "release-agent",
        config={"instructions": "v2"},
        stage="draft",
        guard=_guard(1, 1),
    )
    published = postgres_db_real.upsert_config(
        "release-agent",
        version=draft["version"],
        stage="published",
        guard=_guard(2, 1),
        projection={"name": "Version two", "metadata": {"release": 2}},
    )
    assert published["stage"] == "published"

    component = postgres_db_real.get_component("release-agent")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Version two"
    assert component["metadata"] == {"release": 2}

    assert postgres_db_real.set_current_version(
        "release-agent",
        1,
        guard=_guard(2, 2),
        projection={"name": "Version one", "metadata": {"release": 1}},
    )
    component = postgres_db_real.get_component("release-agent")
    assert component is not None
    assert component["current_version"] == 1
    assert component["name"] == "Version one"

    with pytest.raises(ComponentDraftRequiredError, match="only draft configs") as exc:
        postgres_db_real.delete_config("release-agent", 2, guard=_guard(2, 1))

    assert exc.value.component_id == "release-agent"
    assert exc.value.version == 2


def test_postgres_existing_draft_is_immutable_and_publish_derives_projection(postgres_db_real: PostgresDb) -> None:
    postgres_db_real.create_component_with_config(
        component_id="immutable-draft",
        component_type=ComponentType.AGENT,
        name="Catalog placeholder",
        config={
            "name": "Locked draft",
            "description": "Derived from the stored payload",
            "metadata": {"release": 1},
            "instructions": "original",
        },
        description="Catalog placeholder",
        metadata={"release": 0},
        stage="draft",
    )

    with pytest.raises(ValueError, match="requires a component version guard"):
        postgres_db_real.upsert_config(
            "immutable-draft",
            version=1,
            config={"name": "mutated"},
            stage="draft",
        )
    with pytest.raises(ValueError, match="cannot mutate config"):
        postgres_db_real.upsert_config(
            "immutable-draft",
            version=1,
            config={"name": "mutated"},
            stage="published",
            guard=_guard(1, None),
        )

    published = postgres_db_real.upsert_config(
        "immutable-draft",
        version=1,
        stage="published",
        guard=_guard(1, None),
    )
    component = postgres_db_real.get_component("immutable-draft")

    assert published["config"]["instructions"] == "original"
    assert component is not None
    assert component["current_version"] == 1
    assert component["name"] == "Locked draft"
    assert component["description"] == "Derived from the stored payload"
    assert component["metadata"] == {"release": 1}


def test_postgres_publish_and_set_current_derive_projection_from_target_config(
    postgres_db_real: PostgresDb,
) -> None:
    postgres_db_real.create_component_with_config(
        component_id="derived-pointer",
        component_type=ComponentType.AGENT,
        name="Version one",
        config={"name": "Version one", "description": "First", "metadata": {"release": 1}},
        description="First",
        metadata={"release": 1},
        stage="published",
    )

    postgres_db_real.upsert_config(
        "derived-pointer",
        config={"name": "Version two", "description": "Second", "metadata": {"release": 2}},
        stage="published",
    )
    component = postgres_db_real.get_component("derived-pointer")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Version two"
    assert component["description"] == "Second"
    assert component["metadata"] == {"release": 2}

    assert postgres_db_real.set_current_version("derived-pointer", 1, guard=_guard(2, 2))
    component = postgres_db_real.get_component("derived-pointer")
    assert component is not None
    assert component["current_version"] == 1
    assert component["name"] == "Version one"
    assert component["description"] == "First"
    assert component["metadata"] == {"release": 1}


def test_postgres_draft_delete_and_projection_are_one_transaction(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "audited-delete", config={"instructions": "v1"})
    postgres_db_real.upsert_config(
        "audited-delete",
        config={"instructions": "discard me"},
        stage="draft",
        guard=_guard(1, 1),
    )

    invalid_projection = cast(ComponentProjection, {"unknown_field": "must fail"})
    with pytest.raises(ValueError, match="projection"):
        postgres_db_real.delete_config(
            "audited-delete",
            2,
            guard=_guard(2, 1),
            projection=invalid_projection,
        )

    assert postgres_db_real.get_config("audited-delete", version=2) is not None
    assert postgres_db_real.delete_config(
        "audited-delete",
        2,
        guard=_guard(2, 1),
        projection={"metadata": {"last_action": "delete_version"}},
    )
    component = postgres_db_real.get_component("audited-delete")
    assert component is not None
    assert component["metadata"] == {"last_action": "delete_version"}
    assert postgres_db_real.get_config("audited-delete", version=2) is None


def test_postgres_deleted_draft_tombstone_allows_visible_state_cas_without_version_reuse(
    postgres_db_real: PostgresDb,
) -> None:
    """Deleting v2 restores visible latest=v1, but its audit tombstone reserves v2 forever."""
    _create_component(postgres_db_real, "aba-agent")
    postgres_db_real.upsert_config(
        "aba-agent",
        config={"instructions": "discarded v2"},
        stage="draft",
        guard=_guard(1, 1),
    )
    assert postgres_db_real.delete_config("aba-agent", 2, guard=_guard(2, 1))

    configs_table = postgres_db_real._get_table(table_type="component_configs")
    assert configs_table is not None
    with postgres_db_real.Session() as session:
        tombstone = (
            session.execute(
                configs_table.select().where(
                    configs_table.c.component_id == "aba-agent",
                    configs_table.c.version == 2,
                )
            )
            .mappings()
            .one()
        )
    assert tombstone["stage"] == DELETED_CONFIG_STAGE
    assert tombstone["config"] == {}
    assert tombstone["updated_at"] is not None

    # Guards intentionally compare visible lifecycle state. After deleting the
    # only draft, latest=v1/current=v1 is fresh again; the high-water mark still
    # makes this append v3 rather than overwriting or reusing the audited v2.
    replacement = postgres_db_real.upsert_config(
        "aba-agent",
        config={"instructions": "replacement"},
        stage="draft",
        guard=_guard(1, 1),
    )

    assert replacement["version"] == 3
    assert postgres_db_real.get_config("aba-agent", version=2) is None
    with postgres_db_real.Session() as session:
        history = session.execute(
            configs_table.select().where(configs_table.c.component_id == "aba-agent").order_by(configs_table.c.version)
        ).fetchall()
    assert [(row.version, row.stage) for row in history] == [
        (1, "published"),
        (2, DELETED_CONFIG_STAGE),
        (3, "draft"),
    ]
    with pytest.raises(ValueError, match="not found"):
        postgres_db_real.upsert_config(
            "aba-agent",
            version=2,
            stage="published",
            guard=_guard(3, 1),
            projection={"name": "Must not publish"},
        )


def test_postgres_publish_revalidates_stored_links(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "draft-child-for-publish", stage="draft")
    _create_component(postgres_db_real, "parent-for-publish", component_type=ComponentType.TEAM)
    postgres_db_real.upsert_config(
        "parent-for-publish",
        config={"members": ["draft-child-for-publish"]},
        stage="draft",
        guard=_guard(1, 1),
        links=[
            {
                "link_kind": "member",
                "link_key": "member_0",
                "child_component_id": "draft-child-for-publish",
                "child_version": 1,
                "position": 0,
                "meta": {"type": "agent"},
            }
        ],
    )

    with pytest.raises(ValueError, match="not published"):
        postgres_db_real.upsert_config(
            "parent-for-publish",
            version=2,
            stage="published",
            guard=_guard(2, 1),
            projection={"name": "Must remain draft"},
        )

    parent = postgres_db_real.get_component("parent-for-publish")
    draft = postgres_db_real.get_config("parent-for-publish", version=2)
    assert parent is not None
    assert draft is not None
    assert parent["current_version"] == 1
    assert draft["stage"] == "draft"


def test_postgres_guarded_publish_atomically_derives_and_persists_links(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "published-child-for-derived-link")
    _create_component(
        postgres_db_real,
        "draft-parent-for-derived-link",
        component_type=ComponentType.TEAM,
        stage="draft",
    )

    published = postgres_db_real.upsert_config(
        "draft-parent-for-derived-link",
        version=1,
        stage="published",
        guard=_guard(1, None),
        projection={"name": "Published parent"},
        links=[
            {
                "link_kind": "member",
                "link_key": "member_0",
                "child_component_id": "published-child-for-derived-link",
                "child_version": 1,
                "position": 0,
                "meta": {"type": "agent"},
            }
        ],
    )

    assert published["stage"] == "published"
    component = postgres_db_real.get_component("draft-parent-for-derived-link")
    assert component is not None and component["current_version"] == 1
    links = postgres_db_real.get_links("draft-parent-for-derived-link", 1)
    assert [(link["child_component_id"], link["child_version"]) for link in links] == [
        ("published-child-for-derived-link", 1)
    ]


def test_postgres_rejects_unpublished_child_pin_atomically(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "draft-child", stage="draft")

    with pytest.raises(ValueError, match="not published"):
        _create_component(
            postgres_db_real,
            "invalid-parent",
            component_type=ComponentType.TEAM,
            links=[
                {
                    "link_kind": "member",
                    "link_key": "member_0",
                    "child_component_id": "draft-child",
                    "child_version": 1,
                    "position": 0,
                    "meta": {"type": "agent"},
                }
            ],
        )

    assert postgres_db_real.get_component("invalid-parent", include_deleted=True) is None
    assert postgres_db_real.get_config("invalid-parent", version=1) is None


def test_postgres_archive_is_dependency_safe_and_archived_ids_remain_occupied(
    postgres_db_real: PostgresDb,
) -> None:
    _create_component(postgres_db_real, "child-agent")
    _create_component(
        postgres_db_real,
        "parent-team",
        component_type=ComponentType.TEAM,
        links=[
            {
                "link_kind": "member",
                "link_key": "member_0",
                "child_component_id": "child-agent",
                "child_version": 1,
                "position": 0,
                "meta": {"type": "agent"},
            }
        ],
    )

    with pytest.raises(ComponentDependencyError):
        postgres_db_real.delete_component(
            "child-agent",
            guard=_guard(1, 1),
            require_no_dependents=True,
        )

    assert postgres_db_real.delete_component(
        "parent-team",
        guard=_guard(1, 1),
        require_no_dependents=True,
    )
    assert postgres_db_real.get_dependents("child-agent", active_parents_only=True) == []
    assert postgres_db_real.delete_component(
        "child-agent",
        guard=_guard(1, 1),
        require_no_dependents=True,
        projection={"name": "Archived child", "metadata": {"release": 1}},
    )
    archived = postgres_db_real.get_component("child-agent", include_deleted=True)
    assert archived is not None
    assert archived["name"] == "Archived child"
    assert archived["metadata"] == {"release": 1}

    with pytest.raises(ComponentAlreadyExistsError):
        _create_component(postgres_db_real, "child-agent", name="Replacement")


def test_postgres_restore_component_is_guarded_and_preserves_history(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "restored-agent", name="Published")
    assert postgres_db_real.delete_component("restored-agent", guard=_guard(1, 1))

    assert postgres_db_real.get_config("restored-agent") is None
    archived_config = postgres_db_real.get_config("restored-agent", version=1, include_deleted=True)
    assert archived_config is not None
    assert archived_config["version"] == 1
    archived_latest = postgres_db_real.get_latest_config("restored-agent", include_deleted=True)
    assert archived_latest is not None
    assert archived_latest["version"] == 1

    with pytest.raises(ComponentVersionConflictError):
        postgres_db_real.restore_component("restored-agent", guard=_guard(0, 1))
    assert postgres_db_real.get_component("restored-agent") is None

    assert postgres_db_real.restore_component(
        "restored-agent",
        guard=_guard(1, 1),
        projection={"name": "Restored", "description": "Same identity", "metadata": {"restored": True}},
    )
    restored = postgres_db_real.get_component("restored-agent")
    assert restored is not None
    assert restored["name"] == "Restored"
    assert restored["description"] == "Same identity"
    assert restored["metadata"] == {"restored": True}
    assert postgres_db_real.get_current_config("restored-agent")["version"] == 1  # type: ignore[index]
    assert [row["version"] for row in postgres_db_real.list_configs("restored-agent")] == [1]


def test_postgres_restore_rejects_an_archived_pinned_dependency_but_allows_draft_only_components(
    postgres_db_real: PostgresDb,
) -> None:
    _create_component(postgres_db_real, "restore-child")
    _create_component(
        postgres_db_real,
        "restore-parent",
        component_type=ComponentType.WORKFLOW,
        links=[_component_link("restore-child")],
    )
    assert postgres_db_real.delete_component("restore-parent", guard=_guard(1, 1))
    assert postgres_db_real.delete_component("restore-child", guard=_guard(1, 1))

    with pytest.raises(ComponentDependencyUnavailableError) as unavailable:
        postgres_db_real.restore_component("restore-parent", guard=_guard(1, 1))

    assert unavailable.value.component_id == "restore-parent"
    assert unavailable.value.dependencies == [
        {
            "component_id": "restore-child",
            "version": 1,
            "referenced_by": {"component_id": "restore-parent", "version": 1},
            "reason": "component_archived",
        }
    ]
    parent = postgres_db_real.get_component("restore-parent", include_deleted=True)
    assert parent is not None and parent["deleted_at"] is not None

    assert postgres_db_real.restore_component("restore-child", guard=_guard(1, 1))
    assert postgres_db_real.restore_component("restore-parent", guard=_guard(1, 1))

    _create_component(postgres_db_real, "restore-draft", stage="draft")
    assert postgres_db_real.delete_component("restore-draft", guard=_guard(1, None))
    assert postgres_db_real.restore_component("restore-draft", guard=_guard(1, None))
    restored_draft = postgres_db_real.get_component("restore-draft")
    assert restored_draft is not None and restored_draft["current_version"] is None


def test_postgres_restore_and_dependency_archive_race_never_exposes_a_broken_graph(
    postgres_db_real: PostgresDb,
) -> None:
    _create_component(postgres_db_real, "restore-race-child")
    _create_component(
        postgres_db_real,
        "restore-race-parent",
        component_type=ComponentType.WORKFLOW,
        links=[_component_link("restore-race-child")],
    )
    assert postgres_db_real.delete_component("restore-race-parent", guard=_guard(1, 1))
    ready = Barrier(2)

    def restore_parent() -> str:
        ready.wait()
        try:
            postgres_db_real.restore_component("restore-race-parent", guard=_guard(1, 1))
        except ComponentDependencyUnavailableError:
            return "restore_blocked"
        return "restored"

    def archive_child() -> str:
        ready.wait()
        try:
            postgres_db_real.delete_component("restore-race-child", guard=_guard(1, 1))
        except ComponentDependencyError:
            return "archive_blocked"
        return "archived"

    with ThreadPoolExecutor(max_workers=2) as executor:
        restore_future = executor.submit(restore_parent)
        archive_future = executor.submit(archive_child)
        outcomes = {restore_future.result(timeout=10), archive_future.result(timeout=10)}

    assert outcomes in ({"restored", "archive_blocked"}, {"restore_blocked", "archived"})
    parent_is_active = postgres_db_real.get_component("restore-race-parent") is not None
    child_is_active = postgres_db_real.get_component("restore-race-child") is not None
    if outcomes == {"restored", "archive_blocked"}:
        assert parent_is_active and child_is_active
    else:
        assert not parent_is_active and not child_is_active


def test_postgres_atomic_restore_and_draft_append_roll_back_when_the_current_graph_is_unavailable(
    postgres_db_real: PostgresDb,
) -> None:
    _create_component(postgres_db_real, "restore-append-child")
    _create_component(
        postgres_db_real,
        "restore-append-parent",
        component_type=ComponentType.WORKFLOW,
        links=[_component_link("restore-append-child")],
    )
    assert postgres_db_real.delete_component("restore-append-parent", guard=_guard(1, 1))
    assert postgres_db_real.delete_component("restore-append-child", guard=_guard(1, 1))

    with pytest.raises(ComponentDependencyUnavailableError):
        postgres_db_real.upsert_config(
            "restore-append-parent",
            config={"name": "Draft edit"},
            stage="draft",
            guard=_guard(1, 1),
            restore_if_deleted=True,
            expected_component_type=ComponentType.WORKFLOW,
        )

    parent = postgres_db_real.get_component("restore-append-parent", include_deleted=True)
    assert parent is not None and parent["deleted_at"] is not None
    latest = postgres_db_real.get_latest_config("restore-append-parent", include_deleted=True)
    assert latest is not None and latest["version"] == 1

    _create_component(postgres_db_real, "restore-repair-child")
    repaired = postgres_db_real.upsert_config(
        "restore-append-parent",
        config={"name": "Published repair"},
        stage="published",
        guard=_guard(1, 1),
        links=[_component_link("restore-repair-child")],
        restore_if_deleted=True,
        expected_component_type=ComponentType.WORKFLOW,
    )
    assert repaired["version"] == 2
    parent = postgres_db_real.get_component("restore-append-parent")
    assert parent is not None and parent["current_version"] == 2
    assert postgres_db_real.get_component("restore-append-child") is None


def test_postgres_atomic_restore_and_append_rolls_back_on_duplicate_label(
    postgres_db_real: PostgresDb,
) -> None:
    postgres_db_real.create_component_with_config(
        component_id="restore-append-agent",
        component_type=ComponentType.AGENT,
        name="Version one",
        config={"name": "Version one"},
        stage="published",
        label="stable",
    )
    assert postgres_db_real.delete_component("restore-append-agent", guard=_guard(1, 1))

    with pytest.raises(ValueError, match="Label 'stable' already exists"):
        postgres_db_real.upsert_config(
            "restore-append-agent",
            config={"name": "Rejected version"},
            stage="published",
            label="stable",
            projection={"name": "Rejected version"},
            restore_if_deleted=True,
        )

    assert postgres_db_real.get_component("restore-append-agent") is None
    archived = postgres_db_real.get_component("restore-append-agent", include_deleted=True)
    assert archived is not None and archived["deleted_at"] is not None
    assert postgres_db_real.get_latest_config("restore-append-agent", include_deleted=True)["version"] == 1  # type: ignore[index]

    appended = postgres_db_real.upsert_config(
        "restore-append-agent",
        config={"name": "Version two"},
        stage="published",
        label="next",
        projection={"name": "Version two"},
        restore_if_deleted=True,
    )
    assert appended["version"] == 2
    restored = postgres_db_real.get_component("restore-append-agent")
    assert restored is not None
    assert restored["current_version"] == 2
    assert restored["name"] == "Version two"


def test_postgres_expected_component_type_rejects_replaced_identity(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "replaced-identity", component_type=ComponentType.AGENT)
    assert postgres_db_real.delete_component(
        "replaced-identity",
        hard_delete=True,
        require_no_dependents=False,
    )
    _create_component(postgres_db_real, "replaced-identity", component_type=ComponentType.TEAM)

    with pytest.raises(ValueError, match="has type team, not agent"):
        postgres_db_real.upsert_config(
            "replaced-identity",
            config={"name": "Agent payload"},
            stage="published",
            projection={"name": "Agent payload"},
            expected_component_type=ComponentType.AGENT,
        )
    with pytest.raises(ValueError, match="has type team, not agent"):
        postgres_db_real.delete_component(
            "replaced-identity",
            guard=_guard(1, 1),
            expected_component_type=ComponentType.AGENT,
        )

    component = postgres_db_real.get_component("replaced-identity")
    assert component is not None
    assert component["component_type"] == ComponentType.TEAM.value
    assert component["current_version"] == 1
    assert [row["version"] for row in postgres_db_real.list_configs("replaced-identity")] == [1]


def test_postgres_draft_with_inbound_pin_cannot_be_deleted(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "pinned-draft", stage="draft")
    _create_component(postgres_db_real, "legacy-parent", component_type=ComponentType.TEAM)

    links_table = postgres_db_real._get_table(table_type="component_links", create_table_if_not_found=True)
    assert links_table is not None
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            links_table.insert().values(
                parent_component_id="legacy-parent",
                parent_version=1,
                link_kind="member",
                link_key="member_0",
                child_component_id="pinned-draft",
                child_version=1,
                position=0,
            )
        )

    with pytest.raises(ComponentDependencyError):
        postgres_db_real.delete_config("pinned-draft", 1, guard=_guard(1, None))


def test_postgres_concurrent_guarded_appends_yield_one_conflict(postgres_db_real: PostgresDb) -> None:
    _create_component(postgres_db_real, "concurrent-agent")
    ready = Barrier(2)

    def append_draft(instructions: str) -> str:
        ready.wait()
        try:
            postgres_db_real.upsert_config(
                "concurrent-agent",
                config={"instructions": instructions},
                stage="draft",
                guard=_guard(1, 1),
            )
        except ComponentVersionConflictError:
            return "conflict"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append_draft, ["writer one", "writer two"]))

    assert sorted(outcomes) == ["conflict", "created"]
    assert [config["version"] for config in postgres_db_real.list_configs("concurrent-agent")] == [2, 1]


def test_postgres_atomic_create_rejects_self_cycle_without_rows(postgres_db_real: PostgresDb) -> None:
    with pytest.raises(ComponentCycleError) as exc:
        _create_component(
            postgres_db_real,
            "self-cycle",
            component_type=ComponentType.WORKFLOW,
            stage="draft",
            links=[_component_link("self-cycle")],
        )

    assert exc.value.cycle_path == ["self-cycle", "self-cycle"]
    assert postgres_db_real.get_component("self-cycle", include_deleted=True) is None
    assert postgres_db_real.get_config("self-cycle", version=1) is None


def test_postgres_two_node_and_multi_node_cycles_fail_transactionally(postgres_db_real: PostgresDb) -> None:
    for component_id in ("cycle-a", "cycle-b", "cycle-c"):
        _create_component(postgres_db_real, component_id)

    postgres_db_real.upsert_config(
        "cycle-a",
        config={"child": "cycle-b"},
        stage="draft",
        guard=_guard(1, 1),
        links=[_component_link("cycle-b")],
    )
    with pytest.raises(ComponentCycleError) as two_node:
        postgres_db_real.upsert_config(
            "cycle-b",
            config={"child": "cycle-a"},
            stage="draft",
            guard=_guard(1, 1),
            links=[_component_link("cycle-a")],
        )
    assert two_node.value.cycle_path == ["cycle-b", "cycle-a", "cycle-b"]
    assert [row["version"] for row in postgres_db_real.list_configs("cycle-b")] == [1]

    postgres_db_real.upsert_config(
        "cycle-b",
        config={"child": "cycle-c"},
        stage="draft",
        guard=_guard(1, 1),
        links=[_component_link("cycle-c")],
    )
    with pytest.raises(ComponentCycleError) as multi_node:
        postgres_db_real.upsert_config(
            "cycle-c",
            config={"child": "cycle-a"},
            stage="draft",
            guard=_guard(1, 1),
            links=[_component_link("cycle-a")],
        )
    assert multi_node.value.cycle_path == ["cycle-c", "cycle-a", "cycle-b", "cycle-c"]
    assert [row["version"] for row in postgres_db_real.list_configs("cycle-c")] == [1]


def test_postgres_cross_parent_link_writes_commit_at_most_one_edge(postgres_db_real: PostgresDb) -> None:
    """A->B and B->A writes serialize, and the second edge fails as a cycle."""
    _create_component(postgres_db_real, "graph-a")
    _create_component(postgres_db_real, "graph-b")
    ready = Barrier(2)

    def append_link(parent_id: str, child_id: str) -> str:
        ready.wait()
        try:
            postgres_db_real.upsert_config(
                parent_id,
                config={"child": child_id},
                stage="draft",
                guard=_guard(1, 1),
                links=[_component_link(child_id)],
            )
        except ComponentCycleError:
            return "cycle"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        a_to_b = executor.submit(append_link, "graph-a", "graph-b")
        b_to_a = executor.submit(append_link, "graph-b", "graph-a")
        outcomes = [a_to_b.result(timeout=10), b_to_a.result(timeout=10)]

    assert sorted(outcomes) == ["created", "cycle"]
    created_versions = sum(
        len(postgres_db_real.list_configs(component_id)) - 1 for component_id in ("graph-a", "graph-b")
    )
    assert created_versions == 1
