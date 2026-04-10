"""Unit tests for LLMsTxtTools and LLMsTxtReader."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

bs4 = pytest.importorskip("bs4")

from agno.knowledge.reader.llms_txt_reader import LLMsTxtEntry, LLMsTxtReader  # noqa: E402
from agno.tools.llms_txt import LLMsTxtTools  # noqa: E402

# ---------------------------------------------------------------------------
# Sample llms.txt content for testing
# ---------------------------------------------------------------------------

SAMPLE_LLMS_TXT = """# Acme Project

> Acme is a framework for building AI applications.

Acme makes it easy to build production-ready AI agents.

## Getting Started

- [Introduction](https://docs.acme.com/introduction): Overview of Acme
- [Installation](https://docs.acme.com/installation): How to install Acme
- [Quickstart](https://docs.acme.com/quickstart): Build your first agent

## API Reference

- [Agent API](https://docs.acme.com/api/agent): Agent class reference
- [Tools API](https://docs.acme.com/api/tools): Tools class reference

## Optional

- [Changelog](https://docs.acme.com/changelog): Release notes
- [Contributing](https://docs.acme.com/contributing): How to contribute
"""

SAMPLE_LLMS_TXT_RELATIVE = """# My Project

> A project with relative links.

## Docs

- [Guide](/docs/guide): The guide
- [API](api/reference): API docs
"""


# ---------------------------------------------------------------------------
# LLMsTxtReader tests
# ---------------------------------------------------------------------------


class TestLLMsTxtReaderInit:
    def test_defaults(self):
        reader = LLMsTxtReader()
        assert reader.max_urls == 100
        assert reader.timeout == 30
        assert reader.proxy is None
        assert reader.include_llms_txt_content is True
        assert reader.skip_optional is False

    def test_custom_params(self):
        reader = LLMsTxtReader(max_urls=50, timeout=10, skip_optional=True)
        assert reader.max_urls == 50
        assert reader.timeout == 10
        assert reader.skip_optional is True


class TestParseLLMsTxt:
    def test_parses_entries(self):
        reader = LLMsTxtReader()
        overview, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

        assert len(entries) == 7
        assert entries[0].title == "Introduction"
        assert entries[0].url == "https://docs.acme.com/introduction"
        assert entries[0].description == "Overview of Acme"
        assert entries[0].section == "Getting Started"

    def test_parses_overview(self):
        reader = LLMsTxtReader()
        overview, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

        assert "# Acme Project" in overview
        assert "Acme makes it easy" in overview

    def test_sections_assigned(self):
        reader = LLMsTxtReader()
        _, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

        sections = {e.section for e in entries}
        assert sections == {"Getting Started", "API Reference", "Optional"}

    def test_skip_optional(self):
        reader = LLMsTxtReader(skip_optional=True)
        _, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

        assert len(entries) == 5
        assert all(e.section != "Optional" for e in entries)

    def test_relative_urls_resolved(self):
        reader = LLMsTxtReader()
        _, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT_RELATIVE, "https://example.com/llms.txt")

        assert entries[0].url == "https://example.com/docs/guide"
        assert entries[1].url == "https://example.com/api/reference"

    def test_empty_content(self):
        reader = LLMsTxtReader()
        overview, entries = reader.parse_llms_txt("", "https://example.com/llms.txt")

        assert overview == ""
        assert entries == []

    def test_no_links(self):
        content = "# Title\n\nSome overview text.\n\n## Section\n\nNo links here."
        reader = LLMsTxtReader()
        overview, entries = reader.parse_llms_txt(content, "https://example.com/llms.txt")

        assert "# Title" in overview
        assert entries == []


class TestExtractContent:
    def test_extracts_from_main_tag(self):
        reader = LLMsTxtReader()
        html = "<html><body><nav>Nav</nav><main>Main content here</main><footer>Foot</footer></body></html>"
        result = reader._extract_content(html)
        assert "Main content here" in result
        assert "Nav" not in result

    def test_extracts_from_body_fallback(self):
        reader = LLMsTxtReader()
        html = "<html><body><div>Body content</div></body></html>"
        result = reader._extract_content(html)
        assert "Body content" in result

    def test_strips_script_and_style(self):
        reader = LLMsTxtReader()
        html = "<html><body><script>var x=1;</script><style>.a{}</style><p>Text</p></body></html>"
        result = reader._extract_content(html)
        assert "var x" not in result
        assert "Text" in result

    def test_preserves_structure_with_newlines(self):
        reader = LLMsTxtReader()
        html = "<html><body><main><p>First paragraph</p><p>Second paragraph</p></main></body></html>"
        result = reader._extract_content(html)
        assert "First paragraph" in result
        assert "Second paragraph" in result
        assert "\n" in result


class TestFetchUrl:
    def test_returns_text_for_plain_content(self):
        reader = LLMsTxtReader()
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "Plain text content"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            result = reader.fetch_url("https://example.com/file.txt")

        assert result == "Plain text content"

    def test_extracts_html_content(self):
        reader = LLMsTxtReader()
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/html"}
        mock_response.text = "<html><body><main>Extracted</main></body></html>"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            result = reader.fetch_url("https://example.com/page")

        assert "Extracted" in result

    def test_returns_none_on_http_error(self):
        reader = LLMsTxtReader()

        with patch(
            "httpx.get",
            side_effect=httpx.HTTPStatusError("error", request=MagicMock(), response=MagicMock(status_code=404)),
        ):
            result = reader.fetch_url("https://example.com/missing")

        assert result is None

    def test_returns_none_on_request_error(self):
        reader = LLMsTxtReader()

        with patch("httpx.get", side_effect=httpx.RequestError("connection failed")):
            result = reader.fetch_url("https://example.com/down")

        assert result is None


class TestBuildDocuments:
    def test_builds_overview_and_linked_docs(self):
        reader = LLMsTxtReader(chunk=False)
        entries = [
            LLMsTxtEntry(title="Intro", url="https://example.com/intro", description="Intro page", section="Docs"),
        ]
        fetched = {"https://example.com/intro": "Introduction content here"}

        docs = reader._build_documents("Overview text", entries, fetched, "https://example.com/llms.txt", None)

        assert len(docs) == 2
        assert docs[0].meta_data["type"] == "llms_txt_overview"
        assert docs[0].content == "Overview text"
        assert docs[1].meta_data["type"] == "llms_txt_linked_doc"
        assert docs[1].name == "Intro"
        assert docs[1].content == "Introduction content here"

    def test_skips_unfetched_entries(self):
        reader = LLMsTxtReader(chunk=False)
        entries = [
            LLMsTxtEntry(title="Missing", url="https://example.com/missing", description="", section="Docs"),
        ]
        fetched = {}

        docs = reader._build_documents("Overview", entries, fetched, "https://example.com/llms.txt", None)

        # Only the overview doc
        assert len(docs) == 1

    def test_excludes_overview_when_disabled(self):
        reader = LLMsTxtReader(chunk=False, include_llms_txt_content=False)
        entries = [
            LLMsTxtEntry(title="Page", url="https://example.com/page", description="", section="Docs"),
        ]
        fetched = {"https://example.com/page": "Page content"}

        docs = reader._build_documents("Overview", entries, fetched, "https://example.com/llms.txt", None)

        assert len(docs) == 1
        assert docs[0].meta_data["type"] == "llms_txt_linked_doc"


class TestRead:
    def test_read_fetches_and_builds_docs(self):
        reader = LLMsTxtReader(max_urls=5, chunk=False)

        def mock_fetch(url):
            if url == "https://example.com/llms.txt":
                return SAMPLE_LLMS_TXT
            return f"Content of {url}"

        with patch.object(reader, "fetch_url", side_effect=mock_fetch):
            docs = reader.read("https://example.com/llms.txt")

        # 1 overview + 5 linked docs (max_urls=5)
        assert len(docs) == 6
        assert docs[0].meta_data["type"] == "llms_txt_overview"

    def test_read_returns_empty_on_fetch_failure(self):
        reader = LLMsTxtReader()

        with patch.object(reader, "fetch_url", return_value=None):
            docs = reader.read("https://example.com/llms.txt")

        assert docs == []

    def test_max_urls_limits_fetched_pages(self):
        reader = LLMsTxtReader(max_urls=2, chunk=False)

        def mock_fetch(url):
            if url == "https://example.com/llms.txt":
                return SAMPLE_LLMS_TXT
            return f"Content of {url}"

        with patch.object(reader, "fetch_url", side_effect=mock_fetch):
            docs = reader.read("https://example.com/llms.txt")

        # 1 overview + 2 linked docs (max_urls=2)
        assert len(docs) == 3


# ---------------------------------------------------------------------------
# LLMsTxtTools tests
# ---------------------------------------------------------------------------


class TestLLMsTxtToolsInit:
    def test_without_knowledge_registers_agentic_tools(self):
        tools = LLMsTxtTools()
        func_names = [func.name for func in tools.functions.values()]
        assert "get_llms_txt_index" in func_names
        assert "read_llms_txt_url" in func_names
        assert "read_llms_txt_and_load_knowledge" not in func_names

    def test_without_knowledge_registers_async_tools(self):
        tools = LLMsTxtTools()
        async_func_names = [func.name for func in tools.async_functions.values()]
        assert "get_llms_txt_index" in async_func_names
        assert "read_llms_txt_url" in async_func_names

    def test_with_knowledge_registers_load(self):
        mock_knowledge = MagicMock()
        tools = LLMsTxtTools(knowledge=mock_knowledge)
        func_names = [func.name for func in tools.functions.values()]
        assert "read_llms_txt_and_load_knowledge" in func_names
        assert "get_llms_txt_index" not in func_names

    def test_with_knowledge_registers_async_load(self):
        mock_knowledge = MagicMock()
        tools = LLMsTxtTools(knowledge=mock_knowledge)
        async_func_names = [func.name for func in tools.async_functions.values()]
        assert "read_llms_txt_and_load_knowledge" in async_func_names

    def test_custom_params(self):
        tools = LLMsTxtTools(max_urls=50, timeout=10, skip_optional=True)
        assert tools.max_urls == 50
        assert tools.timeout == 10
        assert tools.skip_optional is True

    def test_reader_is_reused(self):
        tools = LLMsTxtTools()
        assert tools.reader is not None
        assert tools.reader.timeout == tools.timeout
        assert tools.reader.max_urls == tools.max_urls


class TestGetLLMsTxtIndex:
    def test_returns_index_json(self):
        tools = LLMsTxtTools()

        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = SAMPLE_LLMS_TXT
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            result = tools.get_llms_txt_index("https://docs.acme.com/llms.txt")

        data = json.loads(result)
        assert data["total_pages"] == 7
        assert data["pages"][0]["title"] == "Introduction"
        assert data["pages"][0]["url"] == "https://docs.acme.com/introduction"
        assert "overview" in data

    def test_returns_error_on_fetch_failure(self):
        tools = LLMsTxtTools()

        with patch("httpx.get", side_effect=httpx.RequestError("connection failed")):
            result = tools.get_llms_txt_index("https://example.com/llms.txt")

        assert "Failed to fetch" in result


class TestReadLLMsTxtUrl:
    def test_returns_page_content(self):
        tools = LLMsTxtTools()

        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.text = "Page content here"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            result = tools.read_llms_txt_url("https://docs.acme.com/introduction")

        assert result == "Page content here"

    def test_returns_error_on_fetch_failure(self):
        tools = LLMsTxtTools()

        with patch("httpx.get", side_effect=httpx.RequestError("connection failed")):
            result = tools.read_llms_txt_url("https://example.com/missing")

        assert "Failed to fetch" in result


class TestLoadKnowledge:
    def test_delegates_to_knowledge_insert(self):
        mock_knowledge = MagicMock()
        tools = LLMsTxtTools(knowledge=mock_knowledge)

        tools.read_llms_txt_and_load_knowledge("https://example.com/llms.txt")

        mock_knowledge.insert.assert_called_once_with(url="https://example.com/llms.txt", reader=tools.reader)

    def test_returns_message_when_no_knowledge(self):
        tools = LLMsTxtTools()
        result = tools.read_llms_txt_and_load_knowledge("https://example.com/llms.txt")
        assert result == "Knowledge base not provided"

    def test_returns_success_message(self):
        mock_knowledge = MagicMock()
        tools = LLMsTxtTools(knowledge=mock_knowledge)

        result = tools.read_llms_txt_and_load_knowledge("https://example.com/llms.txt")

        assert "Successfully loaded" in result
