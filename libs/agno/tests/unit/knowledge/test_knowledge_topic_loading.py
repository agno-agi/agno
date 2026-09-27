from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document import Document


class MockReader:
    def __init__(self):
        self.processed_topics: List[str] = []

    def read(self, topic) -> List[Document]:
        self.processed_topics.append(topic)
        return [Document(name=topic, content=f"Content for {topic}")]

    async def async_read(self, topic) -> List[Document]:
        self.processed_topics.append(topic)
        return [Document(name=topic, content=f"Content for {topic}")]


def _as_lightrag(vector_db) -> None:
    """Knowledge takes the LightRAG branch off the backend class name."""
    vector_db.__class__ = type("LightRag", (type(vector_db),), {})


@pytest.fixture
def mock_reader():
    return MockReader()


def test_load_from_topics_continues_after_skip(knowledge, mock_reader):
    skip_pattern = [True, False, False]
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists, user_id=None, prior_status=None):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    knowledge._should_skip = mock_should_skip
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()
    knowledge._handle_vector_db_insert = MagicMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._prepare_documents_for_insert = MagicMock()

    content = Content(topics=["A", "B", "C"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    assert "B" in mock_reader.processed_topics
    assert "C" in mock_reader.processed_topics


@pytest.mark.asyncio
async def test_aload_from_topics_continues_after_skip(knowledge):
    processed_topics = []

    skip_pattern = [True, False, False]
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists, user_id=None, prior_status=None):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    async def mock_async_read(topic):
        processed_topics.append(topic)
        return [Document(name=topic, content=f"Content for {topic}")]

    knowledge._should_skip = mock_should_skip
    knowledge._ainsert_contents_db = AsyncMock()
    knowledge._aupdate_content = AsyncMock()
    knowledge._ahandle_vector_db_insert = AsyncMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._prepare_documents_for_insert = MagicMock()

    mock_reader = MagicMock()
    mock_reader.async_read = mock_async_read
    content = Content(topics=["A", "B", "C"], reader=mock_reader)

    await knowledge._aload_from_topics(content, upsert=False, skip_if_exists=True)

    assert "B" in processed_topics
    assert "C" in processed_topics


def test_load_from_topics_multiple_skips(knowledge):
    mock_reader = MockReader()

    skip_pattern = [True, True, False, True, False]
    skip_index = [0]

    def mock_should_skip(content_hash, skip_if_exists, user_id=None, prior_status=None):
        result = skip_pattern[skip_index[0] % len(skip_pattern)]
        skip_index[0] += 1
        return result

    knowledge._should_skip = mock_should_skip
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()
    knowledge._handle_vector_db_insert = MagicMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._prepare_documents_for_insert = MagicMock()

    content = Content(topics=["A", "B", "C", "D", "E"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    assert mock_reader.processed_topics == ["C", "E"]


def test_load_from_topics_all_skipped(knowledge):
    mock_reader = MockReader()

    knowledge._should_skip = MagicMock(return_value=True)
    knowledge._insert_contents_db = MagicMock()
    knowledge._update_content = MagicMock()
    knowledge._build_content_hash = MagicMock(return_value="hash")

    content = Content(topics=["A", "B", "C"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=True)

    assert mock_reader.processed_topics == []
    assert knowledge._update_content.call_count == 3


def test_load_from_topics_lightrag_continues(knowledge):
    _as_lightrag(knowledge.vector_db)

    processed_topics = []
    knowledge._process_lightrag_content = MagicMock(
        side_effect=lambda content, origin: processed_topics.append(content.name)
    )
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._insert_contents_db = MagicMock()

    mock_reader = MagicMock()
    content = Content(topics=["A", "B", "C"], reader=mock_reader)
    knowledge._load_from_topics(content, upsert=False, skip_if_exists=False)

    assert len(processed_topics) == 3
    assert "A" in processed_topics
    assert "B" in processed_topics
    assert "C" in processed_topics


@pytest.mark.asyncio
async def test_aload_from_topics_lightrag_continues(knowledge):
    _as_lightrag(knowledge.vector_db)

    processed_topics = []

    async def mock_process_lightrag(content, origin):
        processed_topics.append(content.name)

    knowledge._aprocess_lightrag_content = mock_process_lightrag
    knowledge._build_content_hash = MagicMock(return_value="hash")
    knowledge._ainsert_contents_db = AsyncMock()

    mock_reader = MagicMock()
    content = Content(topics=["A", "B", "C"], reader=mock_reader)

    await knowledge._aload_from_topics(content, upsert=False, skip_if_exists=False)

    assert len(processed_topics) == 3
