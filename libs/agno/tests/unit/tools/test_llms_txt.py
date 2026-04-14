"""Unit tests for LLMsTxtTools and LLMsTxtReader."""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest

bs4 = pytest.importorskip("bs4")

from agno.knowledge.reader.llms_txt_reader import LLMsTxtEntry, LLMsTxtReader  # noqa: E402
from agno.tools.llms_txt import LLMsTxtTools  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture
def reader():
    return LLMsTxtReader(chunk=False)


@pytest.fixture
def tools():
    return LLMsTxtTools()


@pytest.fixture
def tools_with_knowledge():
    mock_knowledge = MagicMock()
    return LLMsTxtTools(knowledge=mock_knowledge)


def _mock_httpx_response(text: str, content_type: str = "text/plain") -> Mock:
    resp = Mock()
    resp.headers = {"content-type": content_type}
    resp.text = text
    resp.raise_for_status = Mock()
    return resp


# ============================================================================
# READER: INIT
# ============================================================================


def test_reader_defaults():
    reader = LLMsTxtReader()
    assert reader.max_urls == 20
    assert reader.timeout == 60
    assert reader.proxy is None
    assert reader.skip_optional is False


def test_reader_custom_params():
    reader = LLMsTxtReader(max_urls=50, timeout=10, skip_optional=True)
    assert reader.max_urls == 50
    assert reader.timeout == 10
    assert reader.skip_optional is True


# ============================================================================
# READER: PARSE
# ============================================================================


def test_parse_entries(reader):
    overview, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

    assert len(entries) == 7
    assert entries[0].title == "Introduction"
    assert entries[0].url == "https://docs.acme.com/introduction"
    assert entries[0].description == "Overview of Acme"
    assert entries[0].section == "Getting Started"


def test_parse_overview(reader):
    overview, _ = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

    assert "# Acme Project" in overview
    assert "Acme makes it easy" in overview


def test_parse_sections(reader):
    _, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

    sections = {e.section for e in entries}
    assert sections == {"Getting Started", "API Reference", "Optional"}


def test_parse_skip_optional():
    reader = LLMsTxtReader(skip_optional=True)
    _, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT, "https://docs.acme.com/llms.txt")

    assert len(entries) == 5
    assert all(e.section != "Optional" for e in entries)


def test_parse_relative_urls(reader):
    _, entries = reader.parse_llms_txt(SAMPLE_LLMS_TXT_RELATIVE, "https://example.com/llms.txt")

    assert entries[0].url == "https://example.com/docs/guide"
    assert entries[1].url == "https://example.com/api/reference"


def test_parse_empty_content(reader):
    overview, entries = reader.parse_llms_txt("", "https://example.com/llms.txt")

    assert overview == ""
    assert entries == []


def test_parse_no_links(reader):
    content = "# Title\n\nSome overview text.\n\n## Section\n\nNo links here."
    overview, entries = reader.parse_llms_txt(content, "https://example.com/llms.txt")

    assert "# Title" in overview
    assert entries == []


# ============================================================================
# READER: PROCESS RESPONSE
# ============================================================================


def test_process_response_plain_text(reader):
    result = reader._process_response("text/plain", "Plain text content")
    assert result == "Plain text content"


def test_process_response_markdown(reader):
    result = reader._process_response("text/markdown", "# Heading\n\nBody")
    assert result == "# Heading\n\nBody"


def test_process_response_html_extracts_main(reader):
    html = "<html><body><nav>Nav</nav><main>Main content here</main><footer>Foot</footer></body></html>"
    result = reader._process_response("text/html", html)
    assert "Main content here" in result
    assert "Nav" not in result


def test_process_response_html_body_fallback(reader):
    html = "<html><body><div>Body content</div></body></html>"
    result = reader._process_response("text/html", html)
    assert "Body content" in result


def test_process_response_strips_scripts(reader):
    html = "<html><body><script>var x=1;</script><style>.a{}</style><p>Text</p></body></html>"
    result = reader._process_response("text/html", html)
    assert "var x" not in result
    assert "Text" in result


def test_process_response_newline_separator(reader):
    html = "<html><body><main><p>First paragraph</p><p>Second paragraph</p></main></body></html>"
    result = reader._process_response("text/html", html)
    assert "First paragraph" in result
    assert "Second paragraph" in result
    assert "\n" in result


def test_process_response_html_sniffing(reader):
    """HTML detected by content prefix when content-type header is missing."""
    result = reader._process_response("", "<!DOCTYPE html><html><body><p>Sniffed</p></body></html>")
    assert "Sniffed" in result


def test_process_response_unknown_content_type(reader):
    """Unknown content-type returns raw text."""
    result = reader._process_response("application/json", '{"key": "value"}')
    assert result == '{"key": "value"}'


# ============================================================================
# READER: FETCH
# ============================================================================


