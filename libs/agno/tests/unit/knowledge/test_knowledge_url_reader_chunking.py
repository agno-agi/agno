import pytest

from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.vectordb.base import VectorDb


class RecordingVectorDb(VectorDb):
    def __init__(self):
        self.inserted = []

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

    def upsert_available(self) -> bool:
        return False

    def insert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted.append((content_hash, documents, filters))

    async def async_insert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted.append((content_hash, documents, filters))

    def upsert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted.append((content_hash, documents, filters))

    async def async_upsert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted.append((content_hash, documents, filters))

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


class NoChunkUrlReader(Reader):
    def __init__(self):
        super().__init__(chunk=False)
        self.chunk_calls = 0
        self.async_chunk_calls = 0

    @classmethod
    def get_supported_chunking_strategies(cls):
        return []

    @classmethod
    def get_supported_content_types(cls):
        return [ContentType.URL]

    def read(self, obj, name=None, password=None):
        return [Document(content="full document", meta_data={"url": obj})]

    async def async_read(self, obj, name=None, password=None):
        return [Document(content="full document", meta_data={"url": obj})]

    def chunk_document(self, document):
        self.chunk_calls += 1
        return [
            Document(content="chunk 1", meta_data=document.meta_data),
            Document(content="chunk 2", meta_data=document.meta_data),
        ]

    async def chunk_documents_async(self, documents):
        self.async_chunk_calls += 1
        return [
            Document(content="chunk 1", meta_data=documents[0].meta_data),
            Document(content="chunk 2", meta_data=documents[0].meta_data),
        ]


def test_insert_url_respects_reader_chunk_false():
    vector_db = RecordingVectorDb()
    reader = NoChunkUrlReader()
    knowledge = Knowledge(vector_db=vector_db)

    knowledge.insert(
        url="https://example.com/knowledge",
        reader=reader,
        upsert=False,
    )

    assert reader.chunk_calls == 0
    assert len(vector_db.inserted) == 1
    assert [doc.content for doc in vector_db.inserted[0][1]] == ["full document"]


@pytest.mark.asyncio
async def test_ainsert_url_respects_reader_chunk_false():
    vector_db = RecordingVectorDb()
    reader = NoChunkUrlReader()
    knowledge = Knowledge(vector_db=vector_db)

    await knowledge.ainsert(
        url="https://example.com/knowledge",
        reader=reader,
        upsert=False,
    )

    assert reader.async_chunk_calls == 0
    assert len(vector_db.inserted) == 1
    assert [doc.content for doc in vector_db.inserted[0][1]] == ["full document"]
