"""Per-user RAG isolation must survive the agent/team -> knowledge handoff."""

from typing import Any, Dict, List, Optional

import pytest

from agno.knowledge.document import Document
from agno.run.base import RunContext

ALICE = "alice"


class SpyKnowledge:
    """Records the owner each retrieval was scoped to.

    ``retrieve``/``aretrieve`` accept ``user_id``, so the signature probe in the
    retrieval helpers is expected to find the parameter and pass the owner.
    """

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
    """A pre-isolation Knowledge whose ``retrieve`` has no ``user_id`` parameter.

    Passing the kwarg unconditionally would raise ``TypeError``, so the helpers
    probe the signature first. This guards that probe.
    """

    def __init__(self) -> None:
        self.max_results = 5
        self.vector_db = None
        self.calls = 0

    def validate_filters(self, filters):
        return filters or {}, []

    async def avalidate_filters(self, filters):
        return filters or {}, []

    def retrieve(self, query, max_results=None, filters=None, **kwargs) -> List[Document]:
        self.calls += 1
        return [Document(content="legacy chunk")]


class SpyOwner:
    """The attribute surface the agent/team retrieval helpers read."""

    def __init__(self, knowledge: Any) -> None:
        self.knowledge = knowledge
        self.knowledge_retriever = None
        self.knowledge_filters = None
        self.enable_agentic_knowledge_filters = False
        self.references_format = "json"


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


class ProtocolKnowledge:
    """A ``KnowledgeProtocol``-shaped implementation: ``retrieve(query, **kwargs)``.

    ``agno/knowledge/protocol.py`` documents retrieval with ``**kwargs`` rather
    than named parameters, so a conforming class never declares ``user_id``
    explicitly. Probing only for the literal name would drop the owner here -
    and since ``None`` is the admin view, the drop widens retrieval to every
    owner instead of raising.
    """

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


class TestAcceptsUserIdHelper:
    """The shared probe all four retrieval sites depend on."""

    def test_explicit_user_id_parameter(self):
        from agno.utils.knowledge import accepts_user_id

        def fn(query, max_results=None, filters=None, user_id=None): ...

        assert accepts_user_id(fn) is True

    def test_var_keyword_parameter(self):
        from agno.utils.knowledge import accepts_user_id

        def fn(query, **kwargs): ...

        assert accepts_user_id(fn) is True

    def test_legacy_signature_without_either(self):
        from agno.utils.knowledge import accepts_user_id

        def fn(query, max_results=None, filters=None): ...

        assert accepts_user_id(fn) is False

    def test_uninspectable_callable_is_false(self):
        """Builtins raise on signature() - fall back to the legacy contract."""
        from agno.utils.knowledge import accepts_user_id

        assert accepts_user_id(len) is False
