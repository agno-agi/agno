import json
from unittest.mock import patch

import httpx
import pytest

from agno.tools.keenable import KeenableTools

SEARCH_BODY = {
    "results": [
        {
            "title": "First result",
            "url": "https://example.com/first",
            # The API populates `snippet` with the page text and often leaves
            # `description` empty, so results are mapped from `snippet` first.
            "description": "",
            "snippet": "About the first result.",
        },
        {
            "title": "Second result",
            "url": "https://example.com/second",
            "description": "About the second result.",
            "snippet": "",
        },
    ]
}

FETCH_BODY = {
    "url": "https://example.com/article",
    "title": "An article",
    "content": "The article body as markdown.",
}


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)
    monkeypatch.delenv("KEENABLE_API_URL", raising=False)


def _response(status_code=200, body=None):
    return httpx.Response(status_code=status_code, json=body if body is not None else SEARCH_BODY)


def test_keyless_by_default():
    """With no API key the public endpoint is used and no key header is sent."""
    tools = KeenableTools()
    assert tools.api_key is None

    with patch("agno.tools.keenable.httpx.post", return_value=_response()) as mock_post:
        tools.web_search("small language models")

    called_url = mock_post.call_args.args[0]
    headers = mock_post.call_args.kwargs["headers"]
    assert called_url == "https://api.keenable.ai/v1/search/public"
    assert "X-API-Key" not in headers
    assert headers["X-Keenable-Title"] == "Agno"


def test_api_key_switches_to_keyed_endpoint():
    tools = KeenableTools(api_key="test_key")

    with patch("agno.tools.keenable.httpx.post", return_value=_response()) as mock_post:
        tools.web_search("query")

    assert mock_post.call_args.args[0] == "https://api.keenable.ai/v1/search"
    assert mock_post.call_args.kwargs["headers"]["X-API-Key"] == "test_key"


