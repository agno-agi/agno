"""Unit tests for XquikTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.xquik import XquikTools


@pytest.fixture
def xquik_tools():
    """Create XquikTools instance with a test API key."""
    with patch.dict("os.environ", {"XQUIK_API_KEY": "xk_test_key"}):
        return XquikTools()


@pytest.fixture
def xquik_tools_no_metrics():
    """Create XquikTools instance with metrics disabled."""
    with patch.dict("os.environ", {"XQUIK_API_KEY": "xk_test_key"}):
        return XquikTools(include_post_metrics=False)


def _mock_urlopen(response_data: dict):
    """Helper to create a mock for urllib.request.urlopen."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(response_data).encode("utf-8")
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class TestInit:
    """Tests for XquikTools initialization."""

    def test_init_with_env_var(self):
        """Test initialization with XQUIK_API_KEY env variable."""
        with patch.dict("os.environ", {"XQUIK_API_KEY": "xk_test_key"}):
            tools = XquikTools()
            assert tools.api_key == "xk_test_key"

    def test_init_with_explicit_key(self):
        """Test initialization with explicit API key."""
        tools = XquikTools(api_key="xk_explicit_key")
        assert tools.api_key == "xk_explicit_key"

    def test_init_registers_all_tools(self):
        """Test that all five tools are registered."""
        with patch.dict("os.environ", {"XQUIK_API_KEY": "xk_test_key"}):
            tools = XquikTools()
            tool_names = [func.name for func in tools.functions.values()]
            assert "search_posts" in tool_names
            assert "get_user_info" in tool_names
            assert "get_tweet" in tool_names
            assert "get_user_posts" in tool_names
            assert "get_trends" in tool_names

    def test_init_can_disable_tools(self):
        """Test that registration flags control individual tools."""
        tools = XquikTools(
            api_key="xk_test_key",
            enable_search_posts=True,
            enable_get_user_info=False,
            enable_get_tweet=False,
            enable_get_user_posts=False,
            enable_get_trends=False,
        )

        tool_names = [func.name for func in tools.functions.values()]
        assert tool_names == ["search_posts"]

    def test_init_all_overrides_disabled_tools(self):
        """Test that all=True enables every tool."""
        tools = XquikTools(
            api_key="xk_test_key",
            enable_search_posts=False,
            enable_get_user_info=False,
            enable_get_tweet=False,
            enable_get_user_posts=False,
            enable_get_trends=False,
            all=True,
        )

        tool_names = [func.name for func in tools.functions.values()]
        assert tool_names == [
            "search_posts",
            "get_user_info",
            "get_tweet",
            "get_user_posts",
            "get_trends",
        ]

    def test_init_without_key_logs_error(self):
        """Test that missing API key logs an error."""
        with patch.dict("os.environ", {}, clear=True):
            tools = XquikTools()
            assert tools.api_key is None


