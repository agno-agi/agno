from unittest.mock import patch

import pytest

from agno.document.base import Document
from agno.document.reader.youtube_reader import YouTubeReader


@pytest.fixture
def mock_transcript():
    return [
        {"text": "First segment", "start": 0.0, "duration": 2.0},
        {"text": "Second segment", "start": 2.0, "duration": 2.0},
        {"text": "Third segment", "start": 4.0, "duration": 2.0},
    ]


def test_read_video(mock_transcript):
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        # Ensure chunking is disabled
        reader.chunk = False
        documents = reader.read(video_url)

        assert len(documents) == 1
        assert documents[0].name == "youtube_test_video_id"
        assert documents[0].id == "youtube_test_video_id"
        assert documents[0].meta_data["video_url"] == video_url
        assert documents[0].meta_data["video_id"] == "test_video_id"
        assert documents[0].content == "First segment Second segment Third segment"


def test_read_video_with_chunking(mock_transcript):
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        reader.chunk = True
        reader.chunk_document = lambda doc: [
            Document(
                name=f"{doc.name}_chunk_{i}",
                id=f"{doc.id}_chunk_{i}",
                content=f"chunk_{i}",
                meta_data={"chunk": i, **doc.meta_data},
            )
            for i in range(2)
        ]

        documents = reader.read(video_url)

        assert len(documents) == 2
        assert all(doc.name.startswith("youtube_test_video_id_chunk_") for doc in documents)
        assert all(doc.id.startswith("youtube_test_video_id_chunk_") for doc in documents)
        assert all("chunk" in doc.meta_data for doc in documents)
        assert all("video_url" in doc.meta_data for doc in documents)
        assert all("video_id" in doc.meta_data for doc in documents)


def test_read_invalid_video_url():
    video_url = "invalid_url"

    reader = YouTubeReader()
    documents = reader.read(video_url)

    assert len(documents) == 0


def test_read_video_api_error():
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.side_effect = Exception("API Error")

        reader = YouTubeReader()
        documents = reader.read(video_url)

        assert len(documents) == 0


def test_read_large_transcript():
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    # Create a large transcript
    mock_transcript = [{"text": f"Segment {i}", "start": float(i), "duration": 1.0} for i in range(1000)]

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        # Ensure chunking is disabled
        reader.chunk = False
        documents = reader.read(video_url)

        assert len(documents) == 1
        assert documents[0].name == "youtube_test_video_id"
        assert documents[0].id == "youtube_test_video_id"
        assert all(f"Segment {i}" in documents[0].content for i in range(1000))


def test_read_video_with_params():
    video_url = "https://www.youtube.com/watch?v=test_video_id&t=30s"

    mock_transcript = [{"text": "Test content", "start": 0.0, "duration": 2.0}]

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        reader.chunk = False
        documents = reader.read(video_url)

        assert len(documents) == 1
        assert documents[0].name == "youtube_test_video_id"
        assert documents[0].meta_data["video_id"] == "test_video_id"


def test_read_video_unicode_content():
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    mock_transcript = [{"text": "Unicode content 值", "start": 0.0, "duration": 2.0}]

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        reader.chunk = False
        documents = reader.read(video_url)

        assert len(documents) == 1
        assert "Unicode content 值" in documents[0].content


@pytest.mark.asyncio
async def test_async_read_video(mock_transcript):
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        # Ensure chunking is disabled
        reader.chunk = False
        documents = await reader.async_read(video_url)

        assert len(documents) == 1
        assert documents[0].name == "youtube_test_video_id"
        assert documents[0].id == "youtube_test_video_id"
        assert documents[0].meta_data["video_url"] == video_url
        assert documents[0].meta_data["video_id"] == "test_video_id"
        assert documents[0].content == "First segment Second segment Third segment"


@pytest.mark.asyncio
async def test_async_read_video_with_chunking(mock_transcript):
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        reader.chunk = True
        reader.chunk_document = lambda doc: [
            Document(
                name=f"{doc.name}_chunk_{i}",
                id=f"{doc.id}_chunk_{i}",
                content=f"chunk_{i}",
                meta_data={"chunk": i, **doc.meta_data},
            )
            for i in range(2)
        ]

        documents = await reader.async_read(video_url)

        assert len(documents) == 2
        assert all(doc.name.startswith("youtube_test_video_id_chunk_") for doc in documents)
        assert all(doc.id.startswith("youtube_test_video_id_chunk_") for doc in documents)
        assert all("chunk" in doc.meta_data for doc in documents)
        assert all("video_url" in doc.meta_data for doc in documents)
        assert all("video_id" in doc.meta_data for doc in documents)


@pytest.mark.asyncio
async def test_async_read_invalid_video_url():
    video_url = "invalid_url"

    reader = YouTubeReader()
    documents = await reader.async_read(video_url)

    assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_read_video_api_error():
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.side_effect = Exception("API Error")

        reader = YouTubeReader()
        documents = await reader.async_read(video_url)

        assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_read_large_transcript():
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    # Create a large transcript
    mock_transcript = [{"text": f"Segment {i}", "start": float(i), "duration": 1.0} for i in range(1000)]

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        # Ensure chunking is disabled
        reader.chunk = False
        documents = await reader.async_read(video_url)

        assert len(documents) == 1
        assert documents[0].name == "youtube_test_video_id"
        assert documents[0].id == "youtube_test_video_id"
        assert all(f"Segment {i}" in documents[0].content for i in range(1000))


@pytest.mark.asyncio
async def test_async_read_video_with_params():
    video_url = "https://www.youtube.com/watch?v=test_video_id&t=30s"

    mock_transcript = [{"text": "Test content", "start": 0.0, "duration": 2.0}]

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        reader.chunk = False
        documents = await reader.async_read(video_url)

        assert len(documents) == 1
        assert documents[0].name == "youtube_test_video_id"
        assert documents[0].meta_data["video_id"] == "test_video_id"


@pytest.mark.asyncio
async def test_async_read_video_unicode_content():
    video_url = "https://www.youtube.com/watch?v=test_video_id"

    mock_transcript = [{"text": "Unicode content 值", "start": 0.0, "duration": 2.0}]

    with patch("agno.document.reader.youtube_reader.YouTubeTranscriptApi") as mock_api:
        mock_api.get_transcript.return_value = mock_transcript

        reader = YouTubeReader()
        reader.chunk = False
        documents = await reader.async_read(video_url)

        assert len(documents) == 1
        assert "Unicode content 值" in documents[0].content
