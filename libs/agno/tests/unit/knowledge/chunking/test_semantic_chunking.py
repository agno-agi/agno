import sys
from types import ModuleType, SimpleNamespace

from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.document.base import Document


class DummyEmbedder:
    def __init__(self, id: str = "azure-embedding-deployment", dimensions: int = 1024):
        self.id = id
        self.dimensions = dimensions

    def get_embedding(self, text: str):
        return [0.0] * self.dimensions


def install_fake_chonkie(klass):
    mod = ModuleType("chonkie")
    setattr(mod, "SemanticChunker", klass)
    sys.modules["chonkie"] = mod
    return mod


def remove_fake_chonkie():
    sys.modules.pop("chonkie", None)


def test_semantic_chunking_uses_embedding_fn_when_supported():
    class FakeSemanticChunker:
        def __init__(self, *, embedding_fn, chunk_size, threshold, embedding_dimensions=None):
            self.embedding_fn = embedding_fn
            self.chunk_size = chunk_size
            self.threshold = threshold
            self.embedding_dimensions = embedding_dimensions

        def chunk(self, text: str):
            return [SimpleNamespace(text=text)]

    try:
        install_fake_chonkie(FakeSemanticChunker)

        embedder = DummyEmbedder(id="azure-deploy", dimensions=1536)
        sc = SemanticChunking(embedder=embedder, chunk_size=123, similarity_threshold=0.7)

        # Trigger initialization
        _ = sc.chunk(Document(content="Hello world"))

        fake = sc.chunker
        assert fake is not None
        # Compare bound method components rather than identity of bound method objects
        assert getattr(fake.embedding_fn, "__self__", None) is embedder
        assert getattr(fake.embedding_fn, "__func__", None) is getattr(embedder.get_embedding, "__func__", None)
        assert fake.embedding_dimensions == 1536
        assert fake.chunk_size == 123
        assert abs(fake.threshold - 0.7) < 1e-9
    finally:
        remove_fake_chonkie()


def test_semantic_chunking_uses_embedder_object_when_supported():
    class FakeSemanticChunker:
        def __init__(self, *, embedder, chunk_size, threshold):
            self.embedder = embedder
            self.chunk_size = chunk_size
            self.threshold = threshold

        def chunk(self, text: str):
            return [SimpleNamespace(text=text)]

    try:
        install_fake_chonkie(FakeSemanticChunker)

        embedder = DummyEmbedder(id="azure-deploy", dimensions=1536)
        sc = SemanticChunking(embedder=embedder, chunk_size=256, similarity_threshold=0.4)

        _ = sc.chunk(Document(content="Hello world"))

        fake = sc.chunker
        assert fake is not None
        assert fake.embedder is embedder
        assert fake.chunk_size == 256
        assert abs(fake.threshold - 0.4) < 1e-9
    finally:
        remove_fake_chonkie()


def test_semantic_chunking_falls_back_to_embedding_model_for_older_versions():
    class FakeSemanticChunker:
        def __init__(self, *, embedding_model, chunk_size, threshold):
            self.embedding_model = embedding_model
            self.chunk_size = chunk_size
            self.threshold = threshold

        def chunk(self, text: str):
            return [SimpleNamespace(text=text)]

    try:
        install_fake_chonkie(FakeSemanticChunker)

        embedder = DummyEmbedder(id="azure-deploy", dimensions=1536)
        sc = SemanticChunking(embedder=embedder, chunk_size=512, similarity_threshold=0.8)

        _ = sc.chunk(Document(content="Hello world"))

        fake = sc.chunker
        assert fake is not None
        assert fake.embedding_model == "azure-deploy"
        assert fake.chunk_size == 512
        assert abs(fake.threshold - 0.8) < 1e-9
    finally:
        remove_fake_chonkie()
