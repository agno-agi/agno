from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    async def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return []

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return []

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata) -> None:
        pass

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


@pytest.fixture
def knowledge():
    return Knowledge(vector_db=MockVectorDb())


def test_search_tool_catches_exceptions(knowledge):
    knowledge.search = MagicMock(side_effect=Exception("Connection refused"))

    tool = knowledge._create_search_tool(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result
    assert "Exception" in result


def test_search_tool_with_filters_catches_exceptions(knowledge):
    knowledge.search = MagicMock(side_effect=Exception("DB timeout"))

    tool = knowledge._create_search_tool_with_filters(async_mode=False)
    result = tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


@pytest.mark.asyncio
async def test_async_search_tool_catches_exceptions(knowledge):
    knowledge.asearch = AsyncMock(side_effect=Exception("Network error"))

    tool = knowledge._create_search_tool(async_mode=True)
    result = await tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


@pytest.mark.asyncio
async def test_async_search_tool_with_filters_catches_exceptions(knowledge):
    knowledge.asearch = AsyncMock(side_effect=Exception("Connection timeout"))

    tool = knowledge._create_search_tool_with_filters(async_mode=True)
    result = await tool.entrypoint(query="test")

    assert isinstance(result, str)
    assert "Error searching knowledge base" in result


def test_search_tool_does_not_leak_sensitive_info(knowledge):
    knowledge.search = MagicMock(side_effect=Exception("Connection failed: postgres://user:password@host:5432/db"))

    tool = knowledge._create_search_tool(async_mode=False)
    result = tool.entrypoint(query="test")

    assert "Exception" in result
    assert "password" not in result
