from typing import Any, Dict, List, Literal, Optional, Union

try:
    from chonkie import CodeChunker
    from chonkie.tokenizer import TokenizerProtocol
except ImportError:
    raise ImportError(
        "`chonkie` is required for code chunking. "
        'Please install it using `pip install "chonkie[code]"` to use CodeChunking.'
    )

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


class CodeChunking(ChunkingStrategy):
    """Splits code into chunks based on its structure, leveraging Abstract Syntax Trees (ASTs) to create contextually relevant segments using Chonkie.

    Args:
        tokenizer: The tokenizer to use. Can be a string name or a TokenizerProtocol instance.
        chunk_size: The size of the chunks to create.
        language: The language to parse. Use "auto" for detection or specify a tree-sitter-language-pack language.
        include_nodes: Whether to include AST nodes (Note: Chonkie's base Chunk type does not store node information).
        chunker_params: Additional parameters to pass to Chonkie's CodeChunker.
    """

    def __init__(
        self,
        tokenizer: Union[str, TokenizerProtocol] = "character",
        chunk_size: int = 2048,
        language: Union[Literal["auto"], Any] = "auto",
        include_nodes: bool = False,
        chunker_params: Optional[Dict[str, Any]] = None,
    ):
        self.tokenizer = tokenizer
        self.chunk_size = chunk_size
        self.language = language
        self.include_nodes = include_nodes
        self.chunker_params = chunker_params
        self.chunker: Optional[CodeChunker] = None

    def _initialize_chunker(self):
        """Lazily initialize the chunker with Chonkie dependency."""
        if self.chunker is not None:
            return

        _chunker_params: Dict[str, Any] = {
            "tokenizer": self.tokenizer,
            "chunk_size": self.chunk_size,
            "language": self.language,
            "include_nodes": self.include_nodes,
        }
        if self.chunker_params:
            _chunker_params.update(self.chunker_params)

        try:
            self.chunker = CodeChunker(**_chunker_params)
        except ValueError as e:
            if "Tokenizer not found" in str(e):
                raise ImportError(
                    f"Missing dependencies for tokenizer `{self.tokenizer}`. "
                    f"Please install using `pip install tiktoken`, `pip install transformers`, or `pip install tokenizers`"
                ) from e
            raise

    def chunk(self, document: Document) -> List[Document]:
        """Split document into code chunks using Chonkie."""
        if not document.content:
            return [document]

        # Ensure chunker is initialized (will raise ImportError if Chonkie is missing)
        self._initialize_chunker()

        # Use Chonkie to split into code chunks
        if self.chunker is None:
            raise RuntimeError("Chunker failed to initialize")

        chunks = self.chunker.chunk(document.content)

        # Convert chunks to Documents
        chunked_documents: List[Document] = []
        for i, chunk in enumerate(chunks, 1):
            meta_data = document.meta_data.copy()
            meta_data["chunk"] = i
            chunk_id = self._generate_chunk_id(document, i, chunk.text)
            meta_data["chunk_size"] = len(chunk.text)

            chunked_documents.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk.text))

        return chunked_documents
