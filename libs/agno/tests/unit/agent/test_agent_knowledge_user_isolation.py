"""Per-user RAG isolation must survive the agent/team -> knowledge handoff."""

from typing import Any, Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.run.base import RunContext

ALICE = "alice"


class SpyKnowledge:
    """Records the owner each retrieval was scoped to. ``retrieve`` declares ``user_id``."""

    def __init__(self) -> None:
        self.max_results = 5
        self.vector_db = None
        self.seen_user_ids: List[Optional[str]] = []

    def validate_filters(self, filters):
        return filters or {}, []

    async def avalidate_filters(self, filters):
        return filters or {}, []

    def retrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> List[Document]:
        self.seen_user_ids.append(user_id)
        return [Document(content="owned chunk")]

    async def aretrieve(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> List[Document]:
        self.seen_user_ids.append(user_id)
        return [Document(content="owned chunk")]


class LegacyKnowledge:
    """A pre-isolation Knowledge: ``retrieve`` declares neither ``user_id`` nor ``**kwargs``."""

    def __init__(self) -> None:
        self.max_results = 5
        self.vector_db = None
        self.calls = 0

    def validate_filters(self, filters):
        return filters or {}, []

    async def avalidate_filters(self, filters):
        return filters or {}, []

    def retrieve(self, query, max_results=None, filters=None) -> List[Document]:
        self.calls += 1
        return [Document(content="legacy chunk")]

    async def aretrieve(self, query, max_results=None, filters=None) -> List[Document]:
        self.calls += 1
        return [Document(content="legacy chunk")]


class SpyOwner:
    """The attribute surface the agent/team retrieval helpers read."""

    def __init__(self, knowledge: Any, user_id: Optional[str] = None) -> None:
        self.knowledge = knowledge
        self.knowledge_retriever = None
        self.knowledge_filters = None
        self.enable_agentic_knowledge_filters = False
        self.references_format = "json"
        # Read only when no run_context is supplied
        self.user_id = user_id


@pytest.fixture
def knowledge() -> SpyKnowledge:
    return SpyKnowledge()


@pytest.fixture
def run_context() -> RunContext:
    return RunContext(run_id="run-1", user_id=ALICE, session_id="session-1")


class TestAgentRetrievalScopesToOwner:
    def test_sync_helper_forwards_owner(self, knowledge, run_context):
        from agno.agent import _messages

        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert knowledge.seen_user_ids == [ALICE], (
            "Agent retrieval dropped the owner; the vector DB would be queried "
            "with user_id=None, which is the admin view over every owner."
        )

    @pytest.mark.asyncio
    async def test_async_helper_forwards_owner(self, knowledge, run_context):
        from agno.agent import _messages

        await _messages.aget_relevant_docs_from_knowledge(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert knowledge.seen_user_ids == [ALICE]

    def test_unscoped_run_stays_unscoped(self, knowledge):
        """No owner on the run context is the admin view - None must stay None."""
        from agno.agent import _messages

        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            query="anything",
            run_context=RunContext(run_id="run-2", user_id=None, session_id="session-2"),
        )

        assert knowledge.seen_user_ids == [None]

    def test_missing_run_context_is_unscoped(self, knowledge):
        from agno.agent import _messages

        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            query="anything",
        )

        assert knowledge.seen_user_ids == [None]


class TestDefaultSearchToolScopesToOwner:
    """The tool ``search_knowledge=True`` installs is the primary RAG path."""

    def test_sync_tool_forwards_owner(self, knowledge, run_context):
        from agno.agent import _default_tools

        tool = _default_tools.create_knowledge_search_tool(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            run_context=run_context,
        )
        tool.entrypoint(query="what is my salary")

        assert knowledge.seen_user_ids == [ALICE]

    @pytest.mark.asyncio
    async def test_async_tool_forwards_owner(self, knowledge, run_context):
        from agno.agent import _default_tools

        tool = _default_tools.create_knowledge_search_tool(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            run_context=run_context,
            async_mode=True,
        )
        await tool.entrypoint(query="what is my salary")

        assert knowledge.seen_user_ids == [ALICE]


