"""Tests for insert_many() and ainsert_many() auth parameter passing."""

from unittest.mock import AsyncMock, patch

import pytest

from agno.knowledge.content import ContentAuth
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Minimal VectorDb stub for testing."""

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents, filters=None) -> None:
        pass

    async def async_insert(self, content_hash: str, documents, filters=None) -> None:
        pass

    def upsert(self, content_hash: str, documents, filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents, filters=None) -> None:
        pass

    def search(self, query: str, limit: int = 5, filters=None):
        return []

    async def async_search(self, query: str, limit: int = 5, filters=None):
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

    def get_supported_search_types(self):
        return ["vector"]


def test_insert_many_passes_auth_to_insert():
    """Test that insert_many() passes auth parameter to internal insert() calls."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    auth1 = ContentAuth(password="secret1")
    auth2 = ContentAuth(password="secret2")

    with patch.object(knowledge, "insert") as mock_insert:
        knowledge.insert_many(
            [
                {"text_content": "doc1", "auth": auth1},
                {"text_content": "doc2", "auth": auth2},
            ]
        )

        assert mock_insert.call_count == 2

        # Check first call has auth1
        call1_kwargs = mock_insert.call_args_list[0][1]
        assert call1_kwargs.get("auth") == auth1

        # Check second call has auth2
        call2_kwargs = mock_insert.call_args_list[1][1]
        assert call2_kwargs.get("auth") == auth2


def test_insert_many_passes_none_auth_when_not_provided():
    """Test that insert_many() passes None for auth when not provided."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    with patch.object(knowledge, "insert") as mock_insert:
        knowledge.insert_many(
            [
                {"text_content": "doc1"},
                {"text_content": "doc2"},
            ]
        )

        assert mock_insert.call_count == 2

        # Both calls should have auth=None
        for call in mock_insert.call_args_list:
            assert call[1].get("auth") is None


@pytest.mark.asyncio
async def test_ainsert_many_passes_auth_to_ainsert():
    """Test that ainsert_many() passes auth parameter to internal ainsert() calls."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    auth1 = ContentAuth(password="secret1")
    auth2 = ContentAuth(password="secret2")

    with patch.object(knowledge, "ainsert", new_callable=AsyncMock) as mock_ainsert:
        await knowledge.ainsert_many(
            [
                {"text_content": "doc1", "auth": auth1},
                {"text_content": "doc2", "auth": auth2},
            ]
        )

        assert mock_ainsert.call_count == 2

        # Check first call has auth1
        call1_kwargs = mock_ainsert.call_args_list[0][1]
        assert call1_kwargs.get("auth") == auth1

        # Check second call has auth2
        call2_kwargs = mock_ainsert.call_args_list[1][1]
        assert call2_kwargs.get("auth") == auth2


@pytest.mark.asyncio
async def test_ainsert_many_passes_none_auth_when_not_provided():
    """Test that ainsert_many() passes None for auth when not provided."""
    knowledge = Knowledge(vector_db=MockVectorDb())

    with patch.object(knowledge, "ainsert", new_callable=AsyncMock) as mock_ainsert:
        await knowledge.ainsert_many(
            [
                {"text_content": "doc1"},
                {"text_content": "doc2"},
            ]
        )

        assert mock_ainsert.call_count == 2

        # Both calls should have auth=None
        for call in mock_ainsert.call_args_list:
            assert call[1].get("auth") is None
