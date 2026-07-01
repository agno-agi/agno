"""Unit tests for OlostepTools class."""

import json
import os
from unittest.mock import Mock, patch

import pytest

# Skip all tests in this module if olostep is not installed
pytest.importorskip("olostep")

from olostep import Olostep, Olostep_BaseError  # noqa

from agno.tools.olostep import OlostepTools


@pytest.fixture
def mock_olostep_client():
    """Create a mock Olostep client."""
    mock_client = Mock()

    # Mock scrape response
    mock_scrape_result = Mock()
    mock_scrape_result.markdown_content = "# Test Page\n\nTest content"
    mock_scrape_result.text_content = "Test Page\n\nTest content"
    mock_scrape_result.html_content = "<html><body>Test content</body></html>"
    mock_scrape_result.json_content = '{"title": "Test Page"}'
    mock_client.scrapes.create.return_value = mock_scrape_result

    # Mock crawl response
    mock_page = Mock()
    mock_page.url = "https://example.com/page1"
    mock_page_content = Mock()
    mock_page_content.markdown_content = "# Page 1"
    mock_page.retrieve.return_value = mock_page_content

    mock_crawl_result = Mock()
    mock_crawl_result.pages.return_value = [mock_page]
    mock_client.crawls.create.return_value = mock_crawl_result

    # Mock map response
    mock_map_result = Mock()
    mock_map_result.urls.return_value = ["https://example.com/page1", "https://example.com/page2"]
    mock_client.maps.create.return_value = mock_map_result

    # Mock search response
    mock_link = Mock()
    mock_link.url = "https://example.com"
    mock_link.title = "Example Site"
    mock_link.description = "Example description"
    mock_search_result = Mock()
    mock_search_result.result = Mock()
    mock_search_result.result.links = [mock_link]
    mock_client.searches.create.return_value = mock_search_result

    # Mock answer response
    mock_answer_result = Mock()
    mock_answer_result.answer = "The answer to your question is..."
    mock_answer_result.result = Mock()
    mock_answer_result.result.sources = ["https://example.com", "https://other.com"]
    mock_answer_result.result.json_content = None
    mock_client.answers.create.return_value = mock_answer_result

    # Mock batch response
    mock_batch_item = Mock()
    mock_batch_item.url = "https://example.com"
    mock_batch_item.custom_id = "batch_123"
    mock_batch_content = Mock()
    mock_batch_content.markdown_content = "# Batch Result"
    mock_batch_content.text_content = "Batch Result"
    mock_batch_content.html_content = "<html>Batch</html>"
    mock_batch_content.json_content = None
    mock_batch_item.retrieve.return_value = mock_batch_content

    mock_batch_result = Mock()
    mock_batch_result.items.return_value = [mock_batch_item]
    mock_client.batches.create.return_value = mock_batch_result

    return mock_client


def test_init_with_api_key():
    """Test initialization with explicit API key."""
    with patch("agno.tools.olostep.Olostep") as mock_olostep_class:
        tools = OlostepTools(api_key="test_key", scrape_url=True)
        assert tools.api_key == "test_key"
        mock_olostep_class.assert_called_once_with(api_key="test_key")


