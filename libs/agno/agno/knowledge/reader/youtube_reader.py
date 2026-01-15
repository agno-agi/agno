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

    def _extract_video_id(self, url: str) -> str:
        """Extract video ID from various YouTube URL formats.

        Supports:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST
        - https://youtu.be/VIDEO_ID
        - https://youtu.be/VIDEO_ID?t=TIMESTAMP

        Args:
            url: YouTube URL in any supported format

        Returns:
            The 11-character video ID

        Raises:
            ValueError: If URL format is not recognized or video ID is invalid
        """
        video_id = None

        # Handle youtu.be short URL format
        if "youtu.be/" in url:
            # Extract ID after youtu.be/ and before any query params
            video_id = url.split("youtu.be/")[-1].split("?")[0].split("&")[0]
        # Handle youtube.com/watch?v= format
        elif "v=" in url:
            video_id = url.split("v=")[-1].split("&")[0]

        # Validate video ID
        if not video_id:
            raise ValueError(f"Could not extract video ID from URL: {url}")

        # YouTube video IDs are exactly 11 characters
        if len(video_id) != 11:
            raise ValueError(
                f"Invalid video ID '{video_id}' extracted from URL: {url}. YouTube video IDs must be 11 characters."
            )

        return video_id

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
            # Extract video ID from URL (supports youtube.com and youtu.be formats)
            video_id = self._extract_video_id(url)
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

    async def async_read(self, url: str, name: Optional[str] = None) -> List[Document]:
        import functools

        return await asyncio.get_event_loop().run_in_executor(None, functools.partial(self.read, url, name=name))
