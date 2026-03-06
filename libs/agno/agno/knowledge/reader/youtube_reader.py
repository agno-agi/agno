import asyncio
from typing import List, Optional

from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error, log_info

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    raise ImportError(
        "`youtube_transcript_api` not installed. Please install it via `pip install youtube_transcript_api`."
    )


class YouTubeReader(Reader):
    """Reader for YouTube video transcripts"""

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = RecursiveChunking(), **kwargs):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for YouTube readers."""
        return [
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.YOUTUBE]

    def read(self, url: str, name: Optional[str] = None) -> List[Document]:
        try:
            # Extract video ID from URL
            video_id = url.split("v=")[-1].split("&")[0]
            log_info(f"Reading transcript for video: {video_id}")

            # Get transcript
            log_debug(f"Fetching transcript for video: {video_id}")
            # Create an instance of YouTubeTranscriptApi
            ytt_api = YouTubeTranscriptApi()
            transcript_data = ytt_api.fetch(video_id)

            # Combine transcript segments into full text
            transcript_text = ""
            for segment in transcript_data:
                transcript_text += f"{segment.text} "

            documents = [
                Document(
                    name=name or f"youtube_{video_id}",
                    id=f"youtube_{video_id}",
                    meta_data={"video_url": url, "video_id": video_id},
                    content=transcript_text.strip(),
                )
            ]

            if self.chunk:
                chunked_documents = []
                for document in documents:
                    chunked_documents.extend(self.chunk_document(document))
                return chunked_documents
            return documents

        except Exception as e:
            log_error(f"Error reading transcript for {url}: {e}")
            return []

    async def async_read(self, url: str) -> List[Document]:
        return await asyncio.get_event_loop().run_in_executor(None, self.read, url)