class TestTeamRetrievalScopesToOwner:
    """Teams share the knowledge path and need the same guarantee."""

    def test_sync_helper_forwards_owner(self, knowledge, run_context):
        from agno.team import _default_tools as team_tools

        team_tools.get_relevant_docs_from_knowledge(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert knowledge.seen_user_ids == [ALICE]

    @pytest.mark.asyncio
    async def test_async_helper_forwards_owner(self, knowledge, run_context):
        from agno.team import _default_tools as team_tools

        await team_tools.aget_relevant_docs_from_knowledge(
            SpyOwner(knowledge),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert knowledge.seen_user_ids == [ALICE]


class TestLegacyKnowledgeStillWorks:
    """A custom Knowledge predating isolation must not start raising TypeError."""

    def test_sync_retrieve_without_user_id_is_tolerated(self, run_context):
        from agno.agent import _messages

        legacy = LegacyKnowledge()
        docs = _messages.get_relevant_docs_from_knowledge(
            SpyOwner(legacy),  # type: ignore[arg-type]
            query="q",
            run_context=run_context,
        )

        assert legacy.calls == 1
        assert docs

    @pytest.mark.asyncio
    async def test_async_retrieve_without_user_id_is_tolerated(self, run_context):
        from agno.agent import _messages

        legacy = LegacyKnowledge()
        docs = await _messages.aget_relevant_docs_from_knowledge(
            SpyOwner(legacy),  # type: ignore[arg-type]
            query="q",
            run_context=run_context,
        )

        assert legacy.calls == 1
        assert docs

    def test_dropping_the_owner_warns(self, run_context, monkeypatch):
        """A dropped owner is tolerated, but it has to warn: retrieval runs unscoped."""
        from agno.agent import _messages
        from agno.utils import knowledge as knowledge_utils

        warnings: List[str] = []
        monkeypatch.setattr(knowledge_utils, "log_warning", lambda msg: warnings.append(msg))

        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(LegacyKnowledge()),  # type: ignore[arg-type]
            query="q",
            run_context=run_context,
        )

        assert len(warnings) == 1
        assert "does not accept user_id" in warnings[0]
        assert "LegacyKnowledge.retrieve" in warnings[0]

    def test_unscoped_run_does_not_warn(self, monkeypatch):
        """An unscoped run has no owner to drop, so it must not warn."""
        from agno.agent import _messages
        from agno.utils import knowledge as knowledge_utils

        warnings: List[str] = []
        monkeypatch.setattr(knowledge_utils, "log_warning", lambda msg: warnings.append(msg))

        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(LegacyKnowledge()),  # type: ignore[arg-type]
            query="q",
            run_context=RunContext(run_id="run-3", user_id=None, session_id="session-3"),
        )

        assert warnings == []


class TestOwnerFallsBackToTheComponent:
    """``Agent.get_relevant_docs_from_knowledge`` is public and defaults run_context to None."""

    def test_sync_direct_call_uses_agent_user_id(self, knowledge):
        from agno.agent import _messages

        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(knowledge, user_id=ALICE),  # type: ignore[arg-type]
            query="what is my salary",
        )

        assert knowledge.seen_user_ids == [ALICE], (
            "A direct call fell back to user_id=None, which is the admin view over every owner."
        )

    @pytest.mark.asyncio
    async def test_async_direct_call_uses_agent_user_id(self, knowledge):
        from agno.agent import _messages

        await _messages.aget_relevant_docs_from_knowledge(
            SpyOwner(knowledge, user_id=ALICE),  # type: ignore[arg-type]
            query="what is my salary",
        )

        assert knowledge.seen_user_ids == [ALICE]

    def test_run_context_owner_still_wins(self, knowledge):
        """An explicit run owner beats the component default."""
        from agno.agent import _messages

        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(knowledge, user_id="bob"),  # type: ignore[arg-type]
            query="q",
            run_context=RunContext(run_id="run-4", user_id=ALICE, session_id="session-4"),
        )

        assert knowledge.seen_user_ids == [ALICE]


