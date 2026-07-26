"""Unit tests for relevance recall (spec §3.7 / commit 15).

recall(message=...) returns the top-k relevant entities: name/alias matches
against the message first, then a bounded lexical term search. The keyed
lookup stays available as get(); the directory is always injected.
"""

import json
from typing import Any, Dict, List, Optional

import pytest

from agno.learn.config import EntityMemoryConfig
from agno.learn.stores.entity_memory import EntityMemoryStore, _message_terms


class RecordingLearningDb:
    """In-memory fake of the learnings table (duplicated per test file - the
    tests/unit/learn directory is not a package)."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self._clock = 0

    def get_learning(self, **kwargs: Any) -> Optional[Dict[str, Any]]:
        for row in self.rows.values():
            if all(
                kwargs.get(key) is None or row.get(key) == kwargs.get(key)
                for key in ("learning_type", "entity_id", "entity_type", "namespace")
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
        rows = [
            row
            for row in self.rows.values()
            if all(
                kwargs.get(key) is None or row.get(key) == kwargs.get(key)
                for key in ("learning_type", "entity_id", "entity_type", "namespace")
            )
        ]
        rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
        limit = kwargs.get("limit")
        return rows[:limit] if limit is not None else rows

    def delete_learning(self, id: str) -> bool:
        return self.rows.pop(id, None) is not None

    def search_learnings(self, query: str, **kwargs: Any) -> List[Dict[str, Any]]:
        limit = kwargs.pop("limit", None)
        for key in ("workflow_id", "session_id", "agent_id", "team_id", "user_id"):
            kwargs.pop(key, None)
        candidates = self.get_learnings(**kwargs)
        variants = {query.lower(), query.lower().replace(" ", "_"), query.lower().replace("_", " ")}
        rows = [row for row in candidates if any(v in json.dumps(row.get("content", {})).lower() for v in variants)]
        return rows[:limit] if limit is not None else rows


@pytest.fixture
def db() -> RecordingLearningDb:
    return RecordingLearningDb()


@pytest.fixture
def store(db: RecordingLearningDb) -> EntityMemoryStore:
    return EntityMemoryStore(config=EntityMemoryConfig(db=db))  # type: ignore[arg-type]


class TestMessageTerms:
    def test_extracts_distinctive_terms(self) -> None:
        assert _message_terms("What did we decide about the radar project?") == ["decide", "radar", "project"]

    def test_empty_and_stopword_only(self) -> None:
        assert _message_terms("") == []
        assert _message_terms("what is the") == []


class TestRelevanceRecall:
    def test_name_path_serves_without_term_search(self, db: RecordingLearningDb) -> None:
        # Discriminating test for the NAME path: with k=1 filled by the name
        # match, term search must not run at all - so the name path cannot be
        # silently replaced by the more expensive search fallback.
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, max_entities_in_context=1))  # type: ignore[arg-type]
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])

        def forbidden_search(**kwargs: Any) -> Any:
            raise AssertionError("term search must not run when the name path fills k")

        store.search = forbidden_search  # type: ignore[method-assign]
        recalled = store.recall(message="what is the status of radar?")
        assert recalled is not None
        assert [e.entity_id for e in recalled["entities"]] == ["radar"]

    def test_short_names_match_on_word_boundaries_only(self, store: EntityMemoryStore) -> None:
        # A two-letter entity must not match inside other words and evict the
        # entity the turn is actually about.
        store.remember_about(entity="Al", entity_type="person", facts=["works in finance"])
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])

        recalled = store.recall(message="always check the radar dashboard")
        assert recalled is not None
        ids = [e.entity_id for e in recalled["entities"]]
        assert "radar" in ids and "al" not in ids

        # ...but naming Al on a word boundary matches
        recalled = store.recall(message="ask Al about the budget")
        assert recalled is not None
        assert "al" in [e.entity_id for e in recalled["entities"]]

    def test_message_naming_an_entity_expands_it(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        store.remember_about(entity="unrelated", entity_type="project", facts=["nothing here"])

        recalled = store.recall(message="what is the status of radar?")
        assert recalled is not None
        assert [e.entity_id for e in recalled["entities"]] == ["radar"]

    def test_multi_word_name_matches(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="Sarah Chen", entity_type="person", facts=["designs radar"])
        recalled = store.recall(message="Ask Sarah Chen about the deadline")
        assert recalled is not None
        assert [e.entity_id for e in recalled["entities"]] == ["sarah_chen"]

    def test_alias_matches(self, store: EntityMemoryStore, db: RecordingLearningDb) -> None:
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
        recalled = store.recall(message="Where does the radar initiative stand?")
        assert recalled is not None
        assert [e.entity_id for e in recalled["entities"]] == ["radar"]

    def test_term_search_finds_entity_by_fact_content(self, store: EntityMemoryStore) -> None:
        # The entity's NAME is not in the message; a fact matches the term.
        store.remember_about(entity="radar", entity_type="project", facts=["uses postgresql for storage"])
        recalled = store.recall(message="who knows postgresql here?")
        assert recalled is not None
        assert [e.entity_id for e in recalled["entities"]] == ["radar"]

    def test_no_match_returns_directory_only(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        recalled = store.recall(message="have we discussed quantum tunneling?")
        assert recalled is not None
        assert recalled["entities"] == []
        assert [e.entity_id for e in recalled["directory"]] == ["radar"]

    def test_top_k_bound_is_honored(self, db: RecordingLearningDb) -> None:
        store = EntityMemoryStore(config=EntityMemoryConfig(db=db, max_entities_in_context=2))  # type: ignore[arg-type]
        for i in range(5):
            store.remember_about(entity=f"radar {i}", entity_type="project")
        recalled = store.recall(message="radar 0 radar 1 radar 2 radar 3 radar 4")
        assert recalled is not None
        assert len(recalled["entities"]) == 2

    def test_archived_entities_do_not_recall(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.forget(entity="radar")
        recalled = store.recall(message="what about radar?")
        assert recalled is not None
        assert recalled["entities"] == []

    def test_keyed_lookup_composes_with_message(self, store: EntityMemoryStore) -> None:
        store.remember_about(entity="radar", entity_type="project")
        store.remember_about(entity="lidar", entity_type="project")
        recalled = store.recall(entity_id="radar", entity_type="project", message="compare with lidar")
        assert recalled is not None
        ids = [e.entity_id for e in recalled["entities"]]
        assert ids[0] == "radar" and "lidar" in ids

    async def test_async_relevance_recall(self, store: EntityMemoryStore) -> None:
        await store.aremember_about(entity="radar", entity_type="project", facts=["db: Postgres"])
        recalled = await store.arecall(message="what about radar?")
        assert recalled is not None
        assert [e.entity_id for e in recalled["entities"]] == ["radar"]


class TestRecallReachesTheAgent:
    def test_stored_entity_reaches_the_system_message(self) -> None:
        """The §8 bullet whose absence let entity memory ship write-only: given
        a stored entity and a message mentioning it, the rendered system
        message contains that entity's facts."""
        from agno.agent import Agent
        from agno.agent._messages import get_system_message
        from agno.learn import LearningMachine
        from agno.models.openai import OpenAIResponses
        from agno.run.base import RunContext
        from agno.session import AgentSession

        db = RecordingLearningDb()
        machine = LearningMachine(db=db, entity_memory=True)  # type: ignore[arg-type]
        entity_store = machine.entity_memory_store
        assert entity_store is not None
        entity_store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres, over Dynamo"])

        agent = Agent(db=db, learning=machine, model=OpenAIResponses(id="gpt-5.5"))  # type: ignore[arg-type]
        agent._learning = machine
        session = AgentSession(session_id="s1")
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1")

        message = get_system_message(
            agent, session=session, run_context=run_context, input="what did we decide for radar?"
        )
        assert message is not None
        content = str(message.content)
        assert "db: Postgres, over Dynamo" in content

    def test_stored_entity_reaches_the_system_message_through_get_run_messages(self) -> None:
        """The same bullet, guarded one layer up.

        The original write-only bug was a dropped kwarg at the CALL SITE, not
        inside get_system_message, so the regression guard has to run the seam
        that broke: get_run_messages must hand the run input down.
        """
        from agno.agent import Agent
        from agno.agent._messages import get_run_messages
        from agno.learn import LearningMachine
        from agno.models.openai import OpenAIResponses
        from agno.run.agent import RunOutput
        from agno.run.base import RunContext
        from agno.session import AgentSession

        db = RecordingLearningDb()
        machine = LearningMachine(db=db, entity_memory=True)  # type: ignore[arg-type]
        entity_store = machine.entity_memory_store
        assert entity_store is not None
        entity_store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres, over Dynamo"])

        agent = Agent(db=db, learning=machine, model=OpenAIResponses(id="gpt-5.5"))  # type: ignore[arg-type]
        agent._learning = machine
        session = AgentSession(session_id="s1")
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1")

        run_messages = get_run_messages(
            agent,
            run_response=RunOutput(run_id="r1", session_id="s1"),
            run_context=run_context,
            input="what did we decide for radar?",
            session=session,
        )
        assert run_messages.system_message is not None
        assert "db: Postgres, over Dynamo" in str(run_messages.system_message.content)

    async def test_stored_entity_reaches_the_system_message_through_aget_run_messages(self) -> None:
        """Async twin of the call-site guard."""
        from agno.agent import Agent
        from agno.agent._messages import aget_run_messages
        from agno.learn import LearningMachine
        from agno.models.openai import OpenAIResponses
        from agno.run.agent import RunOutput
        from agno.run.base import RunContext
        from agno.session import AgentSession

        db = RecordingLearningDb()
        machine = LearningMachine(db=db, entity_memory=True)  # type: ignore[arg-type]
        entity_store = machine.entity_memory_store
        assert entity_store is not None
        await entity_store.aremember_about(entity="radar", entity_type="project", facts=["db: Postgres, over Dynamo"])

        agent = Agent(db=db, learning=machine, model=OpenAIResponses(id="gpt-5.5"))  # type: ignore[arg-type]
        agent._learning = machine
        session = AgentSession(session_id="s1")
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1")

        run_messages = await aget_run_messages(
            agent,
            run_response=RunOutput(run_id="r1", session_id="s1"),
            run_context=run_context,
            input="what did we decide for radar?",
            session=session,
        )
        assert run_messages.system_message is not None
        assert "db: Postgres, over Dynamo" in str(run_messages.system_message.content)