def test_init_with_env_api_key():
    """Test initialization with environment API key."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "env_key"}),
    ):
        tools = OlostepTools(scrape_url=True)
        assert tools.api_key == "env_key"
        mock_olostep_class.assert_called_once_with(api_key="env_key")


def test_init_without_api_key(caplog):
    """Test initialization without API key logs error."""
    with (
        patch("agno.tools.olostep.Olostep"),
        patch.dict(os.environ, {}, clear=True),
        patch("agno.tools.olostep.log_error") as mock_log_error,
    ):
        OlostepTools(scrape_url=True)
        mock_log_error.assert_called_once()


def test_init_with_all_tools():
    """Test initialization with all_tools=True enables all methods."""
    with patch("agno.tools.olostep.Olostep"):
        with patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}):
            tools = OlostepTools(all_tools=True)
            # Verify that the toolkit was created with all tools registered
            assert tools is not None
            assert hasattr(tools, "scrape_url")
            assert hasattr(tools, "crawl_website")
            assert hasattr(tools, "map_website")
            assert hasattr(tools, "search_web")
            assert hasattr(tools, "answer_question")
            assert hasattr(tools, "batch_scrape")


def test_init_with_selective_tools():
    """Test initialization with selective tool enabling."""
    with patch("agno.tools.olostep.Olostep"):
        with patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}):
            tools = OlostepTools(scrape_url=True, search_web=True, crawl_website=False)
            # Verify selective tools are registered
            assert hasattr(tools, "scrape_url")
            assert hasattr(tools, "search_web")
            # crawl_website should still exist as a method, but wasn't registered
            assert hasattr(tools, "crawl_website")


def test_scrape_url_markdown(mock_olostep_client):
    """Test scrape_url with markdown format."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(scrape_url=True)
        result = tools.scrape_url("https://example.com")

        assert result == "# Test Page\n\nTest content"
        mock_olostep_client.scrapes.create.assert_called_once()
        call_args = mock_olostep_client.scrapes.create.call_args
        assert call_args[1]["url_to_scrape"] == "https://example.com"
        assert "markdown" in call_args[1]["formats"]


def test_scrape_url_json_format(mock_olostep_client):
    """Test scrape_url with JSON format and parser_id."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_client.scrapes.create.return_value.markdown_content = None
        mock_olostep_client.scrapes.create.return_value.json_content = '{"extracted": "data"}'
        mock_olostep_class.return_value = mock_olostep_client

        tools = OlostepTools(scrape_url=True)
        result = tools.scrape_url(
            "https://example.com",
            formats="json",
            parser_id="@olostep/google-search"
        )

        assert result == '{"extracted": "data"}'
        call_args = mock_olostep_client.scrapes.create.call_args
        assert call_args[1]["parser"] == {"id": "@olostep/google-search"}


def test_scrape_url_with_llm_extract_schema(mock_olostep_client):
    """Test scrape_url with LLM extraction schema."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(scrape_url=True)
        schema = '{"title": "", "price": ""}'
        tools.scrape_url(
            "https://example.com",
            formats="json",
            llm_extract_schema=schema
        )

        call_args = mock_olostep_client.scrapes.create.call_args
        assert call_args[1]["llm_extract"]["schema"] == {"title": "", "price": ""}