class TestCustomRetrieverGetsOwner:
    """``Agent(knowledge_retriever=...)`` is the documented extension point."""

    def test_retriever_declaring_user_id_receives_it(self, run_context):
        from agno.agent import _messages

        seen: List[Any] = []

        def retriever(query, num_documents=None, user_id=None, **kwargs):
            seen.append(user_id)
            return [Document(content="chunk")]

        owner = SpyOwner(SpyKnowledge())
        owner.knowledge_retriever = retriever  # type: ignore[assignment]
        _messages.get_relevant_docs_from_knowledge(
            owner,  # type: ignore[arg-type]
            query="q",
            run_context=run_context,
        )

        assert seen == [ALICE]

    def test_variadic_retriever_also_gets_the_owner(self, run_context):
        """A retriever declared ``(query, **kwargs)`` still receives the owner."""
        from agno.agent import _messages

        seen: List[Any] = []

        def retriever(query, num_documents=None, **kwargs):
            seen.append(kwargs.get("user_id", "<absent>"))
            return [Document(content="chunk")]

        owner = SpyOwner(SpyKnowledge())
        owner.knowledge_retriever = retriever  # type: ignore[assignment]
        _messages.get_relevant_docs_from_knowledge(
            owner,  # type: ignore[arg-type]
            query="q",
            run_context=run_context,
        )

        assert seen == [ALICE]

    def test_caller_kwargs_cannot_override_the_owner(self, run_context):
        """The owner comes from the run context, so caller kwargs must not win."""
        from agno.agent import _messages

        seen: List[Any] = []

        def retriever(query, num_documents=None, user_id=None, **kwargs):
            seen.append(user_id)
            return [Document(content="chunk")]

        owner = SpyOwner(SpyKnowledge())
        owner.knowledge_retriever = retriever  # type: ignore[assignment]
        _messages.get_relevant_docs_from_knowledge(
            owner,  # type: ignore[arg-type]
            query="q",
            run_context=run_context,
            user_id="bob",
        )

        assert seen == [ALICE]


class ProtocolKnowledge:
    """A ``KnowledgeProtocol``-shaped implementation: ``retrieve(query, **kwargs)``, no named ``user_id``."""

    def __init__(self) -> None:
        self.max_results = 5
        self.vector_db = None
        self.seen_user_ids: List[Any] = []

    def validate_filters(self, filters):
        return filters or {}, []

    async def avalidate_filters(self, filters):
        return filters or {}, []

    def retrieve(self, query: str, **kwargs) -> List[Document]:
        self.seen_user_ids.append(kwargs.get("user_id", "<absent>"))
        return [Document(content="chunk")]

    async def aretrieve(self, query: str, **kwargs) -> List[Document]:
        self.seen_user_ids.append(kwargs.get("user_id", "<absent>"))
        return [Document(content="chunk")]


