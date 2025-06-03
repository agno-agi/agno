"""Unit tests for OxylabsTools class."""

import json
from unittest.mock import ANY, Mock, patch

import pytest

from agno.tools.oxylabs import OxylabsTools


@pytest.fixture
def mock_oxylabs_client():
    """Create a mocked Oxylabs RealtimeClient with all resource methods stubbed."""
    with patch("agno.tools.oxylabs.RealtimeClient") as mock_realtime_client:
        # Primary client mock returned by the SDK constructor
        mock_client = Mock()

        # Mock nested resource clients
        mock_client.google = Mock()
        mock_client.amazon = Mock()
        mock_client.universal = Mock()

        # Stub API method return values (each exposes a ``raw`` attribute)
        mock_client.google.scrape_search.return_value = Mock(raw={"results": ["g1", "g2"]})
        mock_client.amazon.scrape_product.return_value = Mock(raw={"title": "Some Product"})
        mock_client.universal.scrape_url.return_value = Mock(raw={"body": "<html></html>"})
        mock_client.amazon.scrape_search.return_value = Mock(raw={"results": ["ap1", "ap2"]})

        # Ensure the SDK constructor returns our prepared client
        mock_realtime_client.return_value = mock_client
        yield mock_client


@pytest.fixture
def oxylabs_tools(mock_oxylabs_client):
    """Return an ``OxylabsTools`` instance wired to the mocked client."""
    return OxylabsTools(username="user", password="pass")


def test_init_with_credentials():
    """SDK is initialised with the supplied credentials."""
    with patch("agno.tools.oxylabs.RealtimeClient") as mock_realtime_client:
        OxylabsTools(username="user", password="pass")
        mock_realtime_client.assert_called_once_with("user", "pass", sdk_type=ANY)


def test_init_with_env_vars(monkeypatch):
    """SDK falls back to environment variables when no credentials are passed in."""
    monkeypatch.setenv("OXYLABS_USERNAME", "env_user")
    monkeypatch.setenv("OXYLABS_PASSWORD", "env_pass")
    with patch("agno.tools.oxylabs.RealtimeClient") as mock_realtime_client:
        OxylabsTools()  # credentials taken from environment
        mock_realtime_client.assert_called_once_with("env_user", "env_pass", sdk_type=ANY)


def test_google_search(oxylabs_tools, mock_oxylabs_client):
    params = {"query": "test", "page": 1}
    result_json = oxylabs_tools.google_search(**params)
    assert json.loads(result_json) == {"results": ["g1", "g2"]}
    mock_oxylabs_client.google.scrape_search.assert_called_once_with(**params)


def test_amazon_product(oxylabs_tools, mock_oxylabs_client):
    params = {"asin": "B000123"}
    result_json = oxylabs_tools.amazon_product(**params)
    assert json.loads(result_json) == {"title": "Some Product"}
    mock_oxylabs_client.amazon.scrape_product.assert_called_once_with(**params)


def test_universal(oxylabs_tools, mock_oxylabs_client):
    params = {"url": "https://example.com"}
    result_json = oxylabs_tools.universal(**params)
    assert json.loads(result_json) == {"body": "<html></html>"}
    mock_oxylabs_client.universal.scrape_url.assert_called_once_with(**params)


def test_amazon_search(oxylabs_tools, mock_oxylabs_client):
    params = {"query": "headphones", "page": 2}
    result_json = oxylabs_tools.amazon_search(**params)
    assert json.loads(result_json) == {"results": ["ap1", "ap2"]}
    mock_oxylabs_client.amazon.scrape_search.assert_called_once_with(**params)