async def test_async_far_edge_detach_reaches_an_async_db(tmp_path) -> None:
    """The sync helpers no-op against an AsyncBaseDb.

    aforget dropped the near end's edge and left the far end holding a
    reciprocal edge to a relationship that no longer exists.
    """
    from agno.db.sqlite import AsyncSqliteDb
    from agno.learn.config import LearningMode
    from agno.learn.stores.entity_memory import EntityMemoryStore

    db = AsyncSqliteDb(db_file=str(tmp_path / "a.db"))
    store = EntityMemoryStore(
        config=EntityMemoryConfig(db=db, mode=LearningMode.AGENTIC, namespace="global")  # type: ignore[arg-type]
    )
    await store.aremember_about(entity="quill", entity_type="project", namespace="global")
    await store.alink_entities(entity="quill", relation="written_in", related_entity="Rust", namespace="global")
    await store.aforget(entity="quill", fact="written_in -> Rust", namespace="global")

    quill = await store.aget(entity_id="quill", entity_type="project", namespace="global")
    rust = await store.aget(entity_id="rust", entity_type="unknown", namespace="global")
    assert quill is not None and rust is not None
    assert quill.relationships == []
    assert rust.relationships == []


class TestAsyncEntityToolsAgainstARealAsyncDb:
    """The sync helpers no-op against an AsyncBaseDb.

    Every one of these passed against the in-memory fake while the real async
    backend was broken - the fake is synchronous, so it cannot see the gap.
    """

    async def _store(self, tmp_path, name):
        from agno.db.sqlite import AsyncSqliteDb
        from agno.learn.config import LearningMode
        from agno.learn.stores.entity_memory import EntityMemoryStore

        db = AsyncSqliteDb(db_file=str(tmp_path / name))
        return EntityMemoryStore(
            config=EntityMemoryConfig(db=db, mode=LearningMode.AGENTIC, namespace="global")  # type: ignore[arg-type]
        )

    async def test_ambiguous_name_refuses(self, tmp_path) -> None:
        store = await self._store(tmp_path, "a.db")
        await store.aremember_about(entity="Harbor", entity_type="project", namespace="global")
        await store.aremember_about(entity="Harbor", entity_type="company", namespace="global")

        assert "matches more than one entity" in await store.aforget(entity="Harbor", namespace="global")
        assert "matches more than one entity" in await store.alink_entities(
            entity="Harbor", relation="uses", related_entity="Postgres", namespace="global"
        )
        project = await store.aget(entity_id="harbor", entity_type="project", namespace="global")
        assert project is not None and not getattr(project, "archived_at", None)

    async def test_qualified_name_reaches_either_entity(self, tmp_path) -> None:
        store = await self._store(tmp_path, "b.db")
        await store.aremember_about(entity="Harbor", entity_type="project", namespace="global")
        await store.aremember_about(entity="Harbor", entity_type="company", namespace="global")

        message = await store.alink_entities(
            entity="project/Harbor", relation="uses", related_entity="Postgres", namespace="global"
        )
        assert "project/harbor" in message
        assert "Archived company/harbor" in await store.aforget(entity="company/Harbor", namespace="global")

        project = await store.aget(entity_id="harbor", entity_type="project", namespace="global")
        company = await store.aget(entity_id="harbor", entity_type="company", namespace="global")
        assert project is not None and company is not None
        assert [r["entity_id"] for r in project.relationships] == ["postgres"]
        assert getattr(company, "archived_at", None) and not getattr(project, "archived_at", None)

    async def test_sibling_signal_reaches_the_async_write(self, tmp_path) -> None:
        store = await self._store(tmp_path, "c.db")
        await store.aremember_about(entity="Atlas", entity_type="system", namespace="global")
        message = await store.aremember_about(entity="Atlas", entity_type="team", namespace="global")
        assert "system/atlas already exists under this name" in message