class TestVariadicKnowledgeStillGetsOwner:
    """``**kwargs`` retrieval must receive the owner, not silently fall back to admin."""

    def test_sync_agent_forwards_owner_through_kwargs(self, run_context):
        from agno.agent import _messages

        kb = ProtocolKnowledge()
        _messages.get_relevant_docs_from_knowledge(
            SpyOwner(kb),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert kb.seen_user_ids == [ALICE], (
            "A **kwargs Knowledge lost the owner, so retrieval ran unscoped "
            "(user_id=None) and would return every owner's chunks."
        )

    @pytest.mark.asyncio
    async def test_async_agent_forwards_owner_through_kwargs(self, run_context):
        from agno.agent import _messages

        kb = ProtocolKnowledge()
        await _messages.aget_relevant_docs_from_knowledge(
            SpyOwner(kb),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert kb.seen_user_ids == [ALICE]

    def test_sync_team_forwards_owner_through_kwargs(self, run_context):
        from agno.team import _default_tools as team_tools

        kb = ProtocolKnowledge()
        team_tools.get_relevant_docs_from_knowledge(
            SpyOwner(kb),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert kb.seen_user_ids == [ALICE]

    @pytest.mark.asyncio
    async def test_async_team_forwards_owner_through_kwargs(self, run_context):
        from agno.team import _default_tools as team_tools

        kb = ProtocolKnowledge()
        await team_tools.aget_relevant_docs_from_knowledge(
            SpyOwner(kb),  # type: ignore[arg-type]
            query="what is my salary",
            run_context=run_context,
        )

        assert kb.seen_user_ids == [ALICE]


class VariadicInsertKnowledge:
    """A custom Knowledge whose ``insert`` is declared ``insert(self, **kwargs)``."""

    def __init__(self) -> None:
        self.stored: List[Dict[str, Any]] = []

    def insert(self, **kwargs) -> None:
        self.stored.append({"name": kwargs.get("name"), "user_id": kwargs.get("user_id")})


class OwnerAwareInsertKnowledge:
    """A Knowledge that declares ``user_id``, like ``agno.knowledge.Knowledge.insert``."""

    def __init__(self) -> None:
        self.stored: List[Dict[str, Any]] = []

    def insert(self, name=None, text_content=None, reader=None, user_id=None) -> None:
        self.stored.append({"name": name, "user_id": user_id})


class TestAddToKnowledgeScopesTheWrite:
    """The owner reaches insert, so what an agent learns stays the caller's."""

    def test_agent_write_reaches_an_owner_aware_insert(self):
        from agno.agent import _default_tools as agent_tools

        kb = OwnerAwareInsertKnowledge()
        agent_tools.add_to_knowledge(SpyOwner(kb), query="salary", result="100k", user_id=ALICE)  # type: ignore[arg-type]

        assert kb.stored == [{"name": "salary", "user_id": ALICE}]

    def test_team_write_reaches_an_owner_aware_insert(self):
        from agno.team import _default_tools as team_tools

        kb = OwnerAwareInsertKnowledge()
        team_tools.add_to_knowledge(SpyOwner(kb), query="salary", result="100k", user_id=ALICE)  # type: ignore[arg-type]

        assert kb.stored == [{"name": "salary", "user_id": ALICE}]

    def test_agent_write_reaches_a_variadic_insert(self, monkeypatch):
        """A wrapper that forwards its kwargs is scoped like any other insert."""
        from agno.agent import _default_tools as agent_tools
        from agno.utils import knowledge as knowledge_utils

        warnings: List[str] = []
        monkeypatch.setattr(knowledge_utils, "log_warning", lambda msg: warnings.append(msg))

        kb = VariadicInsertKnowledge()
        agent_tools.add_to_knowledge(SpyOwner(kb), query="salary", result="100k", user_id=ALICE)  # type: ignore[arg-type]

        assert kb.stored == [{"name": "salary", "user_id": ALICE}]
        assert warnings == []

    def test_team_write_reaches_a_variadic_insert(self, monkeypatch):
        from agno.team import _default_tools as team_tools
        from agno.utils import knowledge as knowledge_utils

        warnings: List[str] = []
        monkeypatch.setattr(knowledge_utils, "log_warning", lambda msg: warnings.append(msg))

        kb = VariadicInsertKnowledge()
        team_tools.add_to_knowledge(SpyOwner(kb), query="salary", result="100k", user_id=ALICE)  # type: ignore[arg-type]

        assert kb.stored == [{"name": "salary", "user_id": ALICE}]
        assert warnings == []

    def test_a_scoped_write_to_an_insert_predating_isolation_is_refused(self):
        """Dropping the owner here would store the caller's content in the shared bucket.

        Unlike a read, where a dropped scope only over-fetches, a write lands the row where
        every other user can read it and no owner-scoped delete can reach it. The write is
        refused rather than silently widened.
        """
        from agno.agent import _default_tools as agent_tools

        class LegacyInsertKnowledge:
            def __init__(self) -> None:
                self.stored: List[Dict[str, Any]] = []

            def insert(self, name=None, text_content=None, reader=None) -> None:
                self.stored.append({"name": name})

        kb = LegacyInsertKnowledge()

        with pytest.raises(ValueError, match="shared bucket"):
            agent_tools.add_to_knowledge(SpyOwner(kb), query="salary", result="100k", user_id=ALICE)  # type: ignore[arg-type]

        assert kb.stored == []

    def test_the_team_write_is_refused_the_same_way(self):
        """Agent and team share the contract; a gap in either is the same leak."""
        from agno.team import _default_tools as team_tools

        class LegacyInsertKnowledge:
            def __init__(self) -> None:
                self.stored: List[Dict[str, Any]] = []

            def insert(self, name=None, text_content=None, reader=None) -> None:
                self.stored.append({"name": name})

        kb = LegacyInsertKnowledge()

        with pytest.raises(ValueError, match="shared bucket"):
            team_tools.add_to_knowledge(SpyOwner(kb), query="salary", result="100k", user_id=ALICE)  # type: ignore[arg-type]

        assert kb.stored == []

    def test_an_unscoped_write_to_an_insert_predating_isolation_still_works(self):
        """v2 parity: with no owner to lose, a legacy Knowledge keeps working untouched."""
        from agno.agent import _default_tools as agent_tools

        class LegacyInsertKnowledge:
            def __init__(self) -> None:
                self.stored: List[Dict[str, Any]] = []

            def insert(self, name=None, text_content=None, reader=None) -> None:
                self.stored.append({"name": name})

        kb = LegacyInsertKnowledge()
        agent_tools.add_to_knowledge(SpyOwner(kb), query="salary", result="100k", user_id=None)  # type: ignore[arg-type]

        assert kb.stored == [{"name": "salary"}]

    def test_unscoped_write_does_not_warn(self, monkeypatch):
        """No owner to lose, so a variadic insert is not worth reporting."""
        from agno.agent import _default_tools as agent_tools
        from agno.utils import knowledge as knowledge_utils

        warnings: List[str] = []
        monkeypatch.setattr(knowledge_utils, "log_warning", lambda msg: warnings.append(msg))

        agent_tools.add_to_knowledge(SpyOwner(VariadicInsertKnowledge()), query="salary", result="100k")  # type: ignore[arg-type]

        assert warnings == []


class TestGetUserIdKwarg:
    """The shared probe all four retrieval sites depend on."""

    def test_explicit_user_id_parameter(self):
        from agno.utils.knowledge import get_user_id_kwarg

        def fn(query, max_results=None, filters=None, user_id=None): ...

        assert get_user_id_kwarg(fn, ALICE) == {"user_id": ALICE}

    def test_var_keyword_parameter(self):
        from agno.utils.knowledge import get_user_id_kwarg

        def fn(query, **kwargs): ...

        assert get_user_id_kwarg(fn, ALICE) == {"user_id": ALICE}

    def test_insert_signature_parameter(self):
        """The write path reads the same probe as the four read sites."""
        from agno.utils.knowledge import get_user_id_kwarg

        def fn(name=None, text_content=None, reader=None, user_id=None): ...

        assert get_user_id_kwarg(fn, ALICE) == {"user_id": ALICE}

    def test_var_keyword_does_not_warn(self, monkeypatch):
        """``KnowledgeProtocol`` documents ``retrieve(query, **kwargs)``, so this is correct."""
        from agno.utils import knowledge as knowledge_utils

        warnings: List[str] = []
        monkeypatch.setattr(knowledge_utils, "log_warning", lambda msg: warnings.append(msg))

        def fn(query, **kwargs): ...

        assert knowledge_utils.get_user_id_kwarg(fn, ALICE) == {"user_id": ALICE}
        assert warnings == []

    def test_legacy_signature_without_either(self):
        from agno.utils.knowledge import get_user_id_kwarg

        def fn(query, max_results=None, filters=None): ...

        assert get_user_id_kwarg(fn, ALICE) == {}

    def test_uninspectable_callable_is_skipped(self):
        """Builtins raise on signature() - fall back to the legacy contract."""
        from agno.utils.knowledge import get_user_id_kwarg

        assert get_user_id_kwarg(len, ALICE) == {}

    def test_unscoped_run_does_not_warn(self, monkeypatch):
        """No owner to lose, so nothing to report."""
        from agno.utils import knowledge as knowledge_utils

        warnings: List[str] = []
        monkeypatch.setattr(knowledge_utils, "log_warning", lambda msg: warnings.append(msg))

        def fn(query, max_results=None, filters=None): ...

        assert knowledge_utils.get_user_id_kwarg(fn, None) == {}
        assert warnings == []
