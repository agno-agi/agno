"""Unit tests for the revamped EntityMemoryStore.

Entity memory is AGENTIC-only: the agent records through four tools
(remember_about, link_entities, search_entities, forget) and there is no
extraction pass. These tests run offline against a recording fake db.
"""

import inspect
from typing import Any, Dict, List, Optional

import pytest

from agno.learn.config import EntityMemoryConfig, LearningMode
from agno.learn.stores.entity_memory import EntityMemoryStore


class RecordingLearningDb:
    """In-memory fake of the learnings table, keyed by learning_id."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self._clock = 0

    def get_learning(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        learning_type = kwargs.get("learning_type")
        entity_id = kwargs.get("entity_id")
        entity_type = kwargs.get("entity_type")
        namespace = kwargs.get("namespace")
        for row in self.rows.values():
            if (
                row.get("learning_type") == learning_type
                and row.get("entity_id") == entity_id
                and row.get("entity_type") == entity_type
                and row.get("namespace") == namespace
            ):
                return row
        return None

    def upsert_learning(self, id: str, **kwargs: Any) -> None:
        existing = self.rows.get(id, {})
        row = {**existing, **kwargs, "learning_id": id}
        self._clock += 1
        row["updated_at"] = self._clock
        self.rows[id] = row

    def get_learnings(self, **kwargs: Any) -> List[Dict[str, Any]]:
        learning_type = kwargs.get("learning_type")
        entity_id = kwargs.get("entity_id")
        entity_type = kwargs.get("entity_type")
        namespace = kwargs.get("namespace")
        limit = kwargs.get("limit")
        rows = [
            row
            for row in self.rows.values()
            if (learning_type is None or row.get("learning_type") == learning_type)
            and (entity_id is None or row.get("entity_id") == entity_id)
            and (entity_type is None or row.get("entity_type") == entity_type)
            and (namespace is None or row.get("namespace") == namespace)
        ]
        rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def delete_learning(self, id: str) -> bool:
        return self.rows.pop(id, None) is not None

    def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        import json

        limit = kwargs.pop("limit", None)
        kwargs.pop("workflow_id", None)
        kwargs.pop("session_id", None)
        kwargs.pop("agent_id", None)
        kwargs.pop("team_id", None)
        kwargs.pop("user_id", None)
        candidates = self.get_learnings(**kwargs)
        variants = {query.lower(), query.lower().replace(" ", "_"), query.lower().replace("_", " ")}
        rows = [row for row in candidates if any(v in json.dumps(row.get("content", {})).lower() for v in variants)]
        if limit is not None:
            rows = rows[:limit]
        return rows


@pytest.fixture
def db() -> RecordingLearningDb:
    return RecordingLearningDb()


@pytest.fixture
def store(db: RecordingLearningDb) -> EntityMemoryStore:
    return EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]


class TestAgenticOnly:
    def test_default_mode_is_agentic(self) -> None:
        assert EntityMemoryConfig().mode is LearningMode.AGENTIC

    @pytest.mark.parametrize("mode", [LearningMode.ALWAYS, LearningMode.PROPOSE, LearningMode.HITL])
    def test_non_agentic_mode_raises(self, mode: LearningMode) -> None:
        with pytest.raises(ValueError, match="AGENTIC-only"):
            EntityMemoryStore(config=EntityMemoryConfig(mode=mode))

    def test_extraction_api_is_gone(self, store: EntityMemoryStore) -> None:
        for name in (
            "extract_and_save",
            "aextract_and_save",
            "_get_extraction_tools",
            "_aget_extraction_tools",
            "_get_extraction_system_message",
        ):
            assert not hasattr(store, name)

    def test_process_is_a_noop(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.process(messages=[object()], user_id="user-1")
        assert db.rows == {}
        assert store.was_updated is False

    async def test_aprocess_is_a_noop(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        await store.aprocess(messages=[object()], user_id="user-1")
        assert db.rows == {}
        assert store.was_updated is False

    def test_machine_bool_input_builds_agentic_store(self, db: RecordingLearningDb) -> None:
        from agno.learn import LearningMachine

        machine = LearningMachine(db=db, entity_memory=True)  # type: ignore[arg-type]
        entity_store = machine.entity_memory_store
        assert entity_store is not None
        assert entity_store.config.mode is LearningMode.AGENTIC


class TestToolSurface:
    def test_sync_tools_are_the_four(self, store: EntityMemoryStore) -> None:
        tools = store.get_tools(user_id="user-1")
        assert [t.__name__ for t in tools] == ["remember_about", "link_entities", "search_entities", "forget"]
        assert all(not inspect.iscoroutinefunction(t) for t in tools)

    async def test_async_tools_are_the_four(self, store: EntityMemoryStore) -> None:
        tools = await store.aget_tools(user_id="user-1")
        assert [t.__name__ for t in tools] == ["remember_about", "link_entities", "search_entities", "forget"]
        assert all(inspect.iscoroutinefunction(t) for t in tools)

    def test_sync_and_async_docstrings_match(self, store: EntityMemoryStore) -> None:
        import asyncio

        sync_tools = store.get_tools()
        async_tools = asyncio.run(store.aget_tools())
        for sync_tool, async_tool in zip(sync_tools, async_tools):
            assert sync_tool.__doc__ == async_tool.__doc__
            assert sync_tool.__doc__  # never empty

    def test_tool_signatures_match_the_spec(self, store: EntityMemoryStore) -> None:
        tools = {t.__name__: t for t in store.get_tools()}
        assert list(inspect.signature(tools["remember_about"]).parameters) == [
            "entity",
            "entity_type",
            "description",
            "facts",
            "events",
            "note",
        ]
        assert list(inspect.signature(tools["link_entities"]).parameters) == ["entity", "relation", "related_entity"]
        assert list(inspect.signature(tools["search_entities"]).parameters) == ["query", "entity_type"]
        assert list(inspect.signature(tools["forget"]).parameters) == ["entity", "fact"]

    def test_tools_disabled_when_configured_off(self, db: RecordingLearningDb) -> None:
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, enable_agent_tools=False))  # type: ignore[arg-type]
        assert store.get_tools() == []


class TestRememberAbout:
    def test_creates_entity_with_slugified_id(self, store: EntityMemoryStore) -> None:
        message = store.remember_about(entity="Sarah Chen", entity_type="person", facts=["designs radar"])
        assert "person/sarah_chen" in message
        entity = store.get(entity_id="sarah_chen", entity_type="person")
        assert entity is not None
        assert entity.name == "Sarah Chen"
        assert [f["content"] for f in entity.facts] == ["designs radar"]

    def test_merges_into_existing_entity(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        store.remember_about(entity="radar", entity_type="project", events=["shipped v1"])
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None
        assert len(entity.facts) == 1
        assert len(entity.events) == 1

    def test_note_pointer_round_trips(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", note="notes/radar.md")
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None
        assert entity.properties["note"] == "notes/radar.md"
        # And it shows in search results
        result = store.search_entities(query="radar")
        assert "note: notes/radar.md" in result

    async def test_async_remember_about(self, store: EntityMemoryStore) -> None:
        message = await store.aremember_about(entity="Acme Corp", entity_type="company", facts=["fintech"])
        assert "company/acme_corp" in message
        entity = await store.aget(entity_id="acme_corp", entity_type="company")
        assert entity is not None

    def test_user_namespace_requires_user_id(self, db: RecordingLearningDb) -> None:
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))  # type: ignore[arg-type]
        message = store.remember_about(entity="radar", entity_type="project")
        assert "user_id" in message
        assert db.rows == {}


class TestLinkEntities:
    def test_edge_written_on_both_rows_with_far_end_type(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Sarah Chen", entity_type="person")
        store.remember_about(entity="radar", entity_type="project")
        message = store.link_entities(entity="Sarah Chen", relation="works_on", related_entity="radar")
        assert "person/sarah_chen" in message and "project/radar" in message

        sarah = store.get(entity_id="sarah_chen", entity_type="person")
        radar = store.get(entity_id="radar", entity_type="project")
        assert sarah is not None and radar is not None

        out_edge = sarah.relationships[0]
        assert out_edge["entity_id"] == "radar"
        assert out_edge["entity_type"] == "project"
        assert out_edge["relation"] == "works_on"
        assert out_edge["direction"] == "outgoing"

        in_edge = radar.relationships[0]
        assert in_edge["entity_id"] == "sarah_chen"
        assert in_edge["entity_type"] == "person"
        assert in_edge["relation"] == "works_on"
        assert in_edge["direction"] == "incoming"

    def test_unresolved_end_creates_minimal_unknown_entity(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.link_entities(entity="radar", relation="uses", related_entity="Postgres")
        postgres = store.get(entity_id="postgres", entity_type="unknown")
        assert postgres is not None
        assert postgres.relationships[0]["direction"] == "incoming"

    async def test_async_link_entities(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project")
        message = await store.alink_entities(entity="radar", relation="owned_by", related_entity="Acme")
        assert "Linked" in message


class TestSearchEntities:
    def test_query_matches_fact_content(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="company", facts=["uses PostgreSQL"])
        result = store.search_entities(query="postgresql")
        assert "Acme" in result

    def test_no_query_lists_by_recency(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="older", entity_type="project")
        store.remember_about(entity="newer", entity_type="project")
        result = store.search_entities()
        assert result.index("newer") < result.index("older")

    def test_no_match_reports_scan_scope(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        result = store.search_entities(query="nonexistent")
        assert "No entities matching" in result
        assert "namespace 'global'" in result

    def test_truncation_marker_on_many_facts(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=[f"fact number {i}" for i in range(19)])
        result = store.search_entities(query="radar")
        assert "(6 of 19 facts)" in result

    async def test_async_search_entities(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project")
        result = await store.asearch_entities(query="radar")
        assert "radar" in result


class TestForget:
    def test_archive_excluded_from_recall_but_searchable(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["shipped"])
        message = store.forget(entity="radar")
        assert "Archived project/radar" in message

        # Excluded from recall
        assert store.recall(entity_id="radar", entity_type="project") is None
        # Still reachable via explicit search, marked archived
        result = store.search_entities(query="radar")
        assert "(archived)" in result
        # Excluded from the listing path (recall-adjacent surfaces exclude archived)
        assert store.list_entities() == []

    def test_remember_revives_archived_entity(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.forget(entity="radar")
        message = store.remember_about(entity="radar", entity_type="project", facts=["back on"])
        assert "revived" in message
        assert store.recall(entity_id="radar", entity_type="project") is not None

    def test_forget_unknown_entity(self, store: EntityMemoryStore) -> None:
        assert "No entity found" in store.forget(entity="ghost")

    def test_exact_fact_match_retires(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["blocked on review", "db: Postgres"])
        message = store.forget(entity="radar", fact="Blocked on Review")
        assert "Retired fact" in message
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None
        live = entity.live_facts()
        assert [f["content"] for f in live] == ["db: Postgres"]
        retired = [f for f in entity.facts if f.get("superseded_at")]
        assert len(retired) == 1
        assert retired[0]["superseded_by"] == "forgotten"

    def test_single_containment_match_retires(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["blocked on security review"])
        message = store.forget(entity="radar", fact="security review")
        assert "Retired fact" in message

    def test_multiple_matches_retire_nothing(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["review is pending", "review was requested"])
        message = store.forget(entity="radar", fact="review")
        assert "Multiple facts" in message
        assert "review is pending" in message and "review was requested" in message
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None
        assert len(entity.live_facts()) == 2

    def test_zero_matches_returns_live_facts(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        message = store.forget(entity="radar", fact="something else entirely")
        assert "No matching fact on project/radar" in message
        assert "db: Postgres" in message

    async def test_async_forget_archives(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project")
        message = await store.aforget(entity="radar")
        assert "Archived" in message


class TestSearchRouting:
    def test_search_routes_through_search_learnings(self, db: RecordingLearningDb) -> None:
        calls: List[Dict[str, Any]] = []

        class SpyDb(RecordingLearningDb):
            def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
                calls.append({"query": query, **kwargs})
                return super().search_learnings(query, **kwargs)

        spy = SpyDb()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=spy))  # type: ignore[arg-type]
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        results = store.search(query="postgres")
        assert len(results) == 1
        assert calls and calls[0]["query"] == "postgres"
        assert calls[0]["learning_type"] == "entity_memory"
        assert calls[0]["namespace"] == "global"

    def test_search_crosses_slug_boundary_via_store(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Sarah Chen", entity_type="person", facts=["designs radar"])
        results = store.search(query="sarah chen")
        assert [e.entity_id for e in results] == ["sarah_chen"]

    def test_search_falls_back_on_not_implemented(self, caplog: pytest.LogCaptureFixture) -> None:
        class NoSearchDb(RecordingLearningDb):
            def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
                raise NotImplementedError

        db = NoSearchDb()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])

        import logging

        with caplog.at_level(logging.WARNING):
            results = store.search(query="postgres")
            store.search(query="postgres")

        assert [e.entity_id for e in results] == ["radar"]
        degraded = [r for r in caplog.records if "no search_learnings implementation" in r.getMessage()]
        assert len(degraded) == 1  # logged once, not per call

    def test_search_fails_loudly_when_backend_errors(self) -> None:
        class BrokenSearchDb(RecordingLearningDb):
            def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
                raise RuntimeError("dialect error")

        store = EntityMemoryStore(config=EntityMemoryConfig(db=BrokenSearchDb()))  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="dialect error"):
            store.search(query="anything")

    async def test_asearch_routes_and_falls_back(self, caplog: pytest.LogCaptureFixture) -> None:
        class NoSearchDb(RecordingLearningDb):
            def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
                raise NotImplementedError

        db = NoSearchDb()
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]
        await store.aremember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        results = await store.asearch(query="postgres")
        assert [e.entity_id for e in results] == ["radar"]

    def test_search_finds_match_outside_recent_window_with_sqlite(self, tmp_path) -> None:
        from agno.db.sqlite import SqliteDb

        sqlite_db = SqliteDb(db_file=str(tmp_path / "entities.db"))
        store = EntityMemoryStore(config=EntityMemoryConfig(db=sqlite_db))

        store.remember_about(entity="needle", entity_type="project", facts=["the rare zanzibar detail"])
        for i in range(60):
            sqlite_db.upsert_learning(
                id=f"entity_global_project_filler_{i}",
                learning_type="entity_memory",
                entity_id=f"filler_{i}",
                entity_type="project",
                namespace="global",
                content={"entity_id": f"filler_{i}", "entity_type": "project", "facts": []},
            )

        results = store.search(query="zanzibar", limit=5)
        assert [e.entity_id for e in results] == ["needle"]


class TestDataApi:
    def test_hard_delete(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="radar", entity_type="project")
        assert store.delete(entity_id="radar", entity_type="project") is True
        assert db.rows == {}
        assert store.delete(entity_id="radar", entity_type="project") is False

    async def test_async_hard_delete(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project")
        assert await store.adelete(entity_id="radar", entity_type="project") is True
