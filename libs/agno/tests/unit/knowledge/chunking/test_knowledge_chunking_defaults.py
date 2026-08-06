from typing import List

import pytest

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.row import RowChunking
from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader import ReaderFactory
from agno.knowledge.reader.text_reader import TextReader
from agno.vectordb.base import VectorDb


class CapturingVectorDb(VectorDb):
    def __init__(self):
        self.inserted_documents: List[Document] = []

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
        self.inserted_documents.extend(documents)

    async def async_insert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted_documents.extend(documents)

    def upsert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted_documents.extend(documents)

    async def async_upsert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted_documents.extend(documents)

    def upsert_available(self) -> bool:
        return False

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

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata) -> None:
        pass

    def get_supported_search_types(self):
        return ["vector"]


@pytest.fixture(autouse=True)
def clear_reader_factory_cache():
    ReaderFactory.clear_cache()
    yield
    ReaderFactory.clear_cache()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"chunk_size": 0}, "chunk_size must be greater than 0"),
        ({"chunk_size": -1}, "chunk_size must be greater than 0"),
        ({"chunk_size": True}, "chunk_size must be an integer"),
        ({"chunk_overlap": -1}, "chunk_overlap must be greater than or equal to 0"),
        ({"chunk_overlap": False}, "chunk_overlap must be an integer"),
        (
            {"chunk_size": 100, "chunk_overlap": 100},
            "chunk_overlap must be less than chunk_size",
        ),
        (
            {"chunk_size": 100, "chunk_overlap": 101},
            "chunk_overlap must be less than chunk_size",
        ),
    ],
)
def test_knowledge_validates_chunking_defaults(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Knowledge(**kwargs)


def test_none_defaults_preserve_shared_factory_reader_behavior():
    first = Knowledge()
    second = Knowledge()

    assert first.text_reader is second.text_reader
    assert first.text_reader.chunk_size == 5000
    assert isinstance(first.text_reader.chunking_strategy, FixedSizeChunking)
    assert first.text_reader.chunking_strategy.overlap == 0


def test_knowledge_defaults_configure_automatic_reader():
    knowledge = Knowledge(chunk_size=100, chunk_overlap=20)

    reader = knowledge.text_reader

    assert reader.chunk_size == 100
    assert isinstance(reader.chunking_strategy, FixedSizeChunking)
    assert reader.chunking_strategy.chunk_size == 100
    assert reader.chunking_strategy.overlap == 20


def test_chunk_size_default_can_be_configured_independently():
    knowledge = Knowledge(chunk_size=100)

    reader = knowledge.text_reader

    assert reader.chunk_size == 100
    assert reader.chunking_strategy.chunk_size == 100
    assert reader.chunking_strategy.overlap == 0


def test_chunk_overlap_default_can_be_configured_independently():
    knowledge = Knowledge(chunk_overlap=20)

    reader = knowledge.text_reader

    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert reader.chunking_strategy.overlap == 20


def test_configured_readers_are_isolated_from_other_knowledge_and_factory_cache():
    cached_reader = ReaderFactory.create_reader("text")
    first = Knowledge(chunk_size=100, chunk_overlap=10)
    second = Knowledge(chunk_size=200, chunk_overlap=20)

    first_reader = first.text_reader
    second_reader = second.text_reader

    assert first_reader is not second_reader
    assert first_reader is not cached_reader
    assert second_reader is not cached_reader
    assert first_reader.chunking_strategy.chunk_size == 100
    assert second_reader.chunking_strategy.chunk_size == 200
    assert cached_reader.chunking_strategy.chunk_size == 5000
    assert cached_reader.chunking_strategy.overlap == 0


def test_reader_factory_keeps_existing_public_cache_behavior():
    first = ReaderFactory.create_reader("text", chunk_size=100)
    second = ReaderFactory.create_reader("text", chunk_size=200)

    assert second is first
    assert second.chunking_strategy.chunk_size == 100


def test_explicit_reader_configuration_takes_precedence():
    strategy = FixedSizeChunking(chunk_size=250, overlap=25)
    explicit_reader = TextReader(chunk_size=250, chunking_strategy=strategy)
    knowledge = Knowledge(
        chunk_size=100,
        chunk_overlap=10,
        readers={"text": explicit_reader},
    )

    assert knowledge.text_reader is explicit_reader
    assert explicit_reader.chunk_size == 250
    assert explicit_reader.chunking_strategy is strategy
    assert strategy.chunk_size == 250
    assert strategy.overlap == 25


def test_per_content_reader_configuration_takes_precedence():
    strategy = FixedSizeChunking(chunk_size=250, overlap=25)
    explicit_reader = TextReader(chunk_size=250, chunking_strategy=strategy)
    vector_db = CapturingVectorDb()
    knowledge = Knowledge(vector_db=vector_db, chunk_size=20, chunk_overlap=5)

    knowledge.insert(
        text_content="alpha beta gamma delta epsilon zeta eta theta",
        reader=explicit_reader,
        upsert=False,
    )

    assert explicit_reader.chunk_size == 250
    assert explicit_reader.chunking_strategy is strategy
    assert strategy.chunk_size == 250
    assert strategy.overlap == 25
    assert len(vector_db.inserted_documents) == 1


def test_knowledge_defaults_do_not_replace_unsupported_row_strategy():
    knowledge = Knowledge(chunk_size=100, chunk_overlap=10)

    reader = knowledge.csv_reader

    assert isinstance(reader.chunking_strategy, RowChunking)


def test_overlap_only_is_validated_against_effective_reader_chunk_size():
    knowledge = Knowledge(chunk_overlap=5000)

    with pytest.raises(ValueError, match="chunk_overlap must be less than the reader chunk size"):
        _ = knowledge.text_reader


def test_sync_text_ingestion_uses_knowledge_chunking_defaults():
    vector_db = CapturingVectorDb()
    knowledge = Knowledge(vector_db=vector_db, chunk_size=20, chunk_overlap=5)

    knowledge.insert(text_content="alpha beta gamma delta epsilon zeta eta theta", upsert=False)

    contents = [document.content for document in vector_db.inserted_documents]
    assert len(contents) > 1
    assert all(len(content) <= 20 for content in contents)
    assert contents[0][-5:] == contents[1][:5]


@pytest.mark.asyncio
async def test_async_text_ingestion_matches_sync_chunking_defaults():
    text = "alpha beta gamma delta epsilon zeta eta theta"
    sync_db = CapturingVectorDb()
    async_db = CapturingVectorDb()

    Knowledge(vector_db=sync_db, chunk_size=20, chunk_overlap=5).insert(text_content=text, upsert=False)
    await Knowledge(vector_db=async_db, chunk_size=20, chunk_overlap=5).ainsert(text_content=text, upsert=False)

    assert [document.content for document in async_db.inserted_documents] == [
        document.content for document in sync_db.inserted_documents
    ]


def test_local_path_uses_knowledge_configured_reader(tmp_path):
    path = tmp_path / "knowledge-defaults.txt"
    path.write_text("alpha beta gamma delta epsilon zeta eta theta", encoding="utf-8")
    vector_db = CapturingVectorDb()
    cached_reader = ReaderFactory.create_reader("text")
    knowledge = Knowledge(vector_db=vector_db, chunk_size=20, chunk_overlap=5)

    knowledge.insert(path=str(path), upsert=False)

    assert len(vector_db.inserted_documents) > 1
    assert knowledge.text_reader is not cached_reader
    assert cached_reader.chunking_strategy.chunk_size == 5000
