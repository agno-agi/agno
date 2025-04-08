from unittest.mock import Mock, patch

import arxiv
import pytest

from agno.document.reader.arxiv_reader import ArxivReader


@pytest.fixture
def mock_arxiv_result():
    result = Mock()
    result.title = "Test Paper"
    result.summary = "This is a test paper abstract"
    result.pdf_url = "https://arxiv.org/pdf/1234.5678"
    result.links = [Mock(href="https://arxiv.org/abs/1234.5678"), Mock(href="https://arxiv.org/pdf/1234.5678")]
    return result


@pytest.fixture
def mock_search_results(mock_arxiv_result):
    return [mock_arxiv_result for _ in range(2)]


def test_read_basic_query(mock_search_results):
    with patch("arxiv.Search") as mock_search:
        # Setup mock search
        mock_search.return_value.results.return_value = mock_search_results

        reader = ArxivReader()
        documents = reader.read("quantum computing")

        assert len(documents) == 2
        assert all(doc.name == "Test Paper" for doc in documents)
        assert all(doc.content == "This is a test paper abstract" for doc in documents)
        assert all(doc.meta_data["pdf_url"] == "https://arxiv.org/pdf/1234.5678" for doc in documents)
        assert all("https://arxiv.org/abs/1234.5678" in doc.meta_data["article_links"] for doc in documents)


def test_read_empty_results():
    with patch("arxiv.Search") as mock_search:
        # Setup mock search with no results
        mock_search.return_value.results.return_value = []

        reader = ArxivReader()
        documents = reader.read("nonexistent topic")

        assert len(documents) == 0


def test_read_max_results():
    with patch("arxiv.Search") as mock_search:
        # Create mock results
        mock_result = Mock()
        mock_result.title = "Test Paper"
        mock_result.summary = "Abstract"
        mock_result.pdf_url = "https://arxiv.org/pdf/1234.5678"
        mock_result.links = [Mock(href="https://arxiv.org/abs/1234.5678")]

        # Create a list generator that respects max_results
        def mock_results():
            for i in range(3):  # Only yield 3 results
                yield mock_result

        # Setup the mock to use our generator
        mock_search.return_value.results = mock_results

        reader = ArxivReader()
        reader.max_results = 3
        documents = reader.read("quantum computing")

        assert len(documents) == 3
        mock_search.assert_called_once_with(
            query="quantum computing", max_results=3, sort_by=arxiv.SortCriterion.Relevance
        )


def test_read_sort_criterion():
    with patch("arxiv.Search") as mock_search:
        reader = ArxivReader()
        reader.read("quantum computing")

        # Verify Search was called with correct sort criterion
        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        assert "sort_by" in kwargs
        assert kwargs["sort_by"] == reader.sort_by


def test_read_with_special_characters():
    with patch("arxiv.Search") as mock_search:
        mock_result = Mock()
        mock_result.title = "Test Paper"
        mock_result.summary = "Abstract"
        mock_result.pdf_url = "https://arxiv.org/pdf/1234.5678"
        mock_result.links = [Mock(href="https://arxiv.org/abs/1234.5678")]

        mock_search.return_value.results.return_value = [mock_result]

        reader = ArxivReader()
        documents = reader.read("quantum & computing + AI")

        assert len(documents) == 1
        mock_search.assert_called_once_with(
            query="quantum & computing + AI", max_results=reader.max_results, sort_by=reader.sort_by
        )


def test_read_different_sort_criterions():
    with patch("arxiv.Search") as mock_search:
        # Test with different sort criterions
        reader = ArxivReader()

        # Test with LastUpdatedDate
        reader.sort_by = arxiv.SortCriterion.LastUpdatedDate
        reader.read("quantum computing")
        mock_search.assert_called_with(
            query="quantum computing", max_results=reader.max_results, sort_by=arxiv.SortCriterion.LastUpdatedDate
        )

        # Test with SubmittedDate
        reader.sort_by = arxiv.SortCriterion.SubmittedDate
        reader.read("quantum computing")
        mock_search.assert_called_with(
            query="quantum computing", max_results=reader.max_results, sort_by=arxiv.SortCriterion.SubmittedDate
        )


@pytest.mark.asyncio
async def test_async_read_basic_query(mock_search_results):
    with patch("arxiv.Search") as mock_search:
        # Setup mock search
        mock_search.return_value.results.return_value = mock_search_results

        reader = ArxivReader()
        documents = await reader.async_read("quantum computing")

        assert len(documents) == 2
        assert all(doc.name == "Test Paper" for doc in documents)
        assert all(doc.content == "This is a test paper abstract" for doc in documents)
        assert all(doc.meta_data["pdf_url"] == "https://arxiv.org/pdf/1234.5678" for doc in documents)
        assert all("https://arxiv.org/abs/1234.5678" in doc.meta_data["article_links"] for doc in documents)


@pytest.mark.asyncio
async def test_async_read_empty_results():
    with patch("arxiv.Search") as mock_search:
        # Setup mock search with no results
        mock_search.return_value.results.return_value = []

        reader = ArxivReader()
        documents = await reader.async_read("nonexistent topic")

        assert len(documents) == 0


@pytest.mark.asyncio
async def test_async_read_max_results():
    with patch("arxiv.Search") as mock_search:
        # Create mock results
        mock_result = Mock()
        mock_result.title = "Test Paper"
        mock_result.summary = "Abstract"
        mock_result.pdf_url = "https://arxiv.org/pdf/1234.5678"
        mock_result.links = [Mock(href="https://arxiv.org/abs/1234.5678")]

        # Create a list generator that respects max_results
        def mock_results():
            for i in range(3):  # Only yield 3 results
                yield mock_result

        # Setup the mock to use our generator
        mock_search.return_value.results = mock_results

        reader = ArxivReader()
        reader.max_results = 3
        documents = await reader.async_read("quantum computing")

        assert len(documents) == 3
        mock_search.assert_called_once_with(
            query="quantum computing", max_results=3, sort_by=arxiv.SortCriterion.Relevance
        )


@pytest.mark.asyncio
async def test_async_read_sort_criterion():
    with patch("arxiv.Search") as mock_search:
        reader = ArxivReader()
        await reader.async_read("quantum computing")

        # Verify Search was called with correct sort criterion
        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        assert "sort_by" in kwargs
        assert kwargs["sort_by"] == reader.sort_by


@pytest.mark.asyncio
async def test_async_read_with_special_characters():
    with patch("arxiv.Search") as mock_search:
        mock_result = Mock()
        mock_result.title = "Test Paper"
        mock_result.summary = "Abstract"
        mock_result.pdf_url = "https://arxiv.org/pdf/1234.5678"
        mock_result.links = [Mock(href="https://arxiv.org/abs/1234.5678")]

        mock_search.return_value.results.return_value = [mock_result]

        reader = ArxivReader()
        documents = await reader.async_read("quantum & computing + AI")

        assert len(documents) == 1
        mock_search.assert_called_once_with(
            query="quantum & computing + AI", max_results=reader.max_results, sort_by=reader.sort_by
        )
