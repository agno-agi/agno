import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.string_web_access import StringWebAccessTools

TEST_API_KEY = "test_api_key"


@pytest.fixture
def tools():
    return StringWebAccessTools(api_key=TEST_API_KEY)


def _mock_response(*, json_body=None, text=None):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = json_body
    response.text = text
    return response


def test_init_reads_api_key_from_env():
    with patch.dict("os.environ", {"STRING_API_KEY": "env_api_key"}, clear=True):
        tools = StringWebAccessTools()
        assert tools.api_key == "env_api_key"


def test_init_registers_search_and_fetch_by_default(tools):
    registered = {function.name for function in tools.functions.values()}
    assert registered == {"search_web", "fetch_url"}


def test_all_registers_every_tool():
    tools = StringWebAccessTools(api_key=TEST_API_KEY, all=True)
    registered = {function.name for function in tools.functions.values()}
    assert registered == {"search_web", "fetch_url", "extract_from_url"}


def test_search_web_returns_organic_results(tools):
    body = {
        "results": [
            {"position": 1, "title": "First", "url": "https://example.com/1", "snippet": "One"},
            {"position": 2, "title": "Second", "url": "https://example.com/2", "snippet": "Two"},
        ],
        "zeroResults": False,
    }
    with patch("agno.tools.string_web_access.httpx.post", return_value=_mock_response(json_body=body)) as post:
        result = tools.search_web("running shoes")

    assert json.loads(result) == body["results"]
    _, kwargs = post.call_args
    assert kwargs["json"] == {"query": "running shoes", "engine": "google", "country": "US"}
    assert kwargs["headers"]["Authorization"] == f"Bearer {TEST_API_KEY}"


def test_search_web_respects_max_results(tools):
    body = {"results": [{"position": n} for n in range(1, 6)], "zeroResults": False}
    with patch("agno.tools.string_web_access.httpx.post", return_value=_mock_response(json_body=body)):
        result = tools.search_web("anything", max_results=2)

    assert len(json.loads(result)) == 2


def test_search_web_reports_no_results(tools):
    with patch(
        "agno.tools.string_web_access.httpx.post",
        return_value=_mock_response(json_body={"results": [], "zeroResults": True}),
    ):
        assert "No results found" in tools.search_web("nothing at all")


def test_fetch_url_requests_markdown(tools):
    with patch("agno.tools.string_web_access.httpx.post", return_value=_mock_response(text="# Title")) as post:
        assert tools.fetch_url("https://example.com") == "# Title"

    _, kwargs = post.call_args
    assert kwargs["json"] == {
        "url": "https://example.com",
        "format": "markdown",
        "markdownMode": "full",
        "mainContentOnly": False,
    }


def test_fetch_url_passes_rendering_and_proxy_options():
    tools = StringWebAccessTools(api_key=TEST_API_KEY, execute_js=True, country_code="GB", main_content_only=True)
    with patch("agno.tools.string_web_access.httpx.post", return_value=_mock_response(text="page")) as post:
        tools.fetch_url("https://example.com")

    _, kwargs = post.call_args
    assert kwargs["json"]["executeJS"] is True
    assert kwargs["json"]["countryCode"] == "GB"
    assert kwargs["json"]["mainContentOnly"] is True


def test_fetch_url_truncates_to_max_content_length():
    tools = StringWebAccessTools(api_key=TEST_API_KEY, max_content_length=4)
    with patch("agno.tools.string_web_access.httpx.post", return_value=_mock_response(text="abcdefgh")):
        assert tools.fetch_url("https://example.com") == "abcd..."


def test_extract_from_url_sends_schema():
    tools = StringWebAccessTools(api_key=TEST_API_KEY, enable_extract=True)
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    with patch(
        "agno.tools.string_web_access.httpx.post",
        return_value=_mock_response(json_body={"title": "A Light in the Attic"}),
    ) as post:
        result = tools.extract_from_url("https://example.com", schema)

    assert json.loads(result) == {"title": "A Light in the Attic"}
    _, kwargs = post.call_args
    assert kwargs["json"] == {"url": "https://example.com", "format": "json", "jsonSchema": schema}


def test_missing_api_key_returns_a_message_instead_of_calling_the_api():
    with patch.dict("os.environ", {}, clear=True):
        tools = StringWebAccessTools()
    with patch("agno.tools.string_web_access.httpx.post") as post:
        result = tools.search_web("anything")

    post.assert_not_called()
    assert "STRING_API_KEY not set" in result


def test_http_error_is_returned_as_a_message(tools):
    with patch("agno.tools.string_web_access.httpx.post", side_effect=RuntimeError("boom")):
        result = tools.fetch_url("https://example.com")

    assert "Error calling String Web Access /fetch" in result
    assert "boom" in result