def test_fetch_url_plain_content(reader):
    mock_response = _mock_httpx_response("Plain text content", "text/plain")

    with patch("agno.utils.http.httpx.get", return_value=mock_response):
        result = reader.fetch_url("https://example.com/file.txt")

    assert result == "Plain text content"


def test_fetch_url_html_content(reader):
    mock_response = _mock_httpx_response("<html><body><main>Extracted</main></body></html>", "text/html")

    with patch("agno.utils.http.httpx.get", return_value=mock_response):
        result = reader.fetch_url("https://example.com/page")

    assert "Extracted" in result


def test_fetch_url_http_error(reader):
    with patch(
        "agno.utils.http.httpx.get",
        side_effect=httpx.HTTPStatusError("error", request=MagicMock(), response=MagicMock(status_code=404)),
    ):
        result = reader.fetch_url("https://example.com/missing")

    assert result is None


def test_fetch_url_request_error(reader):
    with patch("agno.utils.http.httpx.get", side_effect=httpx.RequestError("connection failed")):
        result = reader.fetch_url("https://example.com/down")

    assert result is None


# ============================================================================
# READER: BUILD DOCUMENTS
# ============================================================================


def test_build_documents_overview_and_linked(reader):
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


def test_build_documents_skips_unfetched(reader):
    entries = [
        LLMsTxtEntry(title="Missing", url="https://example.com/missing", description="", section="Docs"),
    ]
    docs = reader._build_documents("Overview", entries, {}, "https://example.com/llms.txt", None)

    assert len(docs) == 1
    assert docs[0].meta_data["type"] == "llms_txt_overview"


def test_build_documents_empty_overview(reader):
    entries = [
        LLMsTxtEntry(title="Page", url="https://example.com/page", description="", section="Docs"),
    ]
    fetched = {"https://example.com/page": "Page content"}

    docs = reader._build_documents("", entries, fetched, "https://example.com/llms.txt", None)

    assert len(docs) == 1
    assert docs[0].meta_data["type"] == "llms_txt_linked_doc"


# ============================================================================
# READER: READ
# ============================================================================


def test_read_fetches_and_builds():
    reader = LLMsTxtReader(max_urls=5, chunk=False)

    def mock_fetch(url):
        if url == "https://example.com/llms.txt":
            return SAMPLE_LLMS_TXT
        return f"Content of {url}"

    with patch.object(reader, "fetch_url", side_effect=mock_fetch):
        docs = reader.read("https://example.com/llms.txt")

    assert len(docs) == 6
    assert docs[0].meta_data["type"] == "llms_txt_overview"


def test_read_returns_empty_on_failure():
    reader = LLMsTxtReader()

    with patch.object(reader, "fetch_url", return_value=None):
        docs = reader.read("https://example.com/llms.txt")

    assert docs == []


def test_read_max_urls_limits():
    reader = LLMsTxtReader(max_urls=2, chunk=False)

    def mock_fetch(url):
        if url == "https://example.com/llms.txt":
            return SAMPLE_LLMS_TXT
        return f"Content of {url}"

    with patch.object(reader, "fetch_url", side_effect=mock_fetch):
        docs = reader.read("https://example.com/llms.txt")

    assert len(docs) == 3


# ============================================================================
# READER: ASYNC READ
# ============================================================================


@pytest.mark.asyncio
async def test_async_read_fetches_concurrently():
    reader = LLMsTxtReader(max_urls=3, chunk=False)

    async def mock_async_fetch(client, url):
        if "llms.txt" in url:
            return SAMPLE_LLMS_TXT
        return f"Content of {url}"

    with patch.object(reader, "async_fetch_url", side_effect=mock_async_fetch):
        docs = await reader.async_read("https://example.com/llms.txt")

    assert len(docs) == 4
    assert docs[0].meta_data["type"] == "llms_txt_overview"


@pytest.mark.asyncio
async def test_async_read_returns_empty_on_failure():
    reader = LLMsTxtReader()

    async def mock_async_fetch(client, url):
        return None

    with patch.object(reader, "async_fetch_url", side_effect=mock_async_fetch):
        docs = await reader.async_read("https://example.com/llms.txt")

    assert docs == []


# ============================================================================
# TOOLKIT: INIT
# ============================================================================


def test_toolkit_agentic_tools(tools):
    func_names = [func.name for func in tools.functions.values()]
    assert "get_llms_txt_index" in func_names
    assert "read_llms_txt_url" in func_names
    assert "read_llms_txt_and_load_knowledge" not in func_names


def test_toolkit_async_tools(tools):
    async_func_names = [func.name for func in tools.async_functions.values()]
    assert "get_llms_txt_index" in async_func_names
    assert "read_llms_txt_url" in async_func_names