class TestSearchPosts:
    """Tests for the search_posts method."""

    def test_request_uses_api_key_header(self, xquik_tools):
        """Test that requests use the documented API key header."""
        mock_data = {"tweets": []}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)) as mock_open:
            xquik_tools.search_posts("hello")
            request = mock_open.call_args[0][0]

        assert request.headers["X-api-key"] == "xk_test_key"
        assert request.headers["Accept"] == "application/json"

    def test_search_success(self, xquik_tools):
        """Test successful search returns formatted posts."""
        mock_data = {
            "tweets": [
                {
                    "id": "123456",
                    "text": "Hello world",
                    "createdAt": "2026-04-10T12:00:00Z",
                    "author": {
                        "id": "789",
                        "name": "Test User",
                        "username": "testuser",
                        "verified": True,
                    },
                    "likeCount": 42,
                    "retweetCount": 5,
                    "replyCount": 3,
                    "quoteCount": 1,
                    "viewCount": 1000,
                    "bookmarkCount": 2,
                }
            ]
        }

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)):
            result = json.loads(xquik_tools.search_posts("hello"))

        assert result["query"] == "hello"
        assert result["count"] == 1
        assert result["posts"][0]["id"] == "123456"
        assert result["posts"][0]["text"] == "Hello world"
        assert result["posts"][0]["author"]["username"] == "testuser"
        assert result["posts"][0]["url"] == "https://x.com/testuser/status/123456"
        assert result["posts"][0]["metrics"]["like_count"] == 42
        assert result["posts"][0]["metrics"]["view_count"] == 1000

    def test_search_without_metrics(self, xquik_tools_no_metrics):
        """Test search with metrics disabled."""
        mock_data = {
            "tweets": [
                {
                    "id": "123",
                    "text": "Test",
                    "createdAt": "",
                    "author": {"id": "1", "name": "User", "username": "user", "verified": False},
                    "likeCount": 10,
                }
            ]
        }

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)):
            result = json.loads(xquik_tools_no_metrics.search_posts("test"))

        assert "metrics" not in result["posts"][0]

    def test_search_clamps_max_results(self, xquik_tools):
        """Test that max_results is clamped to the API maximum."""
        mock_data = {"tweets": []}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)) as mock_open:
            xquik_tools.search_posts("test", max_results=500)
            call_url = mock_open.call_args[0][0].full_url
            assert "limit=200" in call_url

    def test_search_rejects_invalid_max_results(self, xquik_tools):
        """Test that non-positive max_results is rejected before the API call."""
        with patch("urllib.request.urlopen") as mock_open:
            result = json.loads(xquik_tools.search_posts("test", max_results=0))

        assert "error" in result
        assert "greater than 0" in result["error"]
        mock_open.assert_not_called()

    def test_search_requires_query(self, xquik_tools):
        """Test that an empty query is rejected before the API call."""
        with patch("urllib.request.urlopen") as mock_open:
            result = json.loads(xquik_tools.search_posts(""))

        assert "error" in result
        assert "query" in result["error"]
        mock_open.assert_not_called()

    def test_search_empty_results(self, xquik_tools):
        """Test search with no results."""
        mock_data = {"tweets": []}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)):
            result = json.loads(xquik_tools.search_posts("nonexistent"))

        assert result["count"] == 0
        assert result["posts"] == []

    def test_search_error_handling(self, xquik_tools):
        """Test search error returns error JSON."""
        with patch("urllib.request.urlopen", side_effect=Exception("Connection timeout")):
            result = json.loads(xquik_tools.search_posts("test"))

        assert "error" in result
        assert "Connection timeout" in result["error"]
        assert result["query"] == "test"


class TestGetUserInfo:
    """Tests for the get_user_info method."""

    def test_get_user_success(self, xquik_tools):
        """Test successful user lookup."""
        mock_data = {
            "id": "12345",
            "name": "Agno",
            "username": "AgnoAgi",
            "description": "Build AI agents",
            "followers": 50000,
            "following": 100,
            "statusesCount": 2000,
            "verified": True,
        }

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)):
            result = json.loads(xquik_tools.get_user_info("AgnoAgi"))

        assert result["id"] == "12345"
        assert result["username"] == "AgnoAgi"
        assert result["followers_count"] == 50000
        assert result["verified"] is True
        assert result["url"] == "https://x.com/AgnoAgi"

    def test_get_user_strips_at_sign(self, xquik_tools):
        """Test that @ prefix is stripped from username."""
        mock_data = {"id": "1", "name": "User", "username": "user"}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)) as mock_open:
            xquik_tools.get_user_info("@user")
            call_url = mock_open.call_args[0][0].full_url
            assert "/x/users/user" in call_url
            assert "@@" not in call_url

    def test_get_user_encodes_path(self, xquik_tools):
        """Test that user identifiers are URL encoded."""
        mock_data = {"id": "1", "name": "User", "username": "user"}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)) as mock_open:
            xquik_tools.get_user_info("team/user")
            call_url = mock_open.call_args[0][0].full_url

        assert "/x/users/team%2Fuser" in call_url

    def test_get_user_error_handling(self, xquik_tools):
        """Test user lookup error returns error JSON."""
        with patch("urllib.request.urlopen", side_effect=Exception("Not found")):
            result = json.loads(xquik_tools.get_user_info("nonexistent"))

        assert "error" in result
        assert "Not found" in result["error"]


