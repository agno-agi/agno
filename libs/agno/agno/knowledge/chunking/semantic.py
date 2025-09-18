import inspect
from typing import Any, Dict, List, Optional

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.knowledge.embedder.base import Embedder
from agno.knowledge.embedder.openai import OpenAIEmbedder


class SemanticChunking(ChunkingStrategy):
    """Chunking strategy that splits text into semantic chunks using chonkie"""

    def __init__(self, embedder: Optional[Embedder] = None, chunk_size: int = 5000, similarity_threshold: float = 0.5):
        self.embedder = embedder or OpenAIEmbedder(id="text-embedding-3-small")  # type: ignore
        self.chunk_size = chunk_size
        self.similarity_threshold = similarity_threshold
        self.chunker = None  # Will be initialized lazily when needed

    def _initialize_chunker(self):
        """Lazily initialize the chunker with chonkie dependency."""
        if self.chunker is None:
            try:
                from chonkie import SemanticChunker
            except ImportError:
                raise ImportError(
                    "`chonkie` is required for semantic chunking. "
                    "Please install it using `pip install chonkie` to use SemanticChunking."
                )

            # Build arguments dynamically based on chonkie's supported signature
            params: Dict[str, Any] = {
                "chunk_size": self.chunk_size,
                "threshold": self.similarity_threshold,
            }

            try:
                sig = inspect.signature(SemanticChunker)
                param_names = set(sig.parameters.keys())

                # Prefer passing a callable to avoid Chonkie initializing its own client
                if "embedding_fn" in param_names:
                    params["embedding_fn"] = self.embedder.get_embedding  # type: ignore[attr-defined]
                    # If chonkie allows specifying dimensions, provide them
                    if "embedding_dimensions" in param_names and getattr(self.embedder, "dimensions", None):
                        params["embedding_dimensions"] = self.embedder.dimensions  # type: ignore[attr-defined]
                elif "embedder" in param_names:
                    # Some versions may accept an embedder object directly
                    params["embedder"] = self.embedder
                else:
                    # Fallback to model id
                    params["embedding_model"] = getattr(self.embedder, "id", None) or "text-embedding-3-small"

                self.chunker = SemanticChunker(**params)
            except Exception:
                # As a final fallback, use the original behavior
                self.chunker = SemanticChunker(
                    embedding_model=getattr(self.embedder, "id", None) or "text-embedding-3-small",
                    chunk_size=self.chunk_size,
                    threshold=self.similarity_threshold,
                )

    def chunk(self, document: Document) -> List[Document]:
        """Split document into semantic chunks using chonkie"""
        if not document.content:
            return [document]

        # Ensure chunker is initialized (will raise ImportError if chonkie is missing)
        self._initialize_chunker()

        # Use chonkie to split into semantic chunks
        if self.chunker is None:
            raise RuntimeError("Chunker failed to initialize")

        chunks = self.chunker.chunk(self.clean_text(document.content))

        # Convert chunks to Documents
        chunked_documents: List[Document] = []
        for i, chunk in enumerate(chunks, 1):
            meta_data = document.meta_data.copy()
            meta_data["chunk"] = i
            chunk_id = f"{document.id}_{i}" if document.id else None
            meta_data["chunk_size"] = len(chunk.text)

            chunked_documents.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk.text))

        return chunked_documents
