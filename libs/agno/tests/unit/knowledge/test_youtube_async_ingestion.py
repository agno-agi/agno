from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.content import Content
from agno.knowledge.reader.youtube_reader import YouTubeReader


@pytest.mark.asyncio
async def test_async_url_ingestion_preserves_youtube_name(knowledge, vector_db):
    url = "https://www.youtube.com/watch?v=test_video_id"
    content = Content(url=url, name="Product demo", reader=YouTubeReader(chunk=False))

    with patch("agno.knowledge.reader.youtube_reader.YouTubeTranscriptApi") as mock_api_class:
        mock_api_class.return_value.fetch.return_value = [MagicMock(text="Demo transcript")]
        await knowledge._aload_from_url(content, upsert=False, skip_if_exists=False)

    assert len(vector_db.inserted_documents) == 1
    assert vector_db.inserted_documents[0].name == "Product demo"
    assert vector_db.inserted_documents[0].content == "Demo transcript"
