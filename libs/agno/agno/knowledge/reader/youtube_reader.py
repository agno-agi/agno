import asyncio
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

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

# Path prefixes that carry the video id as the segment right after them.
_ID_PATH_PREFIXES = ("shorts", "embed", "live", "v")


def _is_host(host: str, domain: str) -> bool:
    """Whether ``host`` is ``domain`` or one of its subdomains."""
    return host == domain or host.endswith(f".{domain}")


def extract_video_id(url: str) -> str:
    """The video id of a YouTube URL: ``watch?v=``, ``youtu.be``, ``/shorts/``, ``/embed/``,
    ``/live/`` and ``/v/``. Anything else falls back to the historical ``v=`` split, so a
    bare id still works."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    segments = [segment for segment in parsed.path.split("/") if segment]
    if _is_host(host, "youtu.be"):
        if segments:
            return segments[0]
    elif _is_host(host, "youtube.com") or _is_host(host, "youtube-nocookie.com"):
        if len(segments) > 1 and segments[0] in _ID_PATH_PREFIXES:
            return segments[1]
    video_ids = parse_qs(parsed.query).get("v")
    if video_ids and video_ids[0]:
        return video_ids[0]
    return url.split("v=")[-1].split("&")[0]


class YouTubeReader(Reader):
    """Reader for YouTube video transcripts"""

    def __init__(self, chunking_strategy: Optional[ChunkingStrategy] = None, **kwargs):
        if chunking_strategy is None:
            chunk_size = kwargs.get("chunk_size", 5000)
            chunking_strategy = RecursiveChunking(chunk_size=chunk_size)
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
            video_id = extract_video_id(url)
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
            log_error(f"Error reading transcript for {url}: {str(e)}")
            return []

    async def async_read(self, url: str, name: Optional[str] = None) -> List[Document]:
        return await asyncio.get_running_loop().run_in_executor(None, self.read, url, name)