class TestTheSeamsThatBrokeBefore:
    """Guards for the two seams whose absence is how this release's bugs shipped.

    Both were found by mutation: the shipped code is correct, and every test
    stayed green when it was broken.
    """

    def test_stored_entity_reaches_a_teams_system_message(self, tmp_path) -> None:
        """The Team half of the write-only bug.

        team/_messages.py threads the run input, the guidance block and the
        message kwarg through three separate lines, and deleting any of them
        left 1,679 tests green while Team recall died. Agents had a guard from
        the first review pass; Teams did not.
        """
        from agno.db.sqlite import SqliteDb
        from agno.learn import LearningMachine
        from agno.models.openai import OpenAIResponses
        from agno.run.base import RunContext
        from agno.run.team import TeamRunOutput
        from agno.session import TeamSession
        from agno.team._messages import _get_run_messages
        from agno.team.team import Team

        db = SqliteDb(db_file=str(tmp_path / "team.db"))
        machine = LearningMachine(db=db, entity_memory=True)
        store = machine.entity_memory_store
        assert store is not None
        store.remember_about(entity="radar", entity_type="project", facts=["db: Postgres, over Dynamo"])

        team = Team(members=[], db=db, learning=machine, model=OpenAIResponses(id="gpt-5.5"))
        team._learning = machine
        session = TeamSession(session_id="s1")
        run_context = RunContext(run_id="r1", session_id="s1", user_id="u1")

        run_messages = _get_run_messages(
            team,
            run_response=TeamRunOutput(run_id="r1", session_id="s1"),
            run_context=run_context,
            session=session,
            input_message="what did we decide for radar?",
        )
        system = next(m for m in run_messages.messages if m.role == "system")
        content = str(system.content)
        assert "db: Postgres, over Dynamo" in content
        assert "entity_memory_instructions" in content

    def test_the_entity_a_query_names_outranks_the_ones_that_mention_it(self, tmp_path) -> None:
        """search_learnings orders by recency and does not rank.

        Five newer entities whose facts merely mention "Harbor" filled the
        verified window - they all legitimately match - and Harbor's own row,
        older, was never fetched. Recall then injected the wrong entities and
        search_entities confirmed them.
        """
        import time

        from agno.db.sqlite import SqliteDb
        from agno.learn.config import EntityMemoryConfig, LearningMode
        from agno.learn.stores.entity_memory import EntityMemoryStore

        store = EntityMemoryStore(
            config=EntityMemoryConfig(  # type: ignore[arg-type]
                db=SqliteDb(db_file=str(tmp_path / "rank.db")), mode=LearningMode.AGENTIC, namespace="global"
            )
        )
        store.remember_about(entity="Harbor", entity_type="project", facts=["db: Postgres, over Dynamo"])
        # Rows written in the same second do not order under updated_at DESC.
        time.sleep(1.1)
        for i in range(8):
            store.remember_about(
                entity=f"Person {i}", entity_type="person", facts=[f"works on Harbor ingest, shift {i}"]
            )

        hits = store.search(query="Harbor", namespace="global", limit=5)
        assert hits and hits[0].entity_id == "harbor"

        recalled = store.recall(message="where does Harbor stand?", namespace="global")
        assert recalled is not None
        assert "harbor" in [e.entity_id for e in recalled["entities"]]

    @pytest.mark.asyncio
    async def test_concurrent_writes_in_one_turn_all_land(self, tmp_path) -> None:
        """The write lock, guarded against its own removal.

        Every entity write is a read-modify-write over one JSON row, and a
        model's tool calls for one turn are gathered concurrently - the path
        AgentOS REST and /mcp take. Without the lock this loses 7 of 8 facts on
        a real AsyncSqliteDb, and the fake db cannot see it because it aliases
        the content dict.
        """
        import asyncio

        from agno.db.sqlite import AsyncSqliteDb
        from agno.learn.config import EntityMemoryConfig, LearningMode
        from agno.learn.stores.entity_memory import EntityMemoryStore

        db = AsyncSqliteDb(db_file=str(tmp_path / "concurrent.db"))
        store = EntityMemoryStore(
            config=EntityMemoryConfig(db=db, mode=LearningMode.AGENTIC, namespace="global")  # type: ignore[arg-type]
        )
        await store.aremember_about(entity="radar", entity_type="project", facts=["seed"], namespace="global")

        await asyncio.gather(
            *[
                store.aremember_about(entity="radar", entity_type="project", facts=[f"fact {i}"], namespace="global")
                for i in range(8)
            ]
        )

        radar = await store.aget(entity_id="radar", entity_type="project", namespace="global")
        assert radar is not None
        stored = {f["content"] for f in radar.live_facts()}
        assert stored == {"seed", *(f"fact {i}" for i in range(8))}