def test_toolkit_knowledge_tools(tools_with_knowledge):
    func_names = [func.name for func in tools_with_knowledge.functions.values()]
    assert "read_llms_txt_and_load_knowledge" in func_names
    assert "get_llms_txt_index" not in func_names


def test_toolkit_knowledge_async_tools(tools_with_knowledge):
    async_func_names = [func.name for func in tools_with_knowledge.async_functions.values()]
    assert "read_llms_txt_and_load_knowledge" in async_func_names


def test_toolkit_custom_params():
    t = LLMsTxtTools(max_urls=50, timeout=10, skip_optional=True)
    assert t.max_urls == 50
    assert t.timeout == 10
    assert t.skip_optional is True


def test_toolkit_reader_reuse(tools):
    assert tools.reader is not None
    assert tools.reader.timeout == tools.timeout
    assert tools.reader.max_urls == tools.max_urls


# ============================================================================
# TOOLKIT: GET INDEX
# ============================================================================


def test_get_index_returns_json(tools):
    mock_response = _mock_httpx_response(SAMPLE_LLMS_TXT, "text/plain")

    with patch("agno.utils.http.httpx.get", return_value=mock_response):
        result = tools.get_llms_txt_index("https://docs.acme.com/llms.txt")

    data = json.loads(result)
    assert data["total_pages"] == 7
    assert data["pages"][0]["title"] == "Introduction"
    assert data["pages"][0]["url"] == "https://docs.acme.com/introduction"
    assert "overview" in data


def test_get_index_failure(tools):
    with patch("agno.utils.http.httpx.get", side_effect=httpx.RequestError("connection failed")):
        result = tools.get_llms_txt_index("https://example.com/llms.txt")

    assert "Failed to fetch" in result


def test_get_index_error_handling(tools):
    with patch.object(tools.reader, "fetch_url", side_effect=RuntimeError("unexpected")):
        result = tools.get_llms_txt_index("https://example.com/llms.txt")

    assert "Error" in result
    assert "RuntimeError" in result


# ============================================================================
# TOOLKIT: READ URL
# ============================================================================


def test_read_url_returns_content(tools):
    mock_response = _mock_httpx_response("Page content here", "text/plain")

    with patch("agno.utils.http.httpx.get", return_value=mock_response):
        result = tools.read_llms_txt_url("https://docs.acme.com/introduction")

    assert result == "Page content here"


def test_read_url_failure(tools):
    with patch("agno.utils.http.httpx.get", side_effect=httpx.RequestError("connection failed")):
        result = tools.read_llms_txt_url("https://example.com/missing")

    assert "Failed to fetch" in result


# ============================================================================
# TOOLKIT: ASYNC TOOLS
# ============================================================================


@pytest.mark.asyncio
async def test_aget_index_returns_json(tools):
    mock_response = _mock_httpx_response(SAMPLE_LLMS_TXT, "text/plain")

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    with patch("agno.tools.llms_txt.httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tools.aget_llms_txt_index("https://docs.acme.com/llms.txt")

    data = json.loads(result)
    assert data["total_pages"] == 7
    assert data["pages"][0]["title"] == "Introduction"


@pytest.mark.asyncio
async def test_aread_url_returns_content(tools):
    mock_response = _mock_httpx_response("Async page content", "text/plain")

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    with patch("agno.tools.llms_txt.httpx.AsyncClient") as mock_async_client:
        mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await tools.aread_llms_txt_url("https://docs.acme.com/page")

    assert result == "Async page content"


@pytest.mark.asyncio
async def test_aread_knowledge_delegates(tools_with_knowledge):
    tools_with_knowledge.knowledge.ainsert = AsyncMock()

    result = await tools_with_knowledge.aread_llms_txt_and_load_knowledge("https://example.com/llms.txt")

    tools_with_knowledge.knowledge.ainsert.assert_called_once_with(
        url="https://example.com/llms.txt", reader=tools_with_knowledge.reader
    )
    assert "Successfully loaded" in result


# ============================================================================
# TOOLKIT: KNOWLEDGE
# ============================================================================


def test_knowledge_delegates_to_insert(tools_with_knowledge):
    result = tools_with_knowledge.read_llms_txt_and_load_knowledge("https://example.com/llms.txt")

    tools_with_knowledge.knowledge.insert.assert_called_once_with(
        url="https://example.com/llms.txt", reader=tools_with_knowledge.reader
    )
    assert "Successfully loaded" in result


def test_knowledge_no_knowledge(tools):
    result = tools.read_llms_txt_and_load_knowledge("https://example.com/llms.txt")
    assert result == "Knowledge base not provided"


def test_knowledge_error_handling(tools_with_knowledge):
    tools_with_knowledge.knowledge.insert.side_effect = RuntimeError("db connection failed")

    result = tools_with_knowledge.read_llms_txt_and_load_knowledge("https://example.com/llms.txt")

    assert "Error" in result
    assert "RuntimeError" in result