def test_scrape_url_invalid_schema():
    """Test scrape_url with invalid JSON schema."""
    with (
        patch("agno.tools.olostep.Olostep"),
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        tools = OlostepTools(scrape_url=True)
        result = tools.scrape_url(
            "https://example.com",
            llm_extract_schema="invalid json"
        )

        assert "Error: llm_extract_schema must be a valid JSON string" in result


def test_scrape_url_error_handling(mock_olostep_client):
    """Test scrape_url error handling."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_client.scrapes.create.side_effect = Olostep_BaseError("API Error")
        mock_olostep_class.return_value = mock_olostep_client

        tools = OlostepTools(scrape_url=True)
        result = tools.scrape_url("https://example.com")

        assert "Olostep API error" in result
        assert "API Error" in result


def test_crawl_website(mock_olostep_client):
    """Test crawl_website method."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(crawl_website=True)
        result = tools.crawl_website("https://example.com")

        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["url"] == "https://example.com/page1"
        assert result_data[0]["markdown_content"] == "# Page 1"


def test_crawl_website_with_filters(mock_olostep_client):
    """Test crawl_website with URL filters."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(crawl_website=True)
        tools.crawl_website(
            "https://example.com",
            max_pages=50,
            max_depth=2,
            include_urls="/blog/**, /articles/**",
            exclude_urls="/admin/**"
        )

        call_args = mock_olostep_client.crawls.create.call_args
        assert call_args[1]["max_pages"] == 50
        assert call_args[1]["max_depth"] == 2
        assert "/blog/**" in call_args[1]["include_urls"]
        assert "/admin/**" in call_args[1]["exclude_urls"]


def test_map_website(mock_olostep_client):
    """Test map_website method."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(map_website=True)
        result = tools.map_website("https://example.com")

        result_data = json.loads(result)
        assert len(result_data) == 2
        assert "https://example.com/page1" in result_data
        assert "https://example.com/page2" in result_data


def test_search_web(mock_olostep_client):
    """Test search_web method."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(search_web=True)
        result = tools.search_web("best vector databases 2025")

        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["url"] == "https://example.com"
        assert result_data[0]["title"] == "Example Site"
        assert result_data[0]["description"] == "Example description"


def test_answer_question(mock_olostep_client):
    """Test answer_question method."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(answer_question=True)
        result = tools.answer_question("What is the best web scraping tool?")

        result_data = json.loads(result)
        assert "answer" in result_data
        assert "sources" in result_data
        assert result_data["answer"] == "The answer to your question is..."
        assert len(result_data["sources"]) == 2


def test_answer_question_with_schema(mock_olostep_client):
    """Test answer_question with JSON schema."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_answer = Mock()
        mock_answer.answer = "Answer text"
        mock_answer.result = Mock()
        mock_answer.result.json_content = '{"company": "Agno", "founded": "2025"}'
        mock_answer.result.sources = ["https://example.com"]
        mock_olostep_client.answers.create.return_value = mock_answer
        mock_olostep_class.return_value = mock_olostep_client

        tools = OlostepTools(answer_question=True)
        schema = '{"company": "", "founded": ""}'
        result = tools.answer_question("What is Agno?", json_schema=schema)

        result_data = json.loads(result)
        assert result_data["company"] == "Agno"
        assert result_data["founded"] == "2025"
        assert "_sources" in result_data


def test_batch_scrape(mock_olostep_client):
    """Test batch_scrape method."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(batch_scrape=True)
        urls = "https://example.com, https://example.com/page2"
        result = tools.batch_scrape(urls)

        result_data = json.loads(result)
        assert len(result_data) == 1
        assert result_data[0]["url"] == "https://example.com"
        assert result_data[0]["custom_id"] == "batch_123"
        assert "Batch Result" in result_data[0]["content"]


def test_batch_scrape_empty_urls():
    """Test batch_scrape with no valid URLs."""
    with (
        patch("agno.tools.olostep.Olostep"),
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        tools = OlostepTools(batch_scrape=True)
        result = tools.batch_scrape("")

        assert "Error: no valid URLs provided" in result


def test_batch_scrape_with_parser(mock_olostep_client):
    """Test batch_scrape with parser_id."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(batch_scrape=True)
        urls = "https://example.com, https://example2.com"
        tools.batch_scrape(urls, parser_id="@olostep/extract-emails")

        call_args = mock_olostep_client.batches.create.call_args
        assert call_args[1]["parser"] == {"id": "@olostep/extract-emails"}


def test_all_tools_enabled():
    """Test that multiple tools can be registered simultaneously."""
    with patch("agno.tools.olostep.Olostep"):
        with patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}):
            tools = OlostepTools(
                scrape_url=True,
                crawl_website=True,
                map_website=True,
                search_web=True,
                answer_question=True,
                batch_scrape=True,
            )

            # Verify all methods are present
            assert all(
                hasattr(tools, name)
                for name in ["scrape_url", "crawl_website", "map_website", "search_web", "answer_question", "batch_scrape"]
            )


def test_country_parameter(mock_olostep_client):
    """Test that country parameter is lowercased."""
    with (
        patch("agno.tools.olostep.Olostep") as mock_olostep_class,
        patch.dict(os.environ, {"OLOSTEP_API_KEY": "test_key"}),
    ):
        mock_olostep_class.return_value = mock_olostep_client
        tools = OlostepTools(scrape_url=True)
        tools.scrape_url("https://example.com", country="US")

        call_args = mock_olostep_client.scrapes.create.call_args
        assert call_args[1]["country"] == "us"
