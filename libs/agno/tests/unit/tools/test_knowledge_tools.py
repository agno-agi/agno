"""Unit tests for KnowledgeTools custom retriever support."""

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from agno.knowledge.document import Document
from agno.run import RunContext
from agno.tools.knowledge import KnowledgeTools


@pytest.fixture
def run_context() -> RunContext:
    return RunContext(run_id="test-run", session_id="test-session", session_state={})


def test_requires_knowledge_or_retriever():
    with pytest.raises(ValueError, match="knowledge or knowledge_retriever"):
        KnowledgeTools(knowledge=None, knowledge_retriever=None)


def test_search_falls_back_to_knowledge_search(run_context: RunContext):
    knowledge = MagicMock()
    knowledge.search.return_value = [Document(content="hello from knowledge")]
    knowledge.max_results = 5

    tools = KnowledgeTools(knowledge=knowledge, enable_think=False, enable_analyze=False)
    result = tools.search_knowledge(run_context=run_context, query="hello")

    knowledge.search.assert_called_once_with(query="hello")
    docs = json.loads(result)
    assert docs[0]["content"] == "hello from knowledge"


def test_search_uses_custom_retriever(run_context: RunContext):
    calls: List[Dict[str, Any]] = []

    def custom_retriever(
        query: str,
        num_documents: Optional[int] = None,
        run_context: Optional[RunContext] = None,
        **kwargs: Any,
    ) -> List[dict]:
        calls.append(
            {
                "query": query,
                "num_documents": num_documents,
                "run_context": run_context,
            }
        )
        return [{"content": f"custom:{query}"}]

    knowledge = MagicMock()
    knowledge.max_results = 3
    tools = KnowledgeTools(
        knowledge=knowledge,
        knowledge_retriever=custom_retriever,
        enable_think=False,
        enable_analyze=False,
    )

    result = tools.search_knowledge(run_context=run_context, query="python")

    knowledge.search.assert_not_called()
    assert calls[0]["query"] == "python"
    assert calls[0]["num_documents"] == 3
    assert calls[0]["run_context"] is run_context
    assert json.loads(result) == [{"content": "custom:python"}]


def test_search_with_retriever_only(run_context: RunContext):
    def custom_retriever(query: str, num_documents: Optional[int] = None, **kwargs: Any) -> List[dict]:
        return [{"content": "retriever-only"}]

    tools = KnowledgeTools(
        knowledge=None,
        knowledge_retriever=custom_retriever,
        enable_think=False,
        enable_analyze=False,
    )
    result = tools.search_knowledge(run_context=run_context, query="x")
    assert json.loads(result) == [{"content": "retriever-only"}]


def test_search_retriever_returns_empty(run_context: RunContext):
    def custom_retriever(query: str, num_documents: Optional[int] = None, **kwargs: Any) -> None:
        return None

    tools = KnowledgeTools(
        knowledge_retriever=custom_retriever,
        enable_think=False,
        enable_analyze=False,
    )
    assert tools.search_knowledge(run_context=run_context, query="missing") == "No documents found"


def test_sync_search_rejects_async_retriever(run_context: RunContext):
    async def async_retriever(query: str, num_documents: Optional[int] = None, **kwargs: Any) -> List[dict]:
        return [{"content": "async"}]

    tools = KnowledgeTools(
        knowledge_retriever=async_retriever,
        enable_think=False,
        enable_analyze=False,
    )
    result = tools.search_knowledge(run_context=run_context, query="x")
    assert "async" in result
    assert "arun" in result
    assert "search_knowledge" in result


@pytest.mark.asyncio
async def test_async_search_awaits_async_retriever(run_context: RunContext):
    async def async_retriever(
        query: str,
        num_documents: Optional[int] = None,
        run_context: Optional[RunContext] = None,
        **kwargs: Any,
    ) -> List[dict]:
        return [{"content": f"async:{query}"}]

    tools = KnowledgeTools(
        knowledge_retriever=async_retriever,
        enable_think=False,
        enable_analyze=False,
    )
    result = await tools.asearch_knowledge(run_context=run_context, query="teams")
    assert json.loads(result) == [{"content": "async:teams"}]


@pytest.mark.asyncio
async def test_async_search_falls_back_to_aretrieve(run_context: RunContext):
    knowledge = MagicMock()
    knowledge.max_results = 2

    async def aretrieve(query: str, max_results: Optional[int] = None, filters: Any = None) -> List[Document]:
        return [Document(content=f"aretrieve:{query}:{max_results}")]

    knowledge.aretrieve = aretrieve
    tools = KnowledgeTools(knowledge=knowledge, enable_think=False, enable_analyze=False)
    result = await tools.asearch_knowledge(run_context=run_context, query="docs")
    docs = json.loads(result)
    assert docs[0]["content"] == "aretrieve:docs:2"


def test_registers_async_search_tool():
    tools = KnowledgeTools(
        knowledge_retriever=lambda query, num_documents=None, **kwargs: [],
        enable_think=False,
        enable_analyze=False,
    )
    assert "search_knowledge" in tools.functions
    assert "search_knowledge" in tools.async_functions


def test_retriever_receives_dependencies_when_requested(run_context: RunContext):
    run_context.dependencies = {"tenant": "acme"}
    seen: Dict[str, Any] = {}

    def custom_retriever(
        query: str,
        num_documents: Optional[int] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[dict]:
        seen["dependencies"] = dependencies
        return [{"content": "ok"}]

    tools = KnowledgeTools(
        knowledge_retriever=custom_retriever,
        enable_think=False,
        enable_analyze=False,
    )
    tools.search_knowledge(run_context=run_context, query="x")
    assert seen["dependencies"] == {"tenant": "acme"}
