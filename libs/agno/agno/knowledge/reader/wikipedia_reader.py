from typing import List, Optional

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_info

try:
    import wikipedia  # noqa: F401
except ImportError:
    raise ImportError("The `wikipedia` package is not installed. Please install it via `pip install wikipedia`.")


class WikipediaReader(Reader):
    auto_suggest: bool = True

    def __init__(
        self, chunking_strategy: Optional[ChunkingStrategy] = FixedSizeChunking(), auto_suggest: bool = True, **kwargs
    ):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)
        self.auto_suggest = auto_suggest

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for Wikipedia readers."""
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.TOPIC]

    def read(self, topic: str) -> List[Document]:
        log_debug(f"Reading Wikipedia topic: {topic}")
        summary = None
        try:
            summary = wikipedia.summary(topic, auto_suggest=self.auto_suggest)

        except wikipedia.exceptions.PageError:
            summary = None
            log_info("PageError: Page not found.")

        # Only create Document if we successfully got a summary
        if summary:
            return [
                Document(
                    name=topic,
                    meta_data={"topic": topic},
                    content=summary,
                )
            ]
        return []
