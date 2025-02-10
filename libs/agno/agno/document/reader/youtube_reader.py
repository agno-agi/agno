from typing import List

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    raise ImportError(
        "`youtube_transcript_api` not installed. Please install it via `pip install youtube_transcript_api`."
    )


class YouTubeReader(Reader):
    """Reader for YouTube video transcripts"""

    def read(self, video_url: str) -> List[Document]:
        try:
            # Extract video ID from URL
            video_id = video_url.split("v=")[-1].split("&")[0]
            logger.info(f"Reading transcript for video: {video_id}")

            # Get transcript
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

            # Combine transcript segments into full text
            transcript_text = ""
            for segment in transcript_list:
                transcript_text += f"{segment['text']} "

            documents = [
                Document(
                    name=f"youtube_{video_id}",
                    id=f"youtube_{video_id}",
                    meta_data={"video_url": video_url, "video_id": video_id},
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
            logger.error(f"Error reading transcript for {video_url}: {e}")
            return []