class TestGetTweet:
    """Tests for the get_tweet method."""

    def test_get_tweet_success(self, xquik_tools):
        """Test successful tweet retrieval."""
        mock_data = {
            "id": "987654",
            "text": "A great tweet",
            "createdAt": "2026-04-10T10:00:00Z",
            "author": {
                "id": "111",
                "name": "Poster",
                "username": "poster",
                "verified": False,
            },
            "likeCount": 100,
            "retweetCount": 20,
            "replyCount": 5,
            "quoteCount": 3,
            "viewCount": 5000,
            "bookmarkCount": 10,
        }

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)):
            result = json.loads(xquik_tools.get_tweet("987654"))

        assert result["id"] == "987654"
        assert result["text"] == "A great tweet"
        assert result["author"]["username"] == "poster"
        assert result["metrics"]["like_count"] == 100
        assert result["url"] == "https://x.com/poster/status/987654"

    def test_get_tweet_error_handling(self, xquik_tools):
        """Test tweet retrieval error returns error JSON."""
        with patch("urllib.request.urlopen", side_effect=Exception("Rate limited")):
            result = json.loads(xquik_tools.get_tweet("123"))

        assert "error" in result
        assert "Rate limited" in result["error"]


class TestGetUserPosts:
    """Tests for the get_user_posts method."""

    def test_get_user_posts_success(self, xquik_tools):
        """Test successful user posts retrieval."""
        mock_data = {
            "tweets": [
                {
                    "id": "111",
                    "text": "Latest post",
                    "createdAt": "2026-04-10T12:00:00Z",
                    "author": {
                        "id": "1",
                        "name": "User",
                        "username": "user",
                        "verified": False,
                    },
                    "likeCount": 3,
                }
            ],
            "has_next_page": True,
            "next_cursor": "cursor-1",
        }

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)):
            result = json.loads(xquik_tools.get_user_posts("@user"))

        assert result["username"] == "user"
        assert result["count"] == 1
        assert result["posts"][0]["id"] == "111"
        assert result["posts"][0]["metrics"]["like_count"] == 3
        assert result["has_next_page"] is True
        assert result["next_cursor"] == "cursor-1"

    def test_get_user_posts_params(self, xquik_tools):
        """Test user posts request parameters."""
        mock_data = {"tweets": []}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)) as mock_open:
            xquik_tools.get_user_posts("team/user", cursor="abc", include_replies=True)
            call_url = mock_open.call_args[0][0].full_url

        assert "/x/users/team%2Fuser/tweets" in call_url
        assert "cursor=abc" in call_url
        assert "includeReplies=true" in call_url
        assert "includeParentTweet=false" in call_url

    def test_get_user_posts_error_handling(self, xquik_tools):
        """Test user posts error returns error JSON."""
        with patch("urllib.request.urlopen", side_effect=Exception("Unavailable")):
            result = json.loads(xquik_tools.get_user_posts("user"))

        assert "error" in result
        assert "Unavailable" in result["error"]


class TestGetTrends:
    """Tests for the get_trends method."""

    def test_get_trends_success(self, xquik_tools):
        """Test successful trends retrieval."""
        mock_data = {
            "trends": [
                {"name": "#AI", "volume": 50000},
                {"name": "#Python", "volume": 30000},
            ]
        }

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)):
            result = json.loads(xquik_tools.get_trends())

        assert len(result["trends"]) == 2
        assert result["trends"][0]["name"] == "#AI"

    def test_get_trends_with_woeid(self, xquik_tools):
        """Test trends with specific WOEID."""
        mock_data = {"trends": []}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)) as mock_open:
            xquik_tools.get_trends(woeid=23424977)
            call_url = mock_open.call_args[0][0].full_url
            assert "/x/trends" in call_url
            assert "woeid=23424977" in call_url

    def test_get_trends_clamps_count(self, xquik_tools):
        """Test that count is clamped to max 50."""
        mock_data = {"trends": []}

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(mock_data)) as mock_open:
            xquik_tools.get_trends(count=100)
            call_url = mock_open.call_args[0][0].full_url
            assert "count=50" in call_url

    def test_get_trends_rejects_invalid_count(self, xquik_tools):
        """Test that non-positive count is rejected before the API call."""
        with patch("urllib.request.urlopen") as mock_open:
            result = json.loads(xquik_tools.get_trends(count=0))

        assert "error" in result
        assert "greater than 0" in result["error"]
        mock_open.assert_not_called()

    def test_get_trends_error_handling(self, xquik_tools):
        """Test trends error returns error JSON."""
        with patch("urllib.request.urlopen", side_effect=Exception("Server error")):
            result = json.loads(xquik_tools.get_trends())

        assert "error" in result
        assert "Server error" in result["error"]
