import json
from unittest.mock import MagicMock

import pytest

from agno.tools.bingsearch import BingSearchTools


@pytest.fixture
def bing_tools():
    tools = BingSearchTools(subscription_key="dummy_key")
    # Directly mock the session object
    tools.session = MagicMock()
    return tools


def test_initialization():
    # Initialize with required parameters only
    tools = BingSearchTools(subscription_key="dummy_key")
    assert tools.subscription_key == "dummy_key"
    assert tools.headers == {}
    assert tools.timeout == 10
    assert tools.verify_ssl is True

    # Initialize with optional parameters
    tools = BingSearchTools(
        subscription_key="dummy_key",
        search=True,
        news=False,
        images=False,
        videos=False,
        modifier="site:example.com",
        fixed_max_results=10,
        headers={"User-Agent": "Test"},
        proxy="http://proxy.test",
        timeout=5,
        verify_ssl=False,
    )
    assert tools.subscription_key == "dummy_key"
    assert tools.modifier == "site:example.com"
    assert tools.fixed_max_results == 10
    assert tools.headers == {"User-Agent": "Test"}
    assert tools.proxy == "http://proxy.test"
    assert tools.timeout == 5
    assert tools.verify_ssl is False


def test_initialization_without_key():
    with pytest.raises(ValueError, match="subscription_key is required"):
        BingSearchTools(subscription_key="")


@pytest.mark.parametrize(
    "proxy,proxies,expected",
    [
        (None, None, None),
        ("http://proxy.test", None, {"http": "http://proxy.test", "https": "http://proxy.test"}),
        (
            None,
            {"http": "http://proxy1.test", "https": "https://proxy2.test"},
            {"http": "http://proxy1.test", "https": "https://proxy2.test"},
        ),
    ],
)
def test_prepare_proxies(bing_tools, proxy, proxies, expected):
    bing_tools.proxy = proxy
    bing_tools.proxies = proxies
    assert bing_tools._prepare_proxies() == expected


def test_build_headers(bing_tools):
    # Default headers
    headers = bing_tools._build_headers()
    assert headers == {"Ocp-Apim-Subscription-Key": "dummy_key"}

    # Custom headers
    bing_tools.headers = {"User-Agent": "Test"}
    headers = bing_tools._build_headers()
    assert headers == {
        "Ocp-Apim-Subscription-Key": "dummy_key",
        "User-Agent": "Test",
    }


def test_build_query(bing_tools):
    # Without modifier
    assert bing_tools._build_query("test query") == "test query"

    # With modifier
    bing_tools.modifier = "site:example.com"
    assert bing_tools._build_query("test query") == "site:example.com test query"


def test_perform_request(bing_tools):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"value": "test"}
    bing_tools.session.get.return_value = mock_response

    result = bing_tools._perform_request("https://api.example.com", {"q": "test"})
    assert result == {"value": "test"}

    # Verify request parameters
    bing_tools.session.get.assert_called_once_with(
        "https://api.example.com",
        headers={"Ocp-Apim-Subscription-Key": "dummy_key"},
        params={"q": "test"},
        proxies=None,
        timeout=10,
        verify=True,
    )


def test_bing_search(bing_tools):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "_type": "SearchResponse",
        "queryContext": {"originalQuery": "test query"},
        "webPages": {
            "webSearchUrl": "https://www.bing.com/search?q=test+query",
            "totalEstimatedMatches": 4130000,
            "value": [
                {
                    "id": "https://api.bing.microsoft.com/api/v7/#WebPages.0",
                    "name": "Test Title",
                    "url": "https://test.com",
                    "snippet": "Test Snippet",
                    "datePublished": "2024-02-05T12:00:00.0000000Z",
                    "language": "en",
                    "isFamilyFriendly": True,
                    "displayUrl": "https://test.com",
                    "deepLinks": [{"name": "Deep Link", "url": "https://test.com/deep", "snippet": "Deep Snippet"}],
                }
            ],
        },
    }
    bing_tools.session.get.return_value = mock_response

    result = json.loads(bing_tools.bing_search("test query"))
    assert len(result) == 1
    assert result[0]["title"] == "Test Title"
    assert result[0]["snippet"] == "Test Snippet"
    assert result[0]["link"] == "https://test.com"
    assert result[0]["datePublished"] == "2024-02-05T12:00:00.0000000Z"
    assert len(result[0]["deepLinks"]) == 1

    # Test case for no results
    mock_response.json.return_value = {}
    result = json.loads(bing_tools.bing_search("no results"))
    assert result == [{"Result": "No good Bing Search Result was found"}]


