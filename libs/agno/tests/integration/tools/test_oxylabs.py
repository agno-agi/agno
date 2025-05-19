import pytest
from unittest.mock import MagicMock
from agno.tools.oxylabs import OxylabsTools

@pytest.fixture
def oxylabs_tools():
    tool = OxylabsTools(username="fake_user", password="fake_pass")
    # Patch the client methods to avoid real API calls
    tool.client.google.scrape_search = MagicMock(return_value=MagicMock(raw={"results": [{"content": {"foo": "bar"}}]}))
    tool.client.amazon.scrape_product = MagicMock(return_value=MagicMock(raw={"results": [{"content": {"asin": "B000123"}}]}))
    tool.client.amazon.scrape_search = MagicMock(return_value=MagicMock(raw={"results": [{"content": {"title": "Magic Mouse"}}]}))
    tool.client.universal.scrape_url = MagicMock(return_value=MagicMock(raw={"results": [{"content": {"url": "https://example.com"}}]}))
    return tool

OX_TOOLS_TESTS_PARAMS = [
    pytest.param(
        "google_search",
        {"query": "test"},
        "foo",
        id="google_search_successful_response",
    ),
    pytest.param(
        "amazon_product",
        {"query": "B000123"},
        "asin",
        id="amazon_product_successful_response",
    ),
    pytest.param(
        "amazon_search",
        {"query": "Magic Mouse"},
        "title",
        id="amazon_search_successful_response",
    ),
    pytest.param(
        "universal",
        {"url": "https://example.com"},
        "url",
        id="universal_successful_response",
    ),
]

@pytest.mark.parametrize(
    ("method_name", "payload", "expected_key"),
    OX_TOOLS_TESTS_PARAMS,
)
def test_oxylabs_tools_methods(oxylabs_tools, method_name, payload, expected_key):
    method = getattr(oxylabs_tools, method_name)
    result = method(**payload)
    assert expected_key in result

