"""Unit tests for YouTools class."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.youcom import YouTools


@pytest.fixture(autouse=True)
def mock_api_key():
    """Provide a fake YDC_API_KEY for every test so YouTools constructs without warnings."""
    with patch.dict("os.environ", {"YDC_API_KEY": "test-key"}):
        yield


@pytest.fixture
def youcom_tools():
    """Create a YouTools instance with the fake API key from the environment."""
    return YouTools()


def _mock_response(payload):
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _patch_client(payload):
    """Patch ``httpx.Client`` so any GET returns the given JSON payload."""
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = _mock_response(payload)
    return patch("agno.tools.youcom.search.httpx.Client", return_value=client), client


def test_init_with_api_key():
    """API key passed via constructor is preferred over the env var."""
    tools = YouTools(api_key="explicit-key")
    assert tools.api_key == "explicit-key"


def test_init_reads_env_var():
    """API key is read from YDC_API_KEY when not provided."""
    with patch.dict("os.environ", {"YDC_API_KEY": "env-key"}):
        tools = YouTools()
        assert tools.api_key == "env-key"


def test_only_search_tool_registered():
    """YouTools should expose exactly one tool: you_search."""
    tools = YouTools()
    names = [func.name for func in tools.functions.values()]
    assert names == ["you_search"]


def test_base_url_strips_trailing_slash():
    tools = YouTools(base_url="https://custom.example.com/")
    assert tools.base_url == "https://custom.example.com"


def test_search_success(youcom_tools):
    payload = {
        "results": {
            "web": [
                {
                    "url": "https://example.com",
                    "title": "Test Article",
                    "description": "A short snippet",
                    "contents": {"markdown": "Sample text content"},
                    "page_age": "2024-01-01",
                }
            ]
        }
    }
    patcher, client = _patch_client(payload)
    with patcher:
        result = youcom_tools.you_search("test query", num_results=3)
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["url"] == "https://example.com"
    assert parsed[0]["title"] == "Test Article"
    assert parsed[0]["snippet"] == "A short snippet"
    assert parsed[0]["text"] == "Sample text content"
    assert parsed[0]["published_date"] == "2024-01-01"

    args, kwargs = client.get.call_args
    assert args[0].endswith("/v1/search")
    assert kwargs["params"]["query"] == "test query"
    assert kwargs["params"]["count"] == 3
    assert "livecrawl" not in kwargs["params"]  # off unless set
    assert "crawl_timeout" not in kwargs["params"]
    assert kwargs["headers"]["X-API-Key"] == "test-key"


def test_search_parses_grouped_web_and_news():
    """The search API groups hits under results.web / results.news; both must be surfaced."""
    payload = {
        "results": {
            "news": [
                {
                    "url": "https://news.example.com",
                    "title": "Headline",
                    "description": "news snippet",
                    "page_age": "2026-01-02",
                }
            ],
            "web": [
                {
                    "url": "https://web.example.com",
                    "title": "Web Page",
                    "description": "web snippet",
                    "contents": {"markdown": "web body"},
                }
            ],
        }
    }
    tools = YouTools()

    patcher, _ = _patch_client(payload)
    with patcher:
        result = tools.you_search("grouped query")
    parsed = json.loads(result)

    assert {r["url"] for r in parsed} == {"https://news.example.com", "https://web.example.com"}
    web = next(r for r in parsed if r["url"] == "https://web.example.com")
    assert web["text"] == "web body"  # nested contents.markdown is extracted
    news = next(r for r in parsed if r["url"] == "https://news.example.com")
    assert news["snippet"] == "news snippet"
    assert news["published_date"] == "2026-01-02"  # page_age is mapped to published_date


def test_search_snippets_list_used_as_text():
    """Non-crawled web hits carry body text in a 'snippets' list; it must be surfaced as text."""
    payload = {
        "results": {
            "web": [
                {
                    "url": "https://web.example.com",
                    "title": "Web Page",
                    "description": "one-line description",
                    "snippets": ["first paragraph", "second paragraph"],
                }
            ]
        }
    }
    tools = YouTools()

    patcher, _ = _patch_client(payload)
    with patcher:
        result = tools.you_search("q")
    parsed = json.loads(result)

    assert parsed[0]["snippet"] == "one-line description"
    assert parsed[0]["text"] == "first paragraph\nsecond paragraph"


def test_search_prefers_contents_over_snippets():
    """When both livecrawled contents and snippets exist, contents.markdown wins."""
    payload = {
        "results": {
            "web": [
                {
                    "url": "https://web.example.com",
                    "contents": {"markdown": "crawled body"},
                    "snippets": ["snippet body"],
                }
            ]
        }
    }
    tools = YouTools()

    patcher, _ = _patch_client(payload)
    with patcher:
        result = tools.you_search("q")
    parsed = json.loads(result)

    assert parsed[0]["text"] == "crawled body"


def test_search_passes_domain_filters():
    # include and exclude cannot be combined, so verify each is comma-joined on its own.
    tools = YouTools(include_domains=["example.com", "example.org"])
    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("filtered query")
    assert client.get.call_args.kwargs["params"]["include_domains"] == "example.com,example.org"

    tools = YouTools(exclude_domains=["spam.com"])
    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("filtered query")
    assert client.get.call_args.kwargs["params"]["exclude_domains"] == "spam.com"


def test_search_passes_new_params():
    tools = YouTools(
        country="IN",
        freshness="month",
        language="EN",
        safesearch="moderate",
        offset=2,
        boost_domains=["gov.in", "edu.in"],
    )

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("test query")

    params = client.get.call_args.kwargs["params"]
    assert params["country"] == "IN"
    assert params["freshness"] == "month"
    assert params["language"] == "EN"
    assert params["safesearch"] == "moderate"
    assert params["offset"] == 2
    assert params["boost_domains"] == "gov.in,edu.in"


def test_search_omits_unset_params():
    tools = YouTools()

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("test query")

    params = client.get.call_args.kwargs["params"]
    assert "country" not in params
    assert "freshness" not in params
    assert "language" not in params
    assert "safesearch" not in params
    assert "offset" not in params
    assert "boost_domains" not in params
    assert "include_domains" not in params
    assert "exclude_domains" not in params
    assert "livecrawl" not in params
    assert "livecrawl_formats" not in params
    assert "crawl_timeout" not in params


def test_search_livecrawl_formats_list():
    tools = YouTools(livecrawl="web", livecrawl_formats=["html", "markdown"])

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("test query")

    params = client.get.call_args.kwargs["params"]
    assert params["livecrawl_formats"] == ["html", "markdown"]


def test_search_livecrawl_formats_comma_string():
    tools = YouTools(livecrawl="web", livecrawl_formats="html, markdown")

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("test query")

    params = client.get.call_args.kwargs["params"]
    assert params["livecrawl_formats"] == ["html", "markdown"]


def test_livecrawl_off_by_default():
    """livecrawl is off unless set; its formats and crawl_timeout are not sent."""
    tools = YouTools(livecrawl_formats=["markdown"], crawl_timeout=20)

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("q")

    params = client.get.call_args.kwargs["params"]
    assert "livecrawl" not in params
    assert "livecrawl_formats" not in params
    assert "crawl_timeout" not in params


def test_livecrawl_on_sends_formats_and_timeout():
    """When livecrawl is set, it plus its formats and crawl_timeout are sent."""
    tools = YouTools(livecrawl="all", livecrawl_formats=["markdown", "html"], crawl_timeout=25)

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("q")

    params = client.get.call_args.kwargs["params"]
    assert params["livecrawl"] == "all"
    assert params["livecrawl_formats"] == ["markdown", "html"]
    assert params["crawl_timeout"] == 25


def test_offset_range_validation():
    with pytest.raises(ValueError, match="offset must be between 0 and 9"):
        YouTools(offset=-1)

    with pytest.raises(ValueError, match="offset must be between 0 and 9"):
        YouTools(offset=10)

    YouTools(offset=0)  # lower boundary is accepted
    YouTools(offset=9)  # upper boundary is accepted


def test_domain_mutual_exclusivity():
    with pytest.raises(ValueError, match="include_domains cannot be combined"):
        YouTools(include_domains=["a.com"], exclude_domains=["b.com"])

    with pytest.raises(ValueError, match="include_domains cannot be combined"):
        YouTools(include_domains=["a.com"], boost_domains=["b.com"])

    YouTools(boost_domains=["a.com"], exclude_domains=["b.com"])  # allowed combination


def test_search_params_passthrough():
    """Arbitrary search_params are merged into the request, for params not yet exposed as arguments."""
    tools = YouTools(search_params={"spellcheck": "true", "custom": "x"})

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("q")

    params = client.get.call_args.kwargs["params"]
    assert params["spellcheck"] == "true"
    assert params["custom"] == "x"


def test_search_params_override_explicit():
    """search_params is applied last, so it can override explicit arguments."""
    tools = YouTools(livecrawl="web", search_params={"livecrawl": "news"})

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("q")

    params = client.get.call_args.kwargs["params"]
    assert params["livecrawl"] == "news"


def test_crawl_timeout_validation():
    with pytest.raises(ValueError, match="crawl_timeout must be between 1 and 60 seconds"):
        YouTools(crawl_timeout=0)

    with pytest.raises(ValueError, match="crawl_timeout must be between 1 and 60 seconds"):
        YouTools(crawl_timeout=61)


def test_search_markdown_format():
    tools = YouTools(format="markdown")

    payload = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Hello",
                "description": "world",
                "markdown": "body",
            }
        ]
    }
    patcher, _ = _patch_client(payload)
    with patcher:
        result = tools.you_search("hi")

    assert "# Results for: hi" in result
    assert "[Hello](https://example.com)" in result
    assert "world" in result
    assert "body" in result


def test_search_text_truncation():
    tools = YouTools(text_length_limit=10)

    long_text = "x" * 200
    patcher, _ = _patch_client({"results": [{"url": "https://example.com", "markdown": long_text}]})
    with patcher:
        result = tools.you_search("query")

    parsed = json.loads(result)
    assert parsed[0]["text"] == "x" * 10


def test_search_falls_back_to_default_count():
    tools = YouTools(num_results=8)

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("query")

    assert client.get.call_args.kwargs["params"]["count"] == 8


def test_search_http_error_returns_message(youcom_tools):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = httpx.ConnectError("connection failed")
    with (
        patch("agno.tools.youcom.search.httpx.Client", return_value=client),
        patch("agno.tools.youcom.search.log_error") as mock_log_error,
    ):
        result = youcom_tools.you_search("query")
    assert result.startswith("Error:")
    mock_log_error.assert_called_once()
