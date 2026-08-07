"""SQLite integration tests for guarded component lifecycle operations."""

import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any, Dict, List, Optional, cast

import pytest
from sqlalchemy.exc import IntegrityError

from agno.db.base import (
    DELETED_CONFIG_STAGE,
    ComponentAlreadyExistsError,
    ComponentCycleError,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentProjection,
    ComponentType,
    ComponentVersionConflictError,
    ComponentVersionGuard,
)
from agno.db.sqlite.sqlite import SqliteDb


def _first_component_write_in_process(
    db_file: str,
    component_id: str,
    ready: Any,
    results: Any,
) -> None:
    try:
        db = SqliteDb(db_file=db_file)
        ready.wait(timeout=10)
        db.create_component_with_config(
            component_id=component_id,
            component_type=ComponentType.AGENT,
            name=component_id,
            config={"name": component_id},
            stage="draft",
        )
        results.put(("created", component_id))
    except Exception as exc:
        results.put(("error", f"{type(exc).__name__}: {exc}"))


def _create_component(
    db: SqliteDb,
    component_id: str,
    *,
    component_type: ComponentType = ComponentType.AGENT,
    stage: str = "published",
    name: Optional[str] = None,
    config: Optional[Dict[str, object]] = None,
    links: Optional[List[Dict[str, object]]] = None,
) -> None:
    db.create_component_with_config(
        component_id=component_id,
        component_type=component_type,
        name=name or component_id,
        config=config or {"name": name or component_id},
        stage=stage,
        links=links,
    )


def _guard(latest_version: Optional[int], current_version: Optional[int]) -> ComponentVersionGuard:
    return ComponentVersionGuard(latest_version=latest_version, current_version=current_version)


def _component_link(child_id: str, *, link_key: str = "step_0") -> Dict[str, object]:
    return {
        "link_kind": "step_agent",
        "link_key": link_key,
        "child_component_id": child_id,
        "child_version": 1,
        "position": 0,
    }


def test_draft_only_component_has_no_implicit_current_config(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "draft-agent", stage="draft")

    component = sqlite_db_real.get_component("draft-agent")
    assert component is not None
    assert component["current_version"] is None
    assert sqlite_db_real.get_config("draft-agent") is None

    draft = sqlite_db_real.get_config("draft-agent", version=1)
    assert draft is not None
    assert draft["version"] == 1
    assert draft["stage"] == "draft"


def test_draft_projection_tracks_latest_only_until_first_publish(sqlite_db_real: SqliteDb) -> None:
    _create_component(
        sqlite_db_real,
        "draft-projection",
        stage="draft",
        name="Draft one",
        config={"name": "Draft one"},
    )

    sqlite_db_real.upsert_config(
        "draft-projection",
        config={"name": "Draft two"},
        stage="draft",
        projection={"name": "Draft two"},
    )
    component = sqlite_db_real.get_component("draft-projection")
    assert component is not None
    assert component["current_version"] is None
    assert component["name"] == "Draft two"

    sqlite_db_real.upsert_config(
        "draft-projection",
        config={"name": "Published"},
        stage="published",
        projection={"name": "Published"},
    )
    with pytest.raises(ValueError, match="draft projection.*published projection"):
        sqlite_db_real.upsert_config(
            "draft-projection",
            config={"name": "Must not leak"},
            stage="draft",
            projection={"name": "Must not leak"},
        )

    component = sqlite_db_real.get_component("draft-projection")
    assert component is not None
    assert component["current_version"] == 3
    assert component["name"] == "Published"


def test_only_draft_cannot_be_deleted_into_a_zombie(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "sole-draft", stage="draft")

    with pytest.raises(ValueError, match="last config.*archive"):
        sqlite_db_real.delete_config(
            "sole-draft",
            1,
            guard=_guard(1, None),
        )

    assert [row["version"] for row in sqlite_db_real.list_configs("sole-draft")] == [1]
    assert sqlite_db_real.get_config("sole-draft", version=1) is not None
    assert sqlite_db_real.delete_component("sole-draft", guard=_guard(1, None)) is True


def test_generic_component_update_cannot_move_current_pointer(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "pointer-agent", name="Version one")
    sqlite_db_real.upsert_config(
        "pointer-agent",
        config={"name": "Version two"},
        stage="published",
        projection={"name": "Version two"},
    )

    with pytest.raises(ValueError, match="set_current_version"):
        sqlite_db_real.upsert_component("pointer-agent", current_version=1)

    component = sqlite_db_real.get_component("pointer-agent")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Version two"