def test_api_key_from_env_var(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_KEY", "env_key")
    assert KeenableTools().api_key == "env_key"


def test_base_url_from_env_var(monkeypatch):
    monkeypatch.setenv("KEENABLE_API_URL", "https://api-test.keenable.ai/")
    assert KeenableTools().base_url == "https://api-test.keenable.ai"


def test_toolkit_registers_functions_by_flag():
    assert [f.name for f in KeenableTools().functions.values()] == ["web_search"]
    assert [f.name for f in KeenableTools(enable_search=False, enable_fetch=True).functions.values()] == [
        "fetch_url_content"
    ]
    assert sorted(f.name for f in KeenableTools(all=True).functions.values()) == [
        "fetch_url_content",
        "web_search",
    ]
    assert KeenableTools().name == "keenable_tools"


def test_search_returns_markdown():
    with patch("agno.tools.keenable.httpx.post", return_value=_response()):
        output = KeenableTools().web_search("query")

    assert output.startswith("# query")
    assert "[First result](https://example.com/first)" in output
    assert "About the first result." in output
    assert "About the second result." in output


def test_search_returns_json():
    with patch("agno.tools.keenable.httpx.post", return_value=_response()):
        output = KeenableTools(format="json").web_search("query")

    payload = json.loads(output)
    assert payload["query"] == "query"
    assert [r["url"] for r in payload["results"]] == [
        "https://example.com/first",
        "https://example.com/second",
    ]


def test_search_respects_max_results():
    with patch("agno.tools.keenable.httpx.post", return_value=_response()):
        output = KeenableTools(format="json", max_results=1).web_search("query")

    assert len(json.loads(output)["results"]) == 1


def test_search_rejects_negative_max_results():
    assert "cannot be negative" in KeenableTools().web_search("query", max_results=-1)


def test_search_rejects_empty_query():
    assert "non-empty search query" in KeenableTools().web_search("   ")


def test_search_sends_pro_mode():
    with patch("agno.tools.keenable.httpx.post", return_value=_response()) as mock_post:
        KeenableTools().web_search("query")

    assert mock_post.call_args.kwargs["json"] == {"query": "query", "mode": "pro"}


def test_search_skips_results_without_url():
    body = {"results": [{"title": "No URL", "snippet": "dropped"}, SEARCH_BODY["results"][0]]}
    with patch("agno.tools.keenable.httpx.post", return_value=_response(body=body)):
        output = KeenableTools(format="json").web_search("query")

    assert [r["url"] for r in json.loads(output)["results"]] == ["https://example.com/first"]


def test_search_prefers_snippet_over_empty_description():
    """`description` is frequently empty while `snippet` holds the page text."""
    with patch("agno.tools.keenable.httpx.post", return_value=_response()):
        payload = json.loads(KeenableTools(format="json").web_search("query"))

    assert [r["content"] for r in payload["results"]] == [
        "About the first result.",
        "About the second result.",
    ]


def test_search_collapses_and_truncates_snippets():
    """Raw page text arrives with newlines, which would break the markdown layout."""
    body = {"results": [{"title": "T", "url": "https://example.com/x", "snippet": "one\ntwo   three\n\nfour"}]}
    with patch("agno.tools.keenable.httpx.post", return_value=_response(body=body)):
        payload = json.loads(KeenableTools(format="json").web_search("query"))
    assert payload["results"][0]["content"] == "one two three four"

    with patch("agno.tools.keenable.httpx.post", return_value=_response(body=body)):
        payload = json.loads(KeenableTools(format="json", max_snippet_chars=7).web_search("query"))
    assert payload["results"][0]["content"] == "one two…"

    with patch("agno.tools.keenable.httpx.post", return_value=_response(body=body)):
        payload = json.loads(KeenableTools(format="json", max_snippet_chars=0).web_search("query"))
    assert payload["results"][0]["content"] == "one two three four"


def test_search_handles_unexpected_shape():
    with patch("agno.tools.keenable.httpx.post", return_value=_response(body={"unexpected": True})):
        assert "unexpected response" in KeenableTools().web_search("query")


def test_search_surfaces_rate_limit():
    body = {"message": "too many requests"}
    with patch("agno.tools.keenable.httpx.post", return_value=_response(status_code=429, body=body)):
        output = KeenableTools().web_search("query")

    assert "Keenable rate limit exceeded (429)" in output
    assert "too many requests" in output


def test_search_surfaces_transport_error():
    with patch("agno.tools.keenable.httpx.post", side_effect=httpx.ConnectError("boom")):
        assert "Error performing search: boom" in KeenableTools().web_search("query")


def test_fetch_returns_content():
    with patch("agno.tools.keenable.httpx.get", return_value=_response(body=FETCH_BODY)) as mock_get:
        output = KeenableTools(enable_fetch=True).fetch_url_content("https://example.com/article")

    assert mock_get.call_args.args[0] == "https://api.keenable.ai/v1/fetch/public"
    assert mock_get.call_args.kwargs["params"] == {"url": "https://example.com/article"}
    assert output == "## An article\n\nThe article body as markdown."


def test_fetch_rejects_non_http_scheme():
    output = KeenableTools(enable_fetch=True).fetch_url_content("file:///etc/passwd")
    assert "non-http(s) URL" in output


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1:8080/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_fetch_rejects_private_targets(url):
    """The backend guards this too, but an internal host should never leave the machine."""
    with patch("agno.tools.keenable.httpx.get") as mock_get:
        output = KeenableTools(enable_fetch=True).fetch_url_content(url)

    assert "private/internal host" in output
    mock_get.assert_not_called()


def test_fetch_reports_empty_content():
    body = {"url": "https://example.com/empty", "title": "Empty"}
    with patch("agno.tools.keenable.httpx.get", return_value=_response(body=body)):
        output = KeenableTools(enable_fetch=True).fetch_url_content("https://example.com/empty")

    assert "No content could be extracted" in output


def test_base_url_must_be_https():
    tools = KeenableTools(base_url="http://api.keenable.ai")
    with pytest.raises(ValueError, match="must be an https:// URL"):
        tools._resolved_base_url()


def test_base_url_allows_loopback_http():
    tools = KeenableTools(base_url="http://localhost:8080")
    assert tools._resolved_base_url() == "http://localhost:8080"
