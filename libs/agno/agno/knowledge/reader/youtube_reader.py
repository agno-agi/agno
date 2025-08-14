import asyncio
from typing import List, Optional

from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.utils.log import log_info, logger

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    raise ImportError(
        "`youtube_transcript_api` not installed. Please install it via `pip install youtube_transcript_api`."
    )


class YouTubeReader(Reader):
    """Reader for YouTube video transcripts"""

    def read(self, url: str, name: Optional[str] = None) -> List[Document]:
        try:
            # Extract video ID from URL
            video_id = url.split("v=")[-1].split("&")[0]
            log_info(f"Reading transcript for video: {video_id}")

            # Get transcript
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
            logger.error(f"Error reading transcript for {url}: {e}")
            return []

    async def async_read(self, url: str) -> List[Document]:
        return await asyncio.get_event_loop().run_in_executor(None, self.read, url)