def test_mutation_results_are_captured_before_commit(
    sqlite_db_real: SqliteDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_public_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("mutation must not perform a post-commit public read")

    monkeypatch.setattr(sqlite_db_real, "get_component", fail_public_read)
    monkeypatch.setattr(sqlite_db_real, "get_config", fail_public_read)

    component, initial = sqlite_db_real.create_component_with_config(
        component_id="atomic-response",
        component_type=ComponentType.AGENT,
        name="Initial",
        config={"name": "Initial"},
        stage="published",
    )
    assert component["component_id"] == "atomic-response"
    assert initial["version"] == 1

    updated = sqlite_db_real.upsert_component("atomic-response", name="Updated")
    draft = sqlite_db_real.upsert_config(
        "atomic-response",
        config={"name": "Draft"},
        stage="draft",
        guard=_guard(1, 1),
    )

    assert updated["name"] == "Updated"
    assert draft["version"] == 2
    assert draft["stage"] == "draft"


def test_guarded_draft_append_rejects_stale_writer_and_in_place_mutation(sqlite_db_real: SqliteDb) -> None:
    _create_component(
        sqlite_db_real,
        "guarded-agent",
        config={"instructions": "published"},
    )

    draft = sqlite_db_real.upsert_config(
        component_id="guarded-agent",
        config={"instructions": "first writer"},
        stage="draft",
        guard=_guard(1, 1),
    )
    assert draft["version"] == 2

    with pytest.raises(ComponentVersionConflictError) as conflict:
        sqlite_db_real.upsert_config(
            component_id="guarded-agent",
            config={"instructions": "stale writer"},
            stage="draft",
            guard=_guard(1, 1),
        )

    assert conflict.value.expected == _guard(1, 1)
    assert conflict.value.actual == _guard(2, 1)

    with pytest.raises(ValueError):
        sqlite_db_real.upsert_config(
            component_id="guarded-agent",
            version=2,
            config={"instructions": "in-place mutation"},
            guard=_guard(2, 1),
        )

    published = sqlite_db_real.get_config("guarded-agent", version=1)
    persisted_draft = sqlite_db_real.get_config("guarded-agent", version=2)
    assert published is not None
    assert persisted_draft is not None
    assert published["config"] == {"instructions": "published"}
    assert persisted_draft["config"] == {"instructions": "first writer"}
    assert [config["version"] for config in sqlite_db_real.list_configs("guarded-agent")] == [2, 1]


def test_concurrent_guarded_appends_serialize_to_success_and_conflict(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "concurrent-agent", config={"instructions": "published"})
    ready = Barrier(2)

    def append_draft(instructions: str) -> str:
        ready.wait()
        try:
            sqlite_db_real.upsert_config(
                component_id="concurrent-agent",
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
    configs = sqlite_db_real.list_configs("concurrent-agent", include_config=True)
    assert [config["version"] for config in configs] == [2, 1]
    assert configs[0]["config"]["instructions"] in {"writer one", "writer two"}


def test_atomic_create_rejects_self_cycle_without_rows(sqlite_db_real: SqliteDb) -> None:
    with pytest.raises(ComponentCycleError) as exc:
        _create_component(
            sqlite_db_real,
            "self-cycle",
            component_type=ComponentType.WORKFLOW,
            stage="draft",
            links=[_component_link("self-cycle")],
        )

    assert exc.value.cycle_path == ["self-cycle", "self-cycle"]
    assert sqlite_db_real.get_component("self-cycle", include_deleted=True) is None
    assert sqlite_db_real.get_config("self-cycle", version=1) is None


def test_two_node_and_multi_node_cycles_fail_transactionally(sqlite_db_real: SqliteDb) -> None:
    for component_id in ("cycle-a", "cycle-b", "cycle-c"):
        _create_component(sqlite_db_real, component_id)

    sqlite_db_real.upsert_config(
        "cycle-a",
        config={"child": "cycle-b"},
        stage="draft",
        guard=_guard(1, 1),
        links=[_component_link("cycle-b")],
    )
    with pytest.raises(ComponentCycleError) as two_node:
        sqlite_db_real.upsert_config(
            "cycle-b",
            config={"child": "cycle-a"},
            stage="draft",
            guard=_guard(1, 1),
            links=[_component_link("cycle-a")],
        )
    assert two_node.value.cycle_path == ["cycle-b", "cycle-a", "cycle-b"]
    assert [row["version"] for row in sqlite_db_real.list_configs("cycle-b")] == [1]

    sqlite_db_real.upsert_config(
        "cycle-b",
        config={"child": "cycle-c"},
        stage="draft",
        guard=_guard(1, 1),
        links=[_component_link("cycle-c")],
    )
    with pytest.raises(ComponentCycleError) as multi_node:
        sqlite_db_real.upsert_config(
            "cycle-c",
            config={"child": "cycle-a"},
            stage="draft",
            guard=_guard(1, 1),
            links=[_component_link("cycle-a")],
        )
    assert multi_node.value.cycle_path == ["cycle-c", "cycle-a", "cycle-b", "cycle-c"]
    assert [row["version"] for row in sqlite_db_real.list_configs("cycle-c")] == [1]


def test_concurrent_cross_component_edges_commit_at_most_one(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "cross-a")
    _create_component(sqlite_db_real, "cross-b")
    ready = Barrier(2)

    def append_link(parent_id: str, child_id: str) -> str:
        ready.wait()
        try:
            sqlite_db_real.upsert_config(
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
        outcomes = list(executor.map(lambda pair: append_link(*pair), [("cross-a", "cross-b"), ("cross-b", "cross-a")]))

    assert sorted(outcomes) == ["created", "cycle"]
    created_versions = sum(
        len(sqlite_db_real.list_configs(component_id)) - 1 for component_id in ("cross-a", "cross-b")
    )
    assert created_versions == 1


def test_first_component_write_is_safe_across_processes(tmp_path: Path) -> None:
    db_file = str(tmp_path / "multi-process-components.db")
    context = multiprocessing.get_context("spawn")
    ready = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_first_component_write_in_process,
            args=(db_file, component_id, ready, results),
        )
        for component_id in ("process-a", "process-b")
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)

    assert all(not process.is_alive() for process in processes)
    assert all(process.exitcode == 0 for process in processes)
    outcomes = sorted(results.get(timeout=5) for _ in processes)
    assert outcomes == [("created", "process-a"), ("created", "process-b")]

    db = SqliteDb(db_file=db_file)
    rows, total = db.list_components(limit=10)
    assert total == 2
    assert {row["component_id"] for row in rows} == {"process-a", "process-b"}


def test_publish_updates_stage_current_pointer_and_projection_together(sqlite_db_real: SqliteDb) -> None:
    _create_component(
        sqlite_db_real,
        "publish-agent",
        name="Published name",
        config={"instructions": "v1"},
    )
    draft = sqlite_db_real.upsert_config(
        component_id="publish-agent",
        config={"instructions": "v2"},
        stage="draft",
        guard=_guard(1, 1),
    )
    projection: ComponentProjection = {
        "name": "Draft promoted",
        "description": "Projected from version two",
        "metadata": {"release": 2},
    }

    published = sqlite_db_real.upsert_config(
        component_id="publish-agent",
        version=draft["version"],
        stage="published",
        guard=_guard(2, 1),
        projection=projection,
    )

    assert published["stage"] == "published"
    assert published["config"] == {"instructions": "v2"}
    component = sqlite_db_real.get_component("publish-agent")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Draft promoted"
    assert component["description"] == "Projected from version two"
    assert component["metadata"] == {"release": 2}
    assert sqlite_db_real.get_config("publish-agent") == published


def test_existing_draft_payload_is_immutable_and_publish_derives_projection(sqlite_db_real: SqliteDb) -> None:
    sqlite_db_real.create_component_with_config(
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
        sqlite_db_real.upsert_config(
            "immutable-draft",
            version=1,
            config={"name": "mutated"},
            stage="draft",
        )
    with pytest.raises(ValueError, match="cannot mutate config"):
        sqlite_db_real.upsert_config(
            "immutable-draft",
            version=1,
            config={"name": "mutated"},
            stage="published",
            guard=_guard(1, None),
        )

    published = sqlite_db_real.upsert_config(
        "immutable-draft",
        version=1,
        stage="published",
        guard=_guard(1, None),
    )
    component = sqlite_db_real.get_component("immutable-draft")

    assert published["config"]["instructions"] == "original"
    assert component is not None
    assert component["current_version"] == 1
    assert component["name"] == "Locked draft"
    assert component["description"] == "Derived from the stored payload"
    assert component["metadata"] == {"release": 1}


def test_publish_and_set_current_derive_projection_from_target_config(sqlite_db_real: SqliteDb) -> None:
    sqlite_db_real.create_component_with_config(
        component_id="derived-pointer",
        component_type=ComponentType.AGENT,
        name="Version one",
        config={"name": "Version one", "description": "First", "metadata": {"release": 1}},
        description="First",
        metadata={"release": 1},
        stage="published",
    )

    sqlite_db_real.upsert_config(
        "derived-pointer",
        config={"name": "Version two", "description": "Second", "metadata": {"release": 2}},
        stage="published",
    )
    component = sqlite_db_real.get_component("derived-pointer")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Version two"
    assert component["description"] == "Second"
    assert component["metadata"] == {"release": 2}

    assert sqlite_db_real.set_current_version("derived-pointer", 1, guard=_guard(2, 2))
    component = sqlite_db_real.get_component("derived-pointer")
    assert component is not None
    assert component["current_version"] == 1
    assert component["name"] == "Version one"
    assert component["description"] == "First"
    assert component["metadata"] == {"release": 1}


def test_projection_failure_rolls_back_publish_transition(sqlite_db_real: SqliteDb) -> None:
    _create_component(
        sqlite_db_real,
        "invalid-projection-agent",
        name="Original name",
        config={"instructions": "v1"},
    )
    sqlite_db_real.upsert_config(
        component_id="invalid-projection-agent",
        config={"instructions": "v2"},
        stage="draft",
        guard=_guard(1, 1),
    )

    invalid_projection = cast(ComponentProjection, {"unknown_field": "must fail"})
    with pytest.raises(ValueError, match="projection"):
        sqlite_db_real.upsert_config(
            component_id="invalid-projection-agent",
            version=2,
            stage="published",
            guard=_guard(2, 1),
            projection=invalid_projection,
        )

    component = sqlite_db_real.get_component("invalid-projection-agent")
    draft = sqlite_db_real.get_config("invalid-projection-agent", version=2)
    assert component is not None
    assert draft is not None
    assert component["current_version"] == 1
    assert component["name"] == "Original name"
    assert draft["stage"] == "draft"


def test_stale_publish_guard_leaves_draft_and_component_projection_unchanged(sqlite_db_real: SqliteDb) -> None:
    _create_component(
        sqlite_db_real,
        "stale-publish-agent",
        name="Original name",
        config={"instructions": "v1"},
    )
    sqlite_db_real.upsert_config(
        component_id="stale-publish-agent",
        config={"instructions": "v2"},
        stage="draft",
        guard=_guard(1, 1),
    )

    with pytest.raises(ComponentVersionConflictError):
        sqlite_db_real.upsert_config(
            component_id="stale-publish-agent",
            version=2,
            stage="published",
            guard=_guard(1, 1),
            projection={"name": "Must not leak"},
        )

    component = sqlite_db_real.get_component("stale-publish-agent")
    draft = sqlite_db_real.get_config("stale-publish-agent", version=2)
    assert component is not None
    assert draft is not None
    assert component["current_version"] == 1
    assert component["name"] == "Original name"
    assert draft["stage"] == "draft"


def test_rollback_updates_current_pointer_and_projection_together(sqlite_db_real: SqliteDb) -> None:
    _create_component(
        sqlite_db_real,
        "rollback-agent",
        name="Version one",
        config={"instructions": "v1"},
    )
    sqlite_db_real.upsert_config(
        component_id="rollback-agent",
        config={"instructions": "v2"},
        stage="draft",
        guard=_guard(1, 1),
    )
    sqlite_db_real.upsert_config(
        component_id="rollback-agent",
        version=2,
        stage="published",
        guard=_guard(2, 1),
        projection={"name": "Version two", "metadata": {"release": 2}},
    )

    did_rollback = sqlite_db_real.set_current_version(
        component_id="rollback-agent",
        version=1,
        guard=_guard(2, 2),
        projection={"name": "Version one", "description": "Restored", "metadata": {"release": 1}},
    )

    assert did_rollback is True
    component = sqlite_db_real.get_component("rollback-agent")
    assert component is not None
    assert component["current_version"] == 1
    assert component["name"] == "Version one"
    assert component["description"] == "Restored"
    assert component["metadata"] == {"release": 1}
    current = sqlite_db_real.get_config("rollback-agent")
    assert current is not None
    assert current["version"] == 1


def test_non_current_published_config_cannot_be_deleted(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "published-delete-agent", config={"instructions": "v1"})
    sqlite_db_real.upsert_config(
        component_id="published-delete-agent",
        config={"instructions": "v2"},
        stage="draft",
        guard=_guard(1, 1),
    )
    sqlite_db_real.upsert_config(
        component_id="published-delete-agent",
        version=2,
        stage="published",
        guard=_guard(2, 1),
        projection={"name": "Version two"},
    )
    sqlite_db_real.set_current_version(
        component_id="published-delete-agent",
        version=1,
        guard=_guard(2, 2),
        projection={"name": "Version one"},
    )

    with pytest.raises(ComponentDraftRequiredError, match="only draft configs") as exc:
        sqlite_db_real.delete_config(
            component_id="published-delete-agent",
            version=2,
            guard=_guard(2, 1),
        )

    assert exc.value.component_id == "published-delete-agent"
    assert exc.value.version == 2

    assert sqlite_db_real.get_config("published-delete-agent", version=2) is not None


def test_draft_delete_and_projection_are_one_transaction(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "audited-delete", config={"instructions": "v1"})
    sqlite_db_real.upsert_config(
        component_id="audited-delete",
        config={"instructions": "discard me"},
        stage="draft",
        guard=_guard(1, 1),
    )

    invalid_projection = cast(ComponentProjection, {"unknown_field": "must fail"})
    with pytest.raises(ValueError, match="projection"):
        sqlite_db_real.delete_config(
            "audited-delete",
            2,
            guard=_guard(2, 1),
            projection=invalid_projection,
        )

    assert sqlite_db_real.get_config("audited-delete", version=2) is not None
    assert sqlite_db_real.delete_config(
        "audited-delete",
        2,
        guard=_guard(2, 1),
        projection={"metadata": {"last_action": "delete_version"}},
    )
    component = sqlite_db_real.get_component("audited-delete")
    assert component is not None
    assert component["metadata"] == {"last_action": "delete_version"}
    assert sqlite_db_real.get_config("audited-delete", version=2) is None


def test_deleted_draft_tombstone_allows_visible_state_cas_without_version_reuse(sqlite_db_real: SqliteDb) -> None:
    """Deleting v2 restores visible latest=v1, but its audit tombstone reserves v2 forever."""
    _create_component(sqlite_db_real, "aba-agent")
    sqlite_db_real.upsert_config(
        "aba-agent",
        config={"instructions": "discarded v2"},
        stage="draft",
        guard=_guard(1, 1),
    )
    assert sqlite_db_real.delete_config("aba-agent", 2, guard=_guard(2, 1))

    configs_table = sqlite_db_real._get_table(table_type="component_configs")
    assert configs_table is not None
    with sqlite_db_real.Session() as session:
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
    replacement = sqlite_db_real.upsert_config(
        "aba-agent",
        config={"instructions": "replacement"},
        stage="draft",
        guard=_guard(1, 1),
    )

    assert replacement["version"] == 3
    assert sqlite_db_real.get_config("aba-agent", version=2) is None
    with sqlite_db_real.Session() as session:
        history = session.execute(
            configs_table.select().where(configs_table.c.component_id == "aba-agent").order_by(configs_table.c.version)
        ).fetchall()
    assert [(row.version, row.stage) for row in history] == [
        (1, "published"),
        (2, DELETED_CONFIG_STAGE),
        (3, "draft"),
    ]
    with pytest.raises(ValueError, match="not found"):
        sqlite_db_real.upsert_config(
            "aba-agent",
            version=2,
            stage="published",
            guard=_guard(3, 1),
            projection={"name": "Must not publish"},
        )


def test_publishing_existing_draft_revalidates_stored_links(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "draft-child-for-publish", stage="draft")
    _create_component(sqlite_db_real, "parent-for-publish", component_type=ComponentType.TEAM)
    sqlite_db_real.upsert_config(
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
        sqlite_db_real.upsert_config(
            "parent-for-publish",
            version=2,
            stage="published",
            guard=_guard(2, 1),
            projection={"name": "Must remain draft"},
        )

    parent = sqlite_db_real.get_component("parent-for-publish")
    draft = sqlite_db_real.get_config("parent-for-publish", version=2)
    assert parent is not None
    assert draft is not None
    assert parent["current_version"] == 1
    assert draft["stage"] == "draft"


def test_guarded_publish_can_atomically_derive_and_persist_links(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "published-child-for-derived-link")
    _create_component(
        sqlite_db_real,
        "draft-parent-for-derived-link",
        component_type=ComponentType.TEAM,
        stage="draft",
    )

    published = sqlite_db_real.upsert_config(
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
    component = sqlite_db_real.get_component("draft-parent-for-derived-link")
    assert component is not None and component["current_version"] == 1
    links = sqlite_db_real.get_links("draft-parent-for-derived-link", 1)
    assert [(link["child_component_id"], link["child_version"]) for link in links] == [
        ("published-child-for-derived-link", 1)
    ]


def test_draft_config_with_inbound_pin_cannot_be_deleted(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "pinned-draft", stage="draft")
    _create_component(
        sqlite_db_real,
        "legacy-parent",
        component_type=ComponentType.TEAM,
    )

    # Simulate a legacy or externally inserted link to isolate the inbound-pin
    # deletion guard. New writes must reject links to unpublished children.
    links_table = sqlite_db_real._get_table(table_type="component_links", create_table_if_not_found=True)
    assert links_table is not None
    with sqlite_db_real.Session() as sess, sess.begin():
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

    with pytest.raises(ComponentDependencyError) as dependency:
        sqlite_db_real.delete_config(
            component_id="pinned-draft",
            version=1,
            guard=_guard(1, None),
        )

    assert dependency.value.component_id == "pinned-draft"
    assert dependency.value.version == 1
    assert sqlite_db_real.get_config("pinned-draft", version=1) is not None


def test_create_rejects_unpublished_child_pin_without_parent_rows(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "draft-child", stage="draft")

    with pytest.raises(ValueError, match="not published"):
        _create_component(
            sqlite_db_real,
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

    assert sqlite_db_real.get_component("invalid-parent", include_deleted=True) is None
    assert sqlite_db_real.get_config("invalid-parent", version=1) is None
    assert sqlite_db_real.get_links("invalid-parent", version=1) == []


def test_link_insert_failure_rolls_back_atomic_component_create(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "published-child")
    duplicate_link: Dict[str, object] = {
        "link_kind": "member",
        "link_key": "member_0",
        "child_component_id": "published-child",
        "child_version": 1,
        "position": 0,
        "meta": {"type": "agent"},
    }

    with pytest.raises(IntegrityError):
        _create_component(
            sqlite_db_real,
            "rolled-back-parent",
            component_type=ComponentType.TEAM,
            links=[duplicate_link, dict(duplicate_link)],
        )

    assert sqlite_db_real.get_component("rolled-back-parent", include_deleted=True) is None
    assert sqlite_db_real.get_config("rolled-back-parent", version=1) is None
    assert sqlite_db_real.get_links("rolled-back-parent", version=1) == []


def test_archive_is_dependency_safe_and_ignores_archived_parents(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "child-agent")
    _create_component(
        sqlite_db_real,
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

    with pytest.raises(ComponentDependencyError) as dependency:
        sqlite_db_real.delete_component(
            "child-agent",
            guard=_guard(1, 1),
            require_no_dependents=True,
        )

    assert dependency.value.component_id == "child-agent"
    assert sqlite_db_real.get_component("child-agent") is not None

    assert sqlite_db_real.delete_component(
        "parent-team",
        guard=_guard(1, 1),
        require_no_dependents=True,
    )
    assert sqlite_db_real.get_dependents("child-agent")
    assert sqlite_db_real.get_dependents("child-agent", active_parents_only=True) == []

    assert sqlite_db_real.delete_component(
        "child-agent",
        guard=_guard(1, 1),
        require_no_dependents=True,
    )
    assert sqlite_db_real.get_component("child-agent") is None
    archived_child = sqlite_db_real.get_component("child-agent", include_deleted=True)
    assert archived_child is not None
    assert archived_child["deleted_at"] is not None


def test_archived_component_id_remains_occupied(sqlite_db_real: SqliteDb) -> None:
    _create_component(sqlite_db_real, "occupied-agent")
    assert sqlite_db_real.delete_component(
        "occupied-agent",
        guard=_guard(1, 1),
        require_no_dependents=True,
        projection={
            "name": "Archived projection",
            "description": "Last published view",
            "metadata": {"release": 1},
        },
    )
    assert sqlite_db_real.delete_component("occupied-agent") is False
    with pytest.raises(ValueError, match="hard delete"):
        sqlite_db_real.delete_component(
            "occupied-agent",
            hard_delete=True,
            projection={"name": "Must not apply"},
        )

    with pytest.raises(ComponentAlreadyExistsError):
        _create_component(
            sqlite_db_real,
            "occupied-agent",
            name="Replacement",
            config={"instructions": "replacement"},
        )

    archived = sqlite_db_real.get_component("occupied-agent", include_deleted=True)
    assert archived is not None
    assert archived["name"] == "Archived projection"
    assert archived["description"] == "Last published view"
    assert archived["metadata"] == {"release": 1}
    assert archived["deleted_at"] is not None
