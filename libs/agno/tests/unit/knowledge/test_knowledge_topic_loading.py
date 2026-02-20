from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    def __init__(self, content_exists: bool = False):
        self.content_exists = content_exists
        self.inserted_documents: List[Document] = []

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
        return self.content_exists

    def insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.inserted_documents.extend(documents)

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.inserted_documents.extend(documents)

    def upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.inserted_documents.extend(documents)

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.inserted_documents.extend(documents)

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


class MockReader:
    def __init__(self):
        self.processed_topics: List[str] = []

    def read(self, topic) -> List[Document]:
        self.processed_topics.append(topic)
        return [Document(name=topic, content=f"Content for {topic}")]

    async def async_read(self, topic) -> List[Document]:
        self.processed_topics.append(topic)
        return [Document(name=topic, content=f"Content for {topic}")]


@pytest.fixture
def mock_reader():
    return MockReader()


def test_load_from_topics_continues_after_skip(mock_reader):
    knowledge = Knowledge(vector_db=MockVectorDb())

    skip_pattern = [True, False, False]
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    pipeline = knowledge._pipeline
    pipeline.should_skip = mock_should_skip
    pipeline.content_store.insert = MagicMock()
    pipeline.content_store.update = MagicMock()
    pipeline.handle_vector_db_insert = MagicMock()
    pipeline.build_content_hash = MagicMock(return_value="hash")
    pipeline.prepare_documents_for_insert = MagicMock()

    content = Content(topics=["A", "B", "C"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    assert "B" in mock_reader.processed_topics
    assert "C" in mock_reader.processed_topics


@pytest.mark.asyncio
async def test_aload_from_topics_continues_after_skip():
    knowledge = Knowledge(vector_db=MockVectorDb())
    processed_topics = []

    skip_pattern = [True, False, False]
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    async def mock_async_read(topic):
        processed_topics.append(topic)
        return [Document(name=topic, content=f"Content for {topic}")]

    pipeline = knowledge._pipeline
    pipeline.should_skip = mock_should_skip
    pipeline.content_store.ainsert = AsyncMock()
    pipeline.content_store.aupdate = AsyncMock()
    pipeline.ahandle_vector_db_insert = AsyncMock()
    pipeline.build_content_hash = MagicMock(return_value="hash")
    pipeline.prepare_documents_for_insert = MagicMock()

    mock_reader = MagicMock()
    mock_reader.async_read = mock_async_read
    content = Content(topics=["A", "B", "C"], reader=mock_reader)

    await knowledge._aload_from_topics(content, upsert=False, skip_if_exists=True)

    assert "B" in processed_topics
    assert "C" in processed_topics


def test_load_from_topics_multiple_skips():
    knowledge = Knowledge(vector_db=MockVectorDb())
    mock_reader = MockReader()

    skip_pattern = [True, True, False, True, False]
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    pipeline = knowledge._pipeline
    pipeline.should_skip = mock_should_skip
    pipeline.content_store.insert = MagicMock()
    pipeline.content_store.update = MagicMock()
    pipeline.handle_vector_db_insert = MagicMock()
    pipeline.build_content_hash = MagicMock(return_value="hash")
    pipeline.prepare_documents_for_insert = MagicMock()

    content = Content(topics=["A", "B", "C", "D", "E"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    assert mock_reader.processed_topics == ["C", "E"]


def test_load_from_topics_all_skipped():
    knowledge = Knowledge(vector_db=MockVectorDb())
    mock_reader = MockReader()

    pipeline = knowledge._pipeline
    pipeline.should_skip = MagicMock(return_value=True)
    pipeline.content_store.insert = MagicMock()
    pipeline.content_store.update = MagicMock()
    pipeline.build_content_hash = MagicMock(return_value="hash")

    content = Content(topics=["A", "B", "C"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    assert mock_reader.processed_topics == []
    assert pipeline.content_store.update.call_count == 3


def test_load_from_topics_lightrag_continues():
    knowledge = Knowledge(vector_db=MockVectorDb())
    knowledge.vector_db.__class__.__name__ = "LightRag"

    processed_topics = []
    pipeline = knowledge._pipeline
    pipeline.process_lightrag_content = MagicMock(
        side_effect=lambda content, origin: processed_topics.append(content.name)
    )
    pipeline.build_content_hash = MagicMock(return_value="hash")
    pipeline.content_store.insert = MagicMock()

    mock_reader = MagicMock()
    content = Content(topics=["A", "B", "C"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=False)

    assert len(processed_topics) == 3
    assert "A" in processed_topics
    assert "B" in processed_topics
    assert "C" in processed_topics


@pytest.mark.asyncio
async def test_aload_from_topics_lightrag_continues():
    knowledge = Knowledge(vector_db=MockVectorDb())
    knowledge.vector_db.__class__.__name__ = "LightRag"

    processed_topics = []

    async def mock_process_lightrag(content, origin):
        processed_topics.append(content.name)

    pipeline = knowledge._pipeline
    pipeline.aprocess_lightrag_content = mock_process_lightrag
    pipeline.build_content_hash = MagicMock(return_value="hash")
    pipeline.content_store.ainsert = AsyncMock()

    mock_reader = MagicMock()
    content = Content(topics=["A", "B", "C"], reader=mock_reader)

    await knowledge._aload_from_topics(content, upsert=False, skip_if_exists=False)

    assert len(processed_topics) == 3
