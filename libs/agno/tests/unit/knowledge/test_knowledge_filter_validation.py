from typing import List, Set

import pytest

from agno.filters import AND, EQ, GT, IN, LT, OR
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


def test_validate_filters_removes_invalid_dict_keys(knowledge):
    filters = {"region": "us", "invalid_key": "value"}
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    assert "region" in valid
    assert "invalid_key" not in valid
    assert "invalid_key" in invalid


def test_validate_filters_removes_invalid_list_items(knowledge):
    filters = [EQ("region", "us"), EQ("invalid_key", "value")]
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    valid_keys = [f.key for f in valid]
    assert "region" in valid_keys
    assert "invalid_key" not in valid_keys
    assert "invalid_key" in invalid


def test_validate_filters_keeps_complex_filters(knowledge):
    filters = [AND(EQ("region", "us"), EQ("year", 2024)), OR(EQ("region", "eu"))]
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    assert len(valid) == 2
    assert len(invalid) == 0


def test_validate_filters_with_gt_lt_in(knowledge):
    filters = [
        GT("price", 100),
        LT("date", "2024-01-01"),
        IN("category", ["tech", "science"]),
        GT("invalid_key", 50),
    ]
    valid_metadata: Set[str] = {"price", "date", "category"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    valid_keys = [f.key for f in valid]
    assert "price" in valid_keys
    assert "date" in valid_keys
    assert "category" in valid_keys
    assert len(valid) == 3
    assert "invalid_key" in invalid


def test_validate_filters_with_prefixed_keys(knowledge):
    filters = {"meta_data.region": "us", "meta_data.invalid": "value"}
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    assert "meta_data.region" in valid
    assert "meta_data.invalid" not in valid
    assert "meta_data.invalid" in invalid


def test_validate_filters_empty_metadata(knowledge):
    filters = [EQ("region", "us")]

    valid, invalid = knowledge._validate_filters(filters, set())

    assert valid == filters
    assert invalid == []


def test_validate_filters_mixed_valid_invalid_list(knowledge):
    filters = [
        EQ("region", "us"),
        EQ("invalid1", "value"),
        EQ("year", 2024),
        EQ("invalid2", "value"),
    ]
    valid_metadata: Set[str] = {"region", "year"}

    valid, invalid = knowledge._validate_filters(filters, valid_metadata)

    assert len(valid) == 2
    assert len(invalid) == 2
    valid_keys = [f.key for f in valid]
    assert "region" in valid_keys
    assert "year" in valid_keys
    assert "invalid1" in invalid
    assert "invalid2" in invalid


def test_filter_merge_raises_on_type_mismatch():
    from agno.utils.knowledge import get_agentic_or_user_search_filters

    with pytest.raises(ValueError):
        get_agentic_or_user_search_filters({"region": "us"}, [EQ("year", 2024)])
