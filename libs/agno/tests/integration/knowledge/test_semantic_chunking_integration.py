from types import ModuleType, SimpleNamespace
import sys

from agno.knowledge.chunking.strategy import ChunkingStrategyFactory, ChunkingStrategyType
from agno.knowledge.document.base import Document


class DummyEmbedder:
    def __init__(self, id: str = "azure-embedding-deployment", dimensions: int = 64):
        self.id = id
        self.dimensions = dimensions

    def get_embedding(self, text: str):
        # Return a deterministic fixed-size vector for integration flow
        return [0.1] * self.dimensions


def install_fake_chonkie(klass):
    mod = ModuleType("chonkie")
    setattr(mod, "SemanticChunker", klass)
    sys.modules["chonkie"] = mod


def remove_fake_chonkie():
    sys.modules.pop("chonkie", None)


def test_semantic_chunking_factory_integration_with_embedding_fn():
    class FakeSemanticChunker:
        def __init__(self, *, embedding_fn, chunk_size, threshold, embedding_dimensions=None):
            # Basic sanity: callable and dims propagated
            assert callable(embedding_fn)
            self.embedding_fn = embedding_fn
            self.chunk_size = chunk_size
            self.threshold = threshold
            self.embedding_dimensions = embedding_dimensions

        def chunk(self, text: str):
            # No real splitting; return one chunk to validate flow
            return [SimpleNamespace(text=text)]

    try:
        install_fake_chonkie(FakeSemanticChunker)

        embedder = DummyEmbedder(id="azure-deploy", dimensions=1536)
        chunker = ChunkingStrategyFactory.create_strategy(
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            embedder=embedder,
            chunk_size=200,
            similarity_threshold=0.6,
        )

        docs = chunker.chunk(Document(content="Hello integration world"))

        assert isinstance(docs, list)
        assert len(docs) == 1
        assert docs[0].content == "Hello integration world"

        # Access underlying chonkie instance to ensure arg propagation
        inner = getattr(chunker, "chunker", None)
        assert inner is not None
        assert getattr(inner, "embedding_dimensions", None) == 1536
        assert getattr(inner, "chunk_size", None) == 200
    finally:
        remove_fake_chonkie()


