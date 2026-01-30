from typing import Any, Dict, List, Literal, Optional, Union

try:
    import numpy as np
except ImportError:
    raise ImportError("`numpy` not installed. Please install using `pip install numpy`")

try:
    from chonkie import SemanticChunker
    from chonkie.embeddings.base import BaseEmbeddings
except ImportError:
    raise ImportError(
        "`chonkie` is required for semantic chunking. "
        'Please install it using `pip install "chonkie[semantic]"` to use SemanticChunking.'
    )

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.knowledge.embedder.base import Embedder
from agno.utils.log import log_debug


def _get_chonkie_embedder_wrapper(embedder: Embedder):
    """Create a wrapper that adapts Agno Embedder to chonkie's BaseEmbeddings interface."""

    class _ChonkieEmbedderWrapper(BaseEmbeddings):
        """Wrapper to make Agno Embedders compatible with chonkie."""

        def __init__(self, agno_embedder: Embedder):
            super().__init__()
            self._embedder = agno_embedder

        def embed(self, text: str):
            embedding = self._embedder.get_embedding(text)  # type: ignore[attr-defined]
            return np.array(embedding, dtype=np.float32)

        def get_tokenizer(self):
            """Return a simple token counter function."""
            return lambda text: len(text.split())

        @property
        def dimension(self) -> int:
            return getattr(self._embedder, "dimensions")

    return _ChonkieEmbedderWrapper(embedder)


class SemanticChunking(ChunkingStrategy):
    """Chunking strategy that splits text into semantic chunks using chonkie.

    Args:
        embedder: The embedder to use for generating embeddings. Can be:
            - A string model identifier (e.g., "minishlab/potion-base-32M") for chonkie's built-in models
            - A chonkie BaseEmbeddings instance (used directly)
            - An Agno Embedder (wrapped for chonkie compatibility)
        chunk_size: Maximum tokens allowed per chunk.
        similarity_threshold: Threshold for semantic similarity (0-1).
        similarity_window: Number of sentences to consider for similarity calculation.
        min_sentences_per_chunk: Minimum number of sentences per chunk.
        min_characters_per_sentence: Minimum number of characters per sentence.
        delimiters: Delimiters to use for sentence splitting.
        include_delimiters: Whether to include delimiter in prev/next sentence or None.
        skip_window: Number of groups to skip when merging (0=disabled).
        filter_window: Window length for the Savitzky-Golay filter.
        filter_polyorder: Polynomial order for the Savitzky-Golay filter.
        filter_tolerance: Tolerance for the Savitzky-Golay filter.
        chunker_params: Additional parameters to pass to chonkie's SemanticChunker.
    """

    def __init__(
        self,
        embedder: Optional[Union[str, Embedder, BaseEmbeddings]] = None,
        chunk_size: int = 5000,
        similarity_threshold: float = 0.5,
        similarity_window: int = 3,
        min_sentences_per_chunk: int = 1,
        min_characters_per_sentence: int = 24,
        delimiters: Optional[List[str]] = None,
        include_delimiters: Literal["prev", "next", None] = "prev",
        skip_window: int = 0,
        filter_window: int = 5,
        filter_polyorder: int = 3,
        filter_tolerance: float = 0.2,
        chunker_params: Optional[Dict[str, Any]] = None,
    ):
        if embedder is None:
            from agno.knowledge.embedder.openai import OpenAIEmbedder

            embedder = OpenAIEmbedder()  # type: ignore
            log_debug("Embedder not provided, using OpenAIEmbedder as default.")
        self.embedder = embedder
        self.chunk_size = chunk_size
        self.similarity_threshold = similarity_threshold
        self.similarity_window = similarity_window
        self.min_sentences_per_chunk = min_sentences_per_chunk
        self.min_characters_per_sentence = min_characters_per_sentence
        self.delimiters = delimiters if delimiters is not None else [". ", "! ", "? ", "\n"]
        self.include_delimiters = include_delimiters
        self.skip_window = skip_window
        self.filter_window = filter_window
        self.filter_polyorder = filter_polyorder
        self.filter_tolerance = filter_tolerance
        self.chunker_params = chunker_params
        self.chunker: Optional[SemanticChunker] = None

    def _initialize_chunker(self):
        """Lazily initialize the chunker with chonkie dependency."""
        if self.chunker is not None:
            return

        # Determine embedding model based on type:
        # - str: pass directly to chonkie (uses chonkie's built-in models)
        # - BaseEmbeddings: pass directly to chonkie
        # - Agno Embedder: wrap for chonkie compatibility
        embedding_model: Union[str, BaseEmbeddings]
        if isinstance(self.embedder, str):
            embedding_model = self.embedder
        elif isinstance(self.embedder, BaseEmbeddings):
            embedding_model = self.embedder
        elif isinstance(self.embedder, Embedder):
            embedding_model = _get_chonkie_embedder_wrapper(self.embedder)
        else:
            raise ValueError("Invalid embedder type. Must be a string, BaseEmbeddings, or Embedder instance.")

        _chunker_params: Dict[str, Any] = {
            "embedding_model": embedding_model,
            "chunk_size": self.chunk_size,
            "threshold": self.similarity_threshold,
            "similarity_window": self.similarity_window,
            "min_sentences_per_chunk": self.min_sentences_per_chunk,
            "min_characters_per_sentence": self.min_characters_per_sentence,
            "delim": self.delimiters,
            "include_delim": self.include_delimiters,
            "skip_window": self.skip_window,
            "filter_window": self.filter_window,
            "filter_polyorder": self.filter_polyorder,
            "filter_tolerance": self.filter_tolerance,
        }
        if self.chunker_params:
            _chunker_params.update(self.chunker_params)

        self.chunker = SemanticChunker(**_chunker_params)

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
            chunk_id = self._generate_chunk_id(document, i, chunk.text)
            meta_data["chunk_size"] = len(chunk.text)

            chunked_documents.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk.text))

        return chunked_documents
