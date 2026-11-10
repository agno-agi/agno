from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.reader.youcom.contents_reader import YouContentsReader
from agno.knowledge.reader.youcom.finance_reader import YouFinanceResearchReader
from agno.knowledge.reader.youcom.research_reader import YouResearchReader
from agno.knowledge.reader.youcom.search_reader import YouSearchReader


def _mock_response(payload):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_search_reader_builds_documents_and_pads_timeout():
    payload = {
        "results": {
            "web": [
                {
                    "url": "https://example.com/article",
                    "title": "Example Title",
                    "description": "Example description",
                    "snippets": ["Snippet one", "Snippet two"],
                    "contents": {"markdown": "Live crawled body"},
                    "page_age": "2d",
                }
            ]
        }
    }

    with patch("agno.knowledge.reader.youcom.base.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.request.return_value = _mock_response(payload)

        reader = YouSearchReader(chunk=False, crawl_timeout=45, livecrawl="all", livecrawl_formats=("markdown", "html"))
        documents = reader.read("agno knowledge readers")

    assert len(documents) == 1
    document = documents[0]
    assert document.name == "Example Title"
    assert document.meta_data["source"] == "youcom_search"
    assert document.meta_data["section"] == "web"
    assert document.meta_data["page_age"] == "2d"
    assert "Example description" in document.content
    assert "Snippet one" in document.content
    assert "Live crawled body" in document.content

    mock_client_cls.assert_called_once_with(timeout=55)
    _, kwargs = mock_client.request.call_args
    assert kwargs["params"]["query"] == "agno knowledge readers"
    assert kwargs["params"]["crawl_timeout"] == 45
    assert kwargs["params"]["livecrawl_formats"] == ["markdown", "html"]


@pytest.mark.asyncio
async def test_search_reader_async_uses_async_client():
    payload = {
        "results": {
            "web": [
                {
                    "url": "https://example.com/article",
                    "title": "Async Example",
                    "description": "Async description",
                    "snippets": ["Async snippet"],
                }
            ]
        }
    }

    with patch("agno.knowledge.reader.youcom.base.httpx.AsyncClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__aenter__.return_value
        mock_client.request = AsyncMock(return_value=_mock_response(payload))

        reader = YouSearchReader(chunk=False)
        documents = await reader.async_read("agno async search")

    assert len(documents) == 1
    assert documents[0].name == "Async Example"
    mock_client_cls.assert_called_once_with(timeout=30)
    assert mock_client.request.await_count == 1


def test_contents_reader_builds_documents_and_metadata():
    payload = [
        {
            "url": "https://docs.agno.com",
            "title": "Agno Docs",
            "markdown": "# Agno\nDocs body",
            "metadata": {"json_ld": {"@type": "WebPage"}},
        }
    ]

    with patch("agno.knowledge.reader.youcom.base.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.request.return_value = _mock_response(payload)

        reader = YouContentsReader(chunk=False, crawl_timeout=40)
        documents = reader.read("https://docs.agno.com")

    assert len(documents) == 1
    document = documents[0]
    assert document.name == "Agno Docs"
    assert document.meta_data["url"] == "https://docs.agno.com"
    assert document.meta_data["metadata"] == {"json_ld": {"@type": "WebPage"}}
    assert "Docs body" in document.content
    mock_client_cls.assert_called_once_with(timeout=50)
    _, kwargs = mock_client.request.call_args
    assert kwargs["json"]["urls"] == ["https://docs.agno.com"]
    assert kwargs["json"]["formats"] == ["markdown", "metadata"]


@pytest.mark.asyncio
async def test_research_reader_async_uses_none_timeout():
    payload = {
        "output": {
            "content": "Answer with citations [[1]]",
            "content_type": "text",
            "sources": [{"url": "https://example.com", "title": "Example source"}],
        }
    }

    with patch("agno.knowledge.reader.youcom.base.httpx.AsyncClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__aenter__.return_value
        mock_client.request = AsyncMock(return_value=_mock_response(payload))

        reader = YouResearchReader(chunk=False, include_source_documents=True)
        documents = await reader.async_read("What is Agno?")

    assert len(documents) == 2
    assert documents[0].meta_data["source"] == "youcom_research"
    assert documents[0].meta_data["source_count"] == 1
    assert documents[1].meta_data["source"] == "youcom_research_source"
    mock_client_cls.assert_called_once_with(timeout=None)
    _, kwargs = mock_client.request.call_args
    assert kwargs["json"]["input"] == "What is Agno?"
    assert kwargs["json"]["research_effort"] == "deep"


def test_research_reader_builds_primary_and_source_documents():
    payload = {
        "output": {
            "content": "Finance answer",
            "content_type": "text",
            "sources": [
                {
                    "url": "https://sec.gov/1",
                    "title": "SEC filing",
                    "description": "Filing description",
                    "snippet": "Snippet from filing",
                }
            ],
        }
    }

    with patch("agno.knowledge.reader.youcom.base.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.request.return_value = _mock_response(payload)

        reader = YouResearchReader(chunk=False, research_effort="exhaustive", include_source_documents=True)
        documents = reader.read("NVIDIA fiscal 2025 drivers")

    assert len(documents) == 2
    assert documents[0].content == "Finance answer"
    assert documents[0].meta_data["research_effort"] == "exhaustive"
    assert documents[1].name == "SEC filing"
    assert "Snippet from filing" in documents[1].content
    mock_client_cls.assert_called_once_with(timeout=None)
    _, kwargs = mock_client.request.call_args
    assert kwargs["json"]["research_effort"] == "exhaustive"


def test_finance_reader_builds_documents():
    payload = {
        "output": {
            "content": "Finance answer with citations",
            "content_type": "text",
            "sources": [{"url": "https://sec.gov/2", "title": "10-K"}],
        }
    }

    with patch("agno.knowledge.reader.youcom.base.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.request.return_value = _mock_response(payload)

        reader = YouFinanceResearchReader(chunk=False)
        documents = reader.read("What drove revenue?")

    assert len(documents) == 1
    assert documents[0].name == "What drove revenue?"
    assert documents[0].meta_data["source_count"] == 1
    mock_client_cls.assert_called_once_with(timeout=None)
    _, kwargs = mock_client.request.call_args
    assert kwargs["json"]["input"] == "What drove revenue?"
    assert kwargs["json"]["research_effort"] == "deep"


def test_search_reader_returns_empty_list_on_request_error():
    with patch("agno.knowledge.reader.youcom.base.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.request.side_effect = httpx.TimeoutException("timed out")

        reader = YouSearchReader(chunk=False)
        documents = reader.read("agno")

    assert documents == []


def test_research_frontier_requires_background():
    reader = YouResearchReader(chunk=False, research_effort="frontier")
    with pytest.raises(ValueError, match="requires background=True"):
        reader.read("deep research")


def test_reader_factory_exposes_youcom_readers():
    ReaderFactory.clear_cache()

    assert "youcom_search" in ReaderFactory.get_all_reader_keys()
    assert "youcom_contents" in ReaderFactory.get_all_reader_keys()
    assert "youcom_research" in ReaderFactory.get_all_reader_keys()
    assert "youcom_finance" in ReaderFactory.get_all_reader_keys()

    assert isinstance(ReaderFactory.create_reader("youcom_search", api_key="test"), YouSearchReader)
    assert isinstance(ReaderFactory.create_reader("youcom_contents", api_key="test"), YouContentsReader)
    assert isinstance(ReaderFactory.create_reader("youcom_research", api_key="test"), YouResearchReader)
    assert isinstance(ReaderFactory.create_reader("youcom_finance", api_key="test"), YouFinanceResearchReader)