def test_bing_news(bing_tools):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "_type": "News",
        "readLink": "https://api.bing.microsoft.com/api/v7/news/search?q=test+query",
        "queryContext": {"originalQuery": "test query", "adultIntent": False},
        "totalEstimatedMatches": 113,
        "value": [
            {
                "name": "News Title",
                "url": "https://news.com",
                "image": {
                    "thumbnail": {
                        "contentUrl": "https://news.com/image.jpg",
                    }
                },
                "description": "News Description",
                "provider": [{"_type": "Organization", "name": "News Provider"}],
                "datePublished": "2024-02-05T12:00:00.0000000Z",
            }
        ],
    }
    bing_tools.session.get.return_value = mock_response

    result = json.loads(bing_tools.bing_news("test query"))
    assert len(result) == 1
    assert result[0]["title"] == "News Title"
    assert result[0]["snippet"] == "News Description"
    assert result[0]["link"] == "https://news.com"
    assert result[0]["provider"] == "News Provider"
    assert result[0]["datePublished"] == "2024-02-05T12:00:00.0000000Z"
    assert result[0]["image"] == "https://news.com/image.jpg"

    # Test case for no results
    mock_response.json.return_value = {}
    result = json.loads(bing_tools.bing_news("no results"))
    assert result == [{"Result": "No Bing News result was found"}]


def test_bing_images(bing_tools):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "_type": "Images",
        "instrumentation": {"_type": "ResponseInstrumentation"},
        "readLink": "https://api.bing.microsoft.com/api/v7/images/search?q=test+query",
        "queryContext": {
            "originalQuery": "test query",
        },
        "totalEstimatedMatches": 427,
        "value": [
            {
                "name": "Image Title",
                "contentUrl": "https://images.com/image.jpg",
                "thumbnailUrl": "https://images.com/thumbnail.jpg",
                "hostPageUrl": "https://images.com/page",
                "datePublished": "2024-02-05T12:00:00.0000000Z",
                "contentSize": "2570021 B",
                "encodingFormat": "jpeg",
                "width": 800,
                "height": 600,
                "accentColor": "C78504",
            }
        ],
    }
    bing_tools.session.get.return_value = mock_response

    result = json.loads(bing_tools.bing_images("test query"))
    assert len(result) == 1
    assert result[0]["title"] == "Image Title"
    assert result[0]["link"] == "https://images.com/image.jpg"
    assert result[0]["thumbnail"] == "https://images.com/thumbnail.jpg"
    assert result[0]["hostPage"] == "https://images.com/page"
    assert result[0]["datePublished"] == "2024-02-05T12:00:00.0000000Z"
    assert result[0]["width"] == 800
    assert result[0]["height"] == 600

    # Test case for no results
    mock_response.json.return_value = {}
    result = json.loads(bing_tools.bing_images("no results"))
    assert result == [{"Result": "No Bing Images result was found"}]


def test_bing_videos(bing_tools):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "_type": "Videos",
        "instrumentation": {"_type": "ResponseInstrumentation"},
        "readLink": "https://api.bing.microsoft.com/api/v7/videos/search?q=test+query",
        "queryContext": {"originalQuery": "test query"},
        "totalEstimatedMatches": 216,
        "value": [
            {
                "name": "Video Title",
                "description": "Video Description",
                "contentUrl": "https://videos.com/video.mp4",
                "thumbnailUrl": "https://videos.com/thumbnail.jpg",
                "duration": "PT2M30S",
                "datePublished": "2024-02-05T12:00:00.0000000Z",
                "publisher": [{"name": "Publisher"}],
                "viewCount": 1000,
                "encodingFormat": "h264",
            }
        ],
    }
    bing_tools.session.get.return_value = mock_response

    result = json.loads(bing_tools.bing_videos("test query"))
    assert len(result) == 1
    assert result[0]["title"] == "Video Title"
    assert result[0]["snippet"] == "Video Description"
    assert result[0]["link"] == "https://videos.com/video.mp4"
    assert result[0]["thumbnail"] == "https://videos.com/thumbnail.jpg"
    assert result[0]["duration"] == "PT2M30S"
    assert result[0]["datePublished"] == "2024-02-05T12:00:00.0000000Z"
    assert result[0]["viewCount"] == 1000

    # Test case for no results
    mock_response.json.return_value = {}
    result = json.loads(bing_tools.bing_videos("no results"))
    assert result == [{"Result": "No Bing Videos result was found"}]
