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


class _SleepyJudge:
    """Stands in for the supersession judge's provider round trip.

    The await is the point: it is the suspension that lets an assistant turn's
    gathered tool calls interleave inside a read-modify-write.
    """

    id = "sleepy-judge"

    def response(self, messages: Any, tools: Any = None, **kwargs: Any) -> None:
        return None

    async def aresponse(self, messages: Any, tools: Any = None, **kwargs: Any) -> None:
        import asyncio

        await asyncio.sleep(0.01)
        return None


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

    def test_store_config_namespace_wins_over_machine_default(self, db: RecordingLearningDb) -> None:
        # EntityMemoryConfig(namespace="ops") under a default machine must not
        # be silently overridden to "global" at the tool call sites.
        from agno.learn import LearningMachine

        machine = LearningMachine(db=db, entity_memory=EntityMemoryConfig(namespace="ops"))  # type: ignore[arg-type]
        tools = machine.get_tools(user_id="u1")
        remember = next(t for t in tools if t.__name__ == "remember_about")
        remember(entity="radar", entity_type="project")
        assert all(row.get("namespace") == "ops" for row in db.rows.values())

    def test_machine_namespace_reaches_default_configs(self, db: RecordingLearningDb) -> None:
        from agno.learn import LearningMachine

        machine = LearningMachine(db=db, namespace="team_west", entity_memory=True)  # type: ignore[arg-type]
        tools = machine.get_tools(user_id="u1")
        remember = next(t for t in tools if t.__name__ == "remember_about")
        remember(entity="radar", entity_type="project")
        assert all(row.get("namespace") == "team_west" for row in db.rows.values())


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

    def test_user_namespace_fails_closed_on_reads_and_forget(self, db: RecordingLearningDb) -> None:
        # Alice's private entity must not be readable or archivable without a user_id.
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, namespace="user"))  # type: ignore[arg-type]
        store.remember_about(entity="secret project", entity_type="project", facts=["acme deal"], user_id="alice")

        assert "user_id" in store.search_entities(query="acme")
        assert store.search(query="acme") == []
        assert store.list_entities() == []
        assert "user_id" in store.forget(entity="secret project")
        entity = store.get(entity_id="secret_project", entity_type="project", user_id="alice")
        assert entity is not None and entity.archived_at is None

    def test_blank_entity_name_is_rejected(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        assert "Entity name is required" in store.remember_about(entity="   ", entity_type="person")
        assert db.rows == {}


class TestResolution:
    def test_name_variants_merge_into_one_entity(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Sarah Chen", entity_type="person", facts=["designs radar"])
        store.remember_about(entity="sarah chen", entity_type="person", facts=["prefers async"])
        assert len(db.rows) == 1
        entity = store.get(entity_id="sarah_chen", entity_type="person")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["designs radar", "prefers async"]

    def test_type_drift_merges(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Sarah Chen", entity_type="person", facts=["designs radar"])
        store.remember_about(entity="Sarah Chen", entity_type="people", facts=["prefers async"])
        store.remember_about(entity="Sarah Chen", entity_type="Person")
        assert len(db.rows) == 1
        entity = store.get(entity_id="sarah_chen", entity_type="person")
        assert entity is not None
        assert len(entity.facts) == 2

    def test_type_is_normalized_on_create(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Acme", entity_type="Companies")
        assert store.get(entity_id="acme", entity_type="company") is not None

    def test_resolves_by_exact_name_when_id_differs(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # A row whose entity_id does not derive from its name (external writer).
        db.upsert_learning(
            id="entity_global_person_sc_001",
            learning_type="entity_memory",
            entity_id="sc_001",
            entity_type="person",
            namespace="global",
            content={"entity_id": "sc_001", "entity_type": "person", "name": "Sarah Chen", "facts": []},
        )
        store.remember_about(entity="Sarah Chen", entity_type="person", facts=["works at Acme"])
        assert len(db.rows) == 1  # merged, not duplicated
        entity = store.get(entity_id="sc_001", entity_type="person")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["works at Acme"]

    def test_resolves_by_alias(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        db.upsert_learning(
            id="entity_global_project_radar",
            learning_type="entity_memory",
            entity_id="radar",
            entity_type="project",
            namespace="global",
            content={
                "entity_id": "radar",
                "entity_type": "project",
                "name": "radar",
                "aliases": ["The Radar Initiative"],
                "facts": [],
            },
        )
        store.remember_about(entity="the radar initiative", entity_type="project", facts=["shipped v1"])
        assert len(db.rows) == 1
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["shipped v1"]

    def test_incoming_name_variant_recorded_as_alias(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        db.upsert_learning(
            id="entity_global_person_sc_001",
            learning_type="entity_memory",
            entity_id="sc_001",
            entity_type="person",
            namespace="global",
            content={"entity_id": "sc_001", "entity_type": "person", "name": "Sarah Chen", "facts": []},
        )
        # Resolves via name match; a genuinely different surface form would be an alias,
        # but the same normalized name must NOT be duplicated in.
        store.remember_about(entity="SARAH  CHEN", entity_type="person")
        entity = store.get(entity_id="sc_001", entity_type="person")
        assert entity is not None
        assert entity.aliases == []

    def test_unknown_type_upgraded_by_later_remember(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.link_entities(entity="radar", relation="uses", related_entity="Postgres")
        assert store.get(entity_id="postgres", entity_type="unknown") is not None

        store.remember_about(entity="Postgres", entity_type="system", facts=["v16 in prod"])

        upgraded = store.get(entity_id="postgres", entity_type="system")
        assert upgraded is not None
        assert [f["content"] for f in upgraded.facts] == ["v16 in prod"]
        assert upgraded.relationships  # the edge written while unknown survives
        # The old-typed row is gone
        assert store.get(entity_id="postgres", entity_type="unknown") is None

    def test_explicit_aliases_write_and_resolve(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # The alias path on remember_about: an explicit alias is written, then
        # a later write arriving under that alias resolves to the same entity.
        store.remember_about(entity="Sarah Chen", entity_type="person", aliases=["SC", "Sarah from Design"])
        entity = store.get(entity_id="sarah_chen", entity_type="person")
        assert entity is not None
        assert entity.aliases == ["SC", "Sarah from Design"]

        store.remember_about(entity="Sarah from Design", entity_type="person", facts=["owns radar UX"])
        assert len(db.rows) == 1  # resolved via the alias, not duplicated
        entity = store.get(entity_id="sarah_chen", entity_type="person")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["owns radar UX"]

    def test_no_fuzzy_merge(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # "Sarah" must NOT merge into "Sarah Chen" - a wrong merge has no unmerge.
        store.remember_about(entity="Sarah Chen", entity_type="person")
        store.remember_about(entity="Sarah", entity_type="person")
        assert len(db.rows) == 2

    def test_archived_entities_do_not_push_live_ones_out_of_the_directory(self, db: RecordingLearningDb) -> None:
        """Archived rows are dropped after the fetch, so enough recent archives
        used to shorten the directory - while the block still told the model
        the directory was the full index and an absent entity was not known."""
        store = EntityMemoryStore(
            config=EntityMemoryConfig(db=db, max_entities_in_directory=5)  # type: ignore[arg-type]
        )
        for i in range(5):
            store.remember_about(entity=f"live{i}", entity_type="project", facts=["x"])
        for i in range(20):
            store.remember_about(entity=f"dead{i}", entity_type="project", facts=["x"])
            store.forget(entity=f"dead{i}")

        data = store.recall(message="where do things stand?")
        assert data is not None
        assert sorted(e.entity_id for e in data["directory"]) == ["live0", "live1", "live2", "live3", "live4"]

    async def test_same_turn_tool_calls_do_not_overwrite_each_other(self, db: RecordingLearningDb) -> None:
        """An assistant turn's tool calls run concurrently (models/base.py
        gathers them), and every entity write is a read-modify-write over the
        whole row. Whatever suspends in the middle - the judge's provider call,
        or any await on an async db - must not cost a sibling its write."""
        import asyncio

        store = EntityMemoryStore(
            config=EntityMemoryConfig(db=db, model=_SleepyJudge())  # type: ignore[arg-type]
        )
        await store.aremember_about(entity="radar", entity_type="project", facts=["db: Postgres"])

        await asyncio.gather(
            store.aremember_about(entity="radar", entity_type="project", facts=["owner: Sarah Chen"]),
            store.aremember_about(entity="radar", entity_type="project", events=["shipped v1"]),
            store.alink_entities(entity="radar", relation="uses", related_entity="Postgres"),
        )

        entity = await store.aget(entity_id="radar", entity_type="project")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["db: Postgres", "owner: Sarah Chen"]
        assert [e["content"] for e in entity.events] == ["shipped v1"]
        assert [r["entity_id"] for r in entity.relationships] == ["postgres"]

    async def test_same_turn_calls_do_not_split_a_new_entity(self, db: RecordingLearningDb) -> None:
        """remember_about mints person/sarah_chen while link_entities mints the
        unknown/ placeholder; concurrently, both used to survive as two rows.

        The fake db never suspends, so the judge's await is what opens the
        window - the store needs a model for this to discriminate.
        """
        import asyncio

        store = EntityMemoryStore(
            config=EntityMemoryConfig(db=db, model=_SleepyJudge())  # type: ignore[arg-type]
        )
        await store.aremember_about(entity="Sarah Chen", entity_type="person", facts=["joined radar"])
        await asyncio.gather(
            store.aremember_about(entity="Sarah Chen", entity_type="person", facts=["leads radar"]),
            store.alink_entities(entity="Sarah Chen", relation="works_on", related_entity="apollo"),
        )
        assert sorted(r["entity_id"] for r in db.rows.values()) == ["apollo", "sarah_chen"]
        entity = await store.aget(entity_id="sarah_chen", entity_type="person")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["joined radar", "leads radar"]
        assert [r["entity_id"] for r in entity.relationships] == ["apollo"]

    async def test_same_fact_twice_in_one_turn_is_stored_once(self, db: RecordingLearningDb) -> None:
        """The duplicate check has to run against the row the merge lands on.

        Judged against the pre-lock snapshot, two siblings carrying the same
        sentence both called it novel and both appended it.
        """
        import asyncio

        store = EntityMemoryStore(
            config=EntityMemoryConfig(db=db, model=_SleepyJudge())  # type: ignore[arg-type]
        )
        await store.aremember_about(entity="Sarah Chen", entity_type="person", facts=["joined radar in March"])
        await asyncio.gather(
            store.aremember_about(entity="Sarah Chen", entity_type="person", facts=["Sarah now leads radar"]),
            store.aremember_about(entity="Sarah Chen", entity_type="person", facts=["Sarah now leads radar"]),
        )
        entity = await store.aget(entity_id="sarah_chen", entity_type="person")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["joined radar in March", "Sarah now leads radar"]

    def test_blank_description_and_note_do_not_wipe_stored_values(self, store: EntityMemoryStore) -> None:
        # The model fills unused optional arguments with ""; the tool surface
        # has no way to CLEAR a description, so "" cannot mean "clear it".
        store.remember_about(
            entity="radar", entity_type="project", description="The ingest rewrite", note="notes/radar.md"
        )
        store.remember_about(entity="radar", entity_type="project", description="", note="", facts=["shipped"])
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None
        assert entity.description == "The ingest rewrite"
        assert (entity.properties or {}).get("note") == "notes/radar.md"

    def test_write_lock_outside_a_running_loop(self, store: EntityMemoryStore) -> None:
        # The loop-keyed cache is weak, and None is not weak-referenceable.
        assert store._write_lock() is not None

    def test_accented_names_do_not_collide(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # Muller and Moller are two people; a slug that drops the accented
        # letter made them one, and there is no unmerge.
        store.remember_about(entity="Anna Müller", entity_type="person", facts=["office: Berlin"])
        store.remember_about(entity="Anna Möller", entity_type="person", facts=["office: Hamburg"])
        assert len(db.rows) == 2

    def test_accent_folding_merges_the_same_person(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="Sofía Muñoz", entity_type="person", facts=["office: Madrid"])
        store.remember_about(entity="Sofia Munoz", entity_type="person", facts=["team: platform"])
        assert len(db.rows) == 1
        entity = store.get(entity_id="sofia_munoz", entity_type="person")
        assert entity is not None
        assert len(entity.facts) == 2

    def test_non_latin_names_keep_their_own_id(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # Nothing to fold: the lowered name is the id, and two of them stay two.
        store.remember_about(entity="李明", entity_type="person", facts=["office: Shanghai"])
        store.remember_about(entity="Дмитрий", entity_type="person", facts=["office: Riga"])
        assert len(db.rows) == 2

    def test_same_name_different_canonical_types_stay_separate(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # The project Harbor and the company Harbor are different things.
        store.remember_about(entity="Harbor", entity_type="project", facts=["db: Postgres"])
        store.remember_about(entity="Harbor", entity_type="company", facts=["HQ: Lisbon"])
        assert len(db.rows) == 2
        project = store.get(entity_id="harbor", entity_type="project")
        company = store.get(entity_id="harbor", entity_type="company")
        assert project is not None and company is not None
        assert [f["content"] for f in project.facts] == ["db: Postgres"]
        assert [f["content"] for f in company.facts] == ["HQ: Lisbon"]

    def test_name_match_across_canonical_types_stays_separate(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # The name rung must not cross canonical types either.
        db.upsert_learning(
            id="entity_global_project_rdr_001",
            learning_type="entity_memory",
            entity_id="rdr_001",
            entity_type="project",
            namespace="global",
            content={"entity_id": "rdr_001", "entity_type": "project", "name": "Radar", "facts": []},
        )
        store.remember_about(entity="Radar", entity_type="person", facts=["role: staff engineer"])
        assert len(db.rows) == 2

    def test_an_ambiguous_name_changes_nothing(self, store: EntityMemoryStore) -> None:
        """link_entities and forget carry no entity_type, so a shared name
        would silently pick one row and strand the other."""
        store.remember_about(entity="Harbor", entity_type="project", facts=["the ingest rewrite"])
        store.remember_about(entity="Harbor", entity_type="company", facts=["HQ Lisbon"])

        for message in (
            store.link_entities(entity="Harbor", relation="uses", related_entity="Postgres"),
            store.forget(entity="Harbor"),
        ):
            assert "matches more than one entity" in message
            assert "project/Harbor" in message and "company/Harbor" in message

        project = store.get(entity_id="harbor", entity_type="project")
        company = store.get(entity_id="harbor", entity_type="company")
        assert project is not None and company is not None
        assert project.relationships == [] and not getattr(company, "archived_at", None)

    def test_a_qualified_name_reaches_either_entity(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Harbor", entity_type="project", facts=["the ingest rewrite"])
        store.remember_about(entity="Harbor", entity_type="company", facts=["HQ Lisbon"])

        assert "project/harbor" in store.link_entities(
            entity="project/Harbor", relation="uses", related_entity="Postgres"
        )
        assert "Archived company/harbor" in store.forget(entity="company/Harbor")

        project = store.get(entity_id="harbor", entity_type="project")
        company = store.get(entity_id="harbor", entity_type="company")
        assert project is not None and company is not None
        assert [r["entity_id"] for r in project.relationships] == ["postgres"]
        assert getattr(company, "archived_at", None)
        assert not getattr(project, "archived_at", None)

    def test_a_slash_in_a_name_is_part_of_the_name(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        """A prefix only qualifies when it names a stored type.

        Reading every slash as "type/name" sent resolution to a key the write
        path never used, so the second write created nothing and clobbered the
        first entity's facts.
        """
        store.remember_about(entity="AC/DC", entity_type="company", facts=["a band"])
        store.remember_about(entity="AC/DC", entity_type="company", facts=["still a band"])
        assert len(db.rows) == 1
        entity = store.get(entity_id="ac_dc", entity_type="company")
        assert entity is not None
        assert [f["content"] for f in entity.facts] == ["a band", "still a band"]

    async def test_async_ambiguous_name_changes_nothing(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="Harbor", entity_type="project")
        await store.aremember_about(entity="Harbor", entity_type="company")
        assert "matches more than one entity" in await store.aforget(entity="Harbor")
        assert "matches more than one entity" in await store.alink_entities(
            entity="Harbor", relation="uses", related_entity="Postgres"
        )

    def test_a_stale_relationship_can_be_retired(self, store: EntityMemoryStore) -> None:
        """A corrected link had no retirement path: stating the new one left
        both edges rendering, undated, forever."""
        store.remember_about(entity="quill", entity_type="project")
        store.link_entities(entity="quill", relation="written_in", related_entity="Rust")
        store.link_entities(entity="quill", relation="written_in", related_entity="Go")

        message = store.forget(entity="quill", fact="written_in -> Rust")
        assert "Removed relationship" in message
        quill = store.get(entity_id="quill", entity_type="project")
        assert quill is not None
        assert [(r["relation"], r["entity_id"]) for r in quill.relationships] == [("written_in", "go")]
        # the reciprocal edge goes too, so the graph does not go one-sided
        rust = store.get(entity_id="rust", entity_type="unknown")
        assert rust is not None
        assert rust.relationships == []

    def test_an_ambiguous_relationship_retires_nothing(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="quill", entity_type="project")
        store.link_entities(entity="quill", relation="written_in", related_entity="Rust")
        store.link_entities(entity="quill", relation="written_in", related_entity="Go")

        message = store.forget(entity="quill", fact="written_in")
        assert "Multiple relationships" in message
        quill = store.get(entity_id="quill", entity_type="project")
        assert quill is not None
        assert len(quill.relationships) == 2

    async def test_async_relationship_retirement(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="tom", entity_type="person")
        await store.alink_entities(entity="tom", relation="works_on", related_entity="radar")
        assert "Removed relationship" in await store.aforget(entity="tom", fact="works_on -> radar")
        tom = await store.aget(entity_id="tom", entity_type="person")
        assert tom is not None
        assert tom.relationships == []

    def test_mixed_script_names_do_not_merge(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        # Dropping the non-Latin half keyed "李 Ming" to `ming`.
        store.remember_about(entity="李 Ming", entity_type="person", facts=["office: Shanghai"])
        store.remember_about(entity="Ming", entity_type="person", facts=["office: London"])
        assert len(db.rows) == 2

    def test_two_named_types_are_two_entities(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        """Only the ``unknown`` placeholder merges across types.

        Restricting the split to a canonical list left the types models
        actually coin - team, framework, service - merging into whatever row
        happened to share the name, which has no unmerge.
        """
        store.remember_about(entity="Atlas", entity_type="system", facts=["the ingest system"])
        message = store.remember_about(entity="Atlas", entity_type="team", facts=["the platform team"])
        assert len(db.rows) == 2
        # ...and the write says the sibling exists, so the model can correct itself.
        assert "system/atlas already exists under this name" in message

    def test_free_form_type_does_not_swallow_a_named_one(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        store.remember_about(entity="Sarah Chen", entity_type="engineer", facts=["designs radar"])
        store.remember_about(entity="Sarah Chen", entity_type="person", facts=["prefers async"])
        assert len(db.rows) == 2

    def test_link_placeholder_still_upgrades_to_a_real_type(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        # link_entities mints entity_type="unknown"; describing it later must merge.
        store.link_entities(entity="harbor", relation="uses", related_entity="Postgres")
        store.remember_about(entity="Postgres", entity_type="system", facts=["v16"])
        assert sorted(r["entity_type"] for r in db.rows.values()) == ["system", "unknown"]

    async def test_async_same_name_different_canonical_types_stay_separate(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        await store.aremember_about(entity="Harbor", entity_type="project", facts=["db: Postgres"])
        await store.aremember_about(entity="Harbor", entity_type="company", facts=["HQ: Lisbon"])
        assert len(db.rows) == 2


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

    def test_self_link_is_rejected(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        message = store.link_entities(entity="radar", relation="relates_to", related_entity="Radar")
        assert "itself" in message
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None and entity.relationships == []


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
        assert "(newest 6 of 19 facts)" in result
        # The NEWEST facts are shown, not the oldest
        assert "fact number 18" in result and "fact number 0" not in result

    async def test_async_search_entities(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project")
        result = await store.asearch_entities(query="radar")
        assert "radar" in result

    def test_blank_entity_type_is_no_filter(self, store: EntityMemoryStore) -> None:
        # A strict tool schema has no "absent", so models send "" for the
        # optional argument they did not mean to use. Filtering on it would
        # answer "not found" while holding the entity.
        store.remember_about(entity="Meridian", entity_type="project", facts=["status: in migration"])
        assert "Meridian" in store.search_entities(query="Meridian", entity_type="")
        assert "Meridian" in store.search_entities(query="Meridian", entity_type="   ")

    def test_blank_query_still_lists(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Meridian", entity_type="project")
        assert "Meridian" in store.search_entities(query="   ", entity_type="")

    async def test_async_blank_entity_type_is_no_filter(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="Meridian", entity_type="project", facts=["status: in migration"])
        assert "Meridian" in await store.asearch_entities(query="Meridian", entity_type="")
        assert "Meridian" in await store.asearch_entities(query="   ", entity_type="")


class TestForget:
    def test_archive_excluded_from_recall_but_searchable(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["shipped"])
        message = store.forget(entity="radar")
        assert "Archived project/radar" in message

        # Excluded from recall: neither expanded nor in the directory
        recalled = store.recall(entity_id="radar", entity_type="project")
        assert recalled is not None
        assert recalled["directory"] == [] and recalled["entities"] == []
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
        recalled = store.recall(entity_id="radar", entity_type="project")
        assert recalled is not None and len(recalled["entities"]) == 1

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
        calls.clear()
        results = store.search(query="postgres")
        assert len(results) == 1
        assert calls and calls[-1]["query"] == "postgres"
        assert calls[-1]["learning_type"] == "entity_memory"
        assert calls[-1]["namespace"] == "global"

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

    def test_json_key_names_do_not_match(self, store: EntityMemoryStore) -> None:
        # The db-side ILIKE sees the whole serialized document; the store must
        # verify hits against values only, or "facts"/"name" match every row.
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        for key_name in ("facts", "name", "entity_id", "properties", "relationships"):
            assert store.search(query=key_name) == [], key_name
        # ...but a value containing such a word still matches
        store.remember_about(entity="naming service", entity_type="system")
        assert [e.entity_id for e in store.search(query="naming")] == ["naming_service"]

    def test_attribute_error_inside_backend_is_not_masked(self) -> None:
        # A backend that HAS search_learnings but raises AttributeError inside
        # it is a real bug, not a missing implementation - it must propagate.
        class BuggyDb(RecordingLearningDb):
            def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
                raise AttributeError("'NoneType' object has no attribute 'client'")

        store = EntityMemoryStore(config=EntityMemoryConfig(db=BuggyDb()))  # type: ignore[arg-type]
        with pytest.raises(AttributeError, match="client"):
            store.search(query="anything")

    def test_archived_rows_do_not_crowd_out_live_hits(self, store: EntityMemoryStore) -> None:
        for i in range(3):
            store.remember_about(entity=f"live topic {i}", entity_type="project", facts=["about postgres"])
        for i in range(15):
            store.remember_about(entity=f"dead topic {i}", entity_type="project", facts=["about postgres"])
            store.forget(entity=f"dead topic {i}")

        results = store.search(query="postgres", limit=10)
        assert len(results) == 3
        assert all(e.archived_at is None for e in results)

    async def test_asearch_awaits_async_base_db(self) -> None:
        from agno.db.base import AsyncBaseDb

        inner = RecordingLearningDb()
        calls: List[str] = []

        class FakeAsyncDb(AsyncBaseDb):
            def __init__(self) -> None:
                pass

            async def get_learning(self, **kwargs: Any) -> Any:
                return inner.get_learning(**kwargs)

            async def upsert_learning(self, **kwargs: Any) -> None:
                inner.upsert_learning(**kwargs)

            async def get_learnings(self, **kwargs: Any) -> Any:
                return inner.get_learnings(**kwargs)

            async def search_learnings(self, query: str, **kwargs: Any) -> Any:
                calls.append(query)
                return inner.search_learnings(query, **kwargs)

        FakeAsyncDb.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]
        store = EntityMemoryStore(config=EntityMemoryConfig(db=FakeAsyncDb()))
        await store.aremember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        results = await store.asearch(query="postgres")
        assert [e.entity_id for e in results] == ["radar"]
        assert "postgres" in calls  # the awaited AsyncBaseDb branch really ran

    def test_sync_call_with_async_db_refuses_instead_of_type_error(self) -> None:
        from agno.db.base import AsyncBaseDb

        class FakeAsyncDb(AsyncBaseDb):
            def __init__(self) -> None:
                pass

        FakeAsyncDb.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]
        store = EntityMemoryStore(config=EntityMemoryConfig(db=FakeAsyncDb()))
        assert store.search(query="anything") == []
        assert store.list_entities() == []
        assert "Failed" in store.remember_about(entity="radar", entity_type="project")

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


class TestRenderingAndDirectory:
    def test_rendering_is_bounded_and_honest(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=[f"fact number {i}" for i in range(200)])
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None

        text = entity.get_context_text(max_facts=10, max_events=5)
        assert "(newest 10 of 200 facts)" in text
        assert text.count("fact number") == 10
        # The NEWEST facts render - showing the oldest slice would date-stamp
        # stale state as current
        assert "fact number 199" in text and "fact number 0 " not in text
        # Facts render with as-of dates
        assert "(as of 20" in text

    def test_events_render_last_n_with_marker(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", events=[f"event {i}" for i in range(9)])
        entity = store.get(entity_id="radar", entity_type="project")
        assert entity is not None
        text = entity.get_context_text(max_facts=10, max_events=3)
        assert "(last 3 of 9 events)" in text
        assert "event 8" in text and "event 0" not in text

    def test_directory_always_in_recall_and_context(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.remember_about(entity="Sarah Chen", entity_type="person")

        # No keyed lookup: recall still returns the directory
        recalled = store.recall()
        assert recalled is not None
        assert [e.entity_id for e in recalled["directory"]] == ["sarah_chen", "radar"]
        assert recalled["entities"] == []

        context = store.build_context(data=recalled)
        assert "Entity directory" in context
        assert "- Sarah Chen (person)" in context
        assert "- radar (project)" in context
        assert "not listed there is not known" in context

    def test_directory_excludes_archived(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.remember_about(entity="dead project", entity_type="project")
        store.forget(entity="dead project")

        recalled = store.recall()
        assert recalled is not None
        assert [e.entity_id for e in recalled["directory"]] == ["radar"]

    def test_context_caps_expanded_entities(self, db: RecordingLearningDb) -> None:
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, max_entities_in_context=2))  # type: ignore[arg-type]
        entities = []
        for i in range(4):
            store.remember_about(entity=f"proj {i}", entity_type="project", facts=[f"about {i}"])
            entities.append(store.get(entity_id=f"proj_{i}", entity_type="project"))

        context = store.build_context(data={"directory": entities, "entities": entities})
        # Directory lists all four; only two expand
        assert context.count("- proj ") == 4
        assert context.count("Facts:") == 2

    def test_empty_store_splits_guidance_and_data(self, store: EntityMemoryStore) -> None:
        # Guidance (the four tools) lives in instructions(); build_context is data only.
        context = store.build_context(data=store.recall())
        assert "No entities recorded yet" in context
        assert "remember_about" not in context

        guidance = store.instructions()
        for tool in ("remember_about", "link_entities", "search_entities", "forget"):
            assert tool in guidance

    def test_one_hop_link_names_render_on_recall(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.remember_about(entity="Sarah Chen", entity_type="person")
        store.link_entities(entity="Sarah Chen", relation="works_on", related_entity="radar")

        recalled = store.recall(entity_id="radar", entity_type="project")
        assert recalled is not None
        assert recalled["related_names"]["sarah_chen"] == "Sarah Chen"

        context = store.build_context(data=recalled)
        # The edge renders the far end's display NAME, not its slug
        assert "works_on <- Sarah Chen" in context

    def test_one_hop_names_resolve_beyond_the_directory(self, db: RecordingLearningDb) -> None:
        # Far end outside the directory cap still resolves via a bounded keyed lookup.
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, max_entities_in_directory=1))  # type: ignore[arg-type]
        store.remember_about(entity="Sarah Chen", entity_type="person")
        store.remember_about(entity="radar", entity_type="project")
        store.link_entities(entity="radar", relation="designed_by", related_entity="Sarah Chen")
        store.remember_about(entity="newest thing", entity_type="project")  # crowds the 1-slot directory

        recalled = store.recall(entity_id="radar", entity_type="project")
        assert recalled is not None
        # recall fetches one row beyond the cap to detect truncation; the render caps at 1
        context = store.build_context(data=recalled)
        assert context.count("\n- ") >= 1
        assert "most recently updated entities; more exist" in context
        assert recalled["related_names"].get("sarah_chen") == "Sarah Chen"

    async def test_arecall_matches_recall(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project")
        sync_result = store.recall()
        async_result = await store.arecall()
        assert sync_result is not None and async_result is not None
        assert [e.entity_id for e in sync_result["directory"]] == [e.entity_id for e in async_result["directory"]]


class TestDataApi:
    def test_hard_delete(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
        store.remember_about(entity="radar", entity_type="project")
        assert store.delete(entity_id="radar", entity_type="project") is True
        assert db.rows == {}
        assert store.delete(entity_id="radar", entity_type="project") is False

    async def test_async_hard_delete(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project")
        assert await store.adelete(entity_id="radar", entity_type="project") is True


class TestSearchWindowExhaustion:
    """The db-side LIKE matches key names, so ordinary words match every row.

    Any finite ladder just moves the threshold at which a real, older match
    becomes unreachable; the window has to run out with the backend.
    """

    def test_a_real_match_survives_hundreds_of_key_name_false_positives(self, tmp_path) -> None:
        import time

        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "crowd.db"))
        store = EntityMemoryStore(
            config=EntityMemoryConfig(db=db, mode=LearningMode.AGENTIC, namespace="global")  # type: ignore[arg-type]
        )
        store.remember_about(
            entity="target", entity_type="project", facts=["the content marker lives here"], namespace="global"
        )
        time.sleep(1.1)  # so ORDER BY updated_at DESC really ranks the fillers first
        for i in range(500):
            store.remember_about(entity=f"other{i}", entity_type="project", facts=["x"], namespace="global")

        # "content" is a JSON key on every row and a value on exactly one
        hits = store.search(query="content", namespace="global", limit=10)
        assert [e.entity_id for e in hits] == ["target"]

    def test_mixed_case_unicode_in_a_fact_value_is_reachable(self, tmp_path) -> None:
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "unicode.db"))
        store = EntityMemoryStore(
            config=EntityMemoryConfig(db=db, mode=LearningMode.AGENTIC, namespace="global")  # type: ignore[arg-type]
        )
        store.remember_about(entity="Alpha", entity_type="project", facts=["Ος"], namespace="global")
        store.remember_about(entity="Cafe", entity_type="company", facts=["Café Noir"], namespace="global")

        for query in ("Ος", "ΟΣ", "ος", "οσ"):
            assert [e.entity_id for e in store.search(query=query, namespace="global")] == ["alpha"], query
        for query in ("café", "CAFÉ", "Café"):
            assert [e.entity_id for e in store.search(query=query, namespace="global")] == ["cafe"], query


class TestRetirementReachesEveryStore:
    """forget is the only retirement path the four-tool surface has.

    Each rung below had no route at all: a retracted event could not be
    removed (the agent archived whole people to suppress one), and an edge
    could not be named the way the context block renders it.
    """

    def test_an_event_can_be_retired(self, store: EntityMemoryStore) -> None:
        store.remember_about(
            entity="Tom",
            entity_type="person",
            facts=["works in infra"],
            events=["heard he is leaving for a competitor", "shipped the migration"],
        )
        assert "Retired event" in store.forget(entity="Tom", fact="heard he is leaving for a competitor")

        tom = store.get(entity_id="tom", entity_type="person")
        assert tom is not None
        assert [e["content"] for e in tom.events] == ["shipped the migration"]
        # the facts survive, and the entity was not archived to suppress it
        assert [f["content"] for f in tom.live_facts()] == ["works in infra"]
        assert not getattr(tom, "archived_at", None)

    def test_an_ambiguous_event_retires_nothing(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Tom", entity_type="person", events=["review passed", "review passed again"])
        assert "Multiple events" in store.forget(entity="Tom", fact="review")
        tom = store.get(entity_id="tom", entity_type="person")
        assert tom is not None and len(tom.events) == 2

    def test_an_edge_retires_by_the_name_the_model_is_shown(self, store: EntityMemoryStore) -> None:
        # The block renders the far end's display name; the edge stores a slug.
        for form in ("owned_by -> Sarah Chen", "owned_by -> sarah_chen", "Sarah Chen"):
            store.remember_about(entity="Sarah Chen", entity_type="person")
            store.remember_about(entity="radar", entity_type="project")
            store.link_entities(entity="radar", relation="owned_by", related_entity="Sarah Chen")
            assert "Removed relationship" in store.forget(entity="radar", fact=form), form

    async def test_async_event_retirement(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="Tom", entity_type="person", events=["a rumour"])
        assert "Retired event" in await store.aforget(entity="Tom", fact="a rumour")


class TestQualifiedNameOnRememberAbout:
    def test_remember_about_reads_the_form_the_other_tools_teach(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        """The refusals and docstrings teach "project/Harbor"; slugging it
        whole minted project/project_harbor and stranded the correction."""
        store.remember_about(entity="Harbor", entity_type="project", facts=["the ingest rewrite"])
        store.remember_about(entity="Harbor", entity_type="company", facts=["HQ Lisbon"])

        message = store.remember_about(entity="project/Harbor", entity_type="project", facts=["status: shipped"])
        assert "project/harbor" in message
        assert len(db.rows) == 2
        project = store.get(entity_id="harbor", entity_type="project")
        assert project is not None
        assert [f["content"] for f in project.facts] == ["the ingest rewrite", "status: shipped"]

    async def test_async_remember_about_reads_the_qualified_form(
        self, store: EntityMemoryStore, db: RecordingLearningDb
    ) -> None:
        await store.aremember_about(entity="Harbor", entity_type="project")
        await store.aremember_about(entity="Harbor", entity_type="company")
        message = await store.aremember_about(entity="project/Harbor", entity_type="project", facts=["shipped"])
        assert "project/harbor" in message
        assert len(db.rows) == 2


class TestEdgesAreIdempotent:
    """Models re-assert links they already know.

    An appended duplicate could not be retired: forget listed byte-identical
    candidates no wording could tell apart, while the far side's detach
    removed every copy - so the graph went one-sided and stayed that way.
    """

    def test_relinking_does_not_double_the_edge(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.remember_about(entity="Sarah Chen", entity_type="person")
        for _ in range(3):
            store.link_entities(entity="radar", relation="owned_by", related_entity="Sarah Chen")

        radar = store.get(entity_id="radar", entity_type="project")
        sarah = store.get(entity_id="sarah_chen", entity_type="person")
        assert radar is not None and sarah is not None
        assert len(radar.relationships) == 1
        assert len(sarah.relationships) == 1
        assert "Removed relationship" in store.forget(entity="radar", fact="owned_by -> Sarah Chen")

    def test_a_different_relation_to_the_same_target_stays_distinct(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.remember_about(entity="Sarah Chen", entity_type="person")
        store.link_entities(entity="radar", relation="owned_by", related_entity="Sarah Chen")
        store.link_entities(entity="radar", relation="designed_by", related_entity="Sarah Chen")

        radar = store.get(entity_id="radar", entity_type="project")
        assert radar is not None and len(radar.relationships) == 2
        # ambiguous by target alone, and correctly refused
        assert "Multiple relationships" in store.forget(entity="radar", fact="Sarah Chen")

    def test_legacy_duplicate_edges_can_still_be_retired(self, store: EntityMemoryStore) -> None:
        # A row written before add_relationship deduped carries exact copies.
        store.remember_about(entity="radar", entity_type="project")
        store.remember_about(entity="Sarah Chen", entity_type="person")
        store.link_entities(entity="radar", relation="owned_by", related_entity="Sarah Chen")
        radar = store.get(entity_id="radar", entity_type="project")
        assert radar is not None
        radar.relationships.append(dict(radar.relationships[0], id="dupe1234"))
        store._save_entity(entity=radar, user_id=None, agent_id=None, team_id=None, namespace="global")

        assert "Removed relationship" in store.forget(entity="radar", fact="owned_by -> Sarah Chen")
        radar = store.get(entity_id="radar", entity_type="project")
        assert radar is not None and radar.relationships == []


class TestEdgeAndEventIdentity:
    """The duplicate class @kausmeows found on edges, generalised.

    entity_type is part of an edge's identity - project/Harbor and
    company/Harbor share a slug - and events had the same append-forever,
    retire-one-of-many shape edges did.
    """

    def test_two_same_named_entities_keep_separate_edges(self, store: EntityMemoryStore) -> None:
        for entity_type in ("project", "company"):
            store.remember_about(entity="Harbor", entity_type=entity_type)
        store.remember_about(entity="Alice", entity_type="person")
        store.link_entities(entity="project/Harbor", relation="managed_by", related_entity="Alice")
        store.link_entities(entity="company/Harbor", relation="managed_by", related_entity="Alice")

        alice = store.get(entity_id="alice", entity_type="person")
        assert alice is not None
        assert sorted(r["entity_type"] for r in alice.relationships) == ["company", "project"]

        # retiring one must not strip the other's reciprocal
        store.forget(entity="project/Harbor", fact="managed_by -> Alice")
        alice = store.get(entity_id="alice", entity_type="person")
        assert alice is not None
        assert [r["entity_type"] for r in alice.relationships] == ["company"]

    def test_forget_refuses_an_edge_naming_two_same_slug_far_ends(self, store: EntityMemoryStore) -> None:
        # The mirror of the case above: the same-name pair is at the FAR end, so
        # "works_on -> harbor" names two links. Retiring both while detaching one
        # reciprocal left Alice pointing at neither and company/Harbor pointing
        # back at her.
        for entity_type in ("project", "company"):
            store.remember_about(entity="Harbor", entity_type=entity_type)
        store.remember_about(entity="Alice", entity_type="person")
        store.link_entities(entity="Alice", relation="works_on", related_entity="project/Harbor")
        store.link_entities(entity="Alice", relation="works_on", related_entity="company/Harbor")

        refusal = store.forget(entity="Alice", fact="works_on -> harbor")
        assert "Multiple relationships" in refusal
        assert "works_on -> project/harbor" in refusal and "works_on -> company/harbor" in refusal
        alice = store.get(entity_id="alice", entity_type="person")
        assert alice is not None and len(alice.relationships) == 2

        # The qualified form the refusal asks for retires exactly one.
        assert "Removed relationship" in store.forget(entity="Alice", fact="works_on -> project/harbor")
        alice = store.get(entity_id="alice", entity_type="person")
        assert alice is not None
        assert [r["entity_type"] for r in alice.relationships] == ["company"]
        project_harbor = store.get(entity_id="harbor", entity_type="project")
        company_harbor = store.get(entity_id="harbor", entity_type="company")
        assert project_harbor is not None and project_harbor.relationships == []
        assert company_harbor is not None and len(company_harbor.relationships) == 1

    def test_remember_about_reads_its_own_qualified_form(self, store: EntityMemoryStore) -> None:
        # remember_about is the only entity tool that declares its own type, so
        # the first write under "project/Harbor" had no row to recognise the
        # prefix from and slugged the whole string into project/project_harbor -
        # a phantom no later call could reach.
        store.remember_about(entity="Harbor", entity_type="company", facts=["in talks"])
        store.remember_about(entity="project/Harbor", entity_type="project", facts=["ingest rewrite"])
        store.remember_about(entity="Harbor", entity_type="project", facts=["due friday"])

        rows = {(e.entity_type, e.entity_id) for e in store.list_entities(limit=10)}
        assert rows == {("company", "harbor"), ("project", "harbor")}
        harbor = store.get(entity_id="harbor", entity_type="project")
        assert harbor is not None and len(harbor.live_facts()) == 2

    def test_a_slash_in_a_name_is_still_a_name(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="AC/DC", entity_type="company", facts=["a band"])
        assert store.get(entity_id="ac_dc", entity_type="company") is not None

    def test_names_differing_only_by_a_naming_symbol_stay_apart(self, store: EntityMemoryStore) -> None:
        # C, C++ and C# all slugged to `c`, so one row ended up holding three
        # languages' facts under one name, and the two discarded names were
        # written nowhere. A merge has no unmerge.
        store.remember_about(entity="C++", entity_type="system", facts=["manual memory management"])
        store.remember_about(entity="C#", entity_type="system", facts=["garbage collected"])
        store.remember_about(entity="C", entity_type="system", facts=["no classes"])

        rows = {e.entity_id: e for e in store.list_entities(entity_type="system", limit=10)}
        assert sorted(rows) == ["c", "c_plus_plus", "c_sharp"]
        assert [f["content"] for f in rows["c_sharp"].live_facts()] == ["garbage collected"]

    def test_punctuation_variants_still_merge_and_keep_the_other_surface(self, store: EntityMemoryStore) -> None:
        # The collapse is load-bearing for real merges; what it must not do is
        # discard the name it merged.
        store.remember_about(entity="Acme, Inc.", entity_type="company", facts=["vendor"])
        store.remember_about(entity="Acme Inc", entity_type="company", facts=["renewal in march"])

        rows = store.list_entities(entity_type="company", limit=10)
        assert len(rows) == 1
        assert rows[0].aliases == ["Acme Inc"]
        assert len(rows[0].live_facts()) == 2

    def test_a_relation_stated_from_both_sides_can_be_retired(self, store: EntityMemoryStore) -> None:
        # The model states a symmetric relation from either end, so the row
        # holds the same link twice - once outgoing, once incoming. Both render;
        # a listing that prints only "relation -> far" offers the same string
        # twice and no needle can pick one.
        store.remember_about(entity="Alice", entity_type="person")
        store.remember_about(entity="Bob", entity_type="person")
        store.link_entities(entity="Alice", relation="pairs_with", related_entity="Bob")
        store.link_entities(entity="Bob", relation="pairs_with", related_entity="Alice")

        assert "Removed relationship" in store.forget(entity="Alice", fact="pairs_with -> Bob")
        assert "Removed relationship" in store.forget(entity="Alice", fact="pairs_with <- Bob")
        alice = store.get(entity_id="alice", entity_type="person")
        bob = store.get(entity_id="bob", entity_type="person")
        assert alice is not None and alice.relationships == []
        assert bob is not None and bob.relationships == []

    def test_a_far_end_name_that_extends_another_stays_retireable(self, store: EntityMemoryStore) -> None:
        # "designed_by -> Sarah Chen" used to match the edge to `sarah` too, and
        # the qualified form could not break the tie either, because
        # "person/sarah" is a substring of "person/sarah_chen".
        store.remember_about(entity="Sarah", entity_type="person")
        store.remember_about(entity="Sarah Chen", entity_type="person")
        store.remember_about(entity="radar", entity_type="project")
        store.link_entities(entity="radar", relation="designed_by", related_entity="Sarah")
        store.link_entities(entity="radar", relation="designed_by", related_entity="Sarah Chen")

        refusal = store.forget(entity="radar", fact="designed_by -> Sarah Chen")
        assert "Multiple relationships" in refusal
        assert "Removed relationship" in store.forget(entity="radar", fact="designed_by -> person/sarah_chen")
        radar = store.get(entity_id="radar", entity_type="project")
        assert radar is not None
        assert [r["entity_id"] for r in radar.relationships] == ["sarah"]

    def test_an_accented_far_end_is_retireable_as_rendered(self, store: EntityMemoryStore) -> None:
        # The block renders the display name; the edge stores the folded slug.
        store.remember_about(entity="Harbor", entity_type="project")
        store.remember_about(entity="Caf\u00e9 Noir", entity_type="company")
        store.link_entities(entity="Harbor", relation="supplier_is", related_entity="Caf\u00e9 Noir")

        assert "Removed relationship" in store.forget(entity="Harbor", fact="supplier_is -> Caf\u00e9 Noir")
        harbor = store.get(entity_id="harbor", entity_type="project")
        assert harbor is not None and harbor.relationships == []

    def test_restating_an_event_does_not_double_it(self, store: EntityMemoryStore) -> None:
        for _ in range(3):
            store.remember_about(entity="Tom", entity_type="person", events=["heard he is leaving"])
        tom = store.get(entity_id="tom", entity_type="person")
        assert tom is not None and len(tom.events) == 1

    def test_exact_duplicate_events_retire_completely(self, store: EntityMemoryStore) -> None:
        # A row written before add_event deduped carries exact copies; retiring
        # one and reporting success left the retracted claim rendering.
        store.remember_about(entity="Tom", entity_type="person", events=["heard he is leaving"])
        tom = store.get(entity_id="tom", entity_type="person")
        assert tom is not None
        tom.events.append(dict(tom.events[0], id="dupe1234"))
        store._save_entity(entity=tom, user_id=None, agent_id=None, team_id=None, namespace="global")

        assert "Retired event" in store.forget(entity="Tom", fact="heard he is leaving")
        tom = store.get(entity_id="tom", entity_type="person")
        assert tom is not None and tom.events == []
