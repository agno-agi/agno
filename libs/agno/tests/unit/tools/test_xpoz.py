"""Unit tests for Xpoz toolkit classes."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.xpoz.account import XpozAccountTools
from agno.tools.xpoz.instagram import XpozInstagramTools
from agno.tools.xpoz.reddit import XpozRedditTools
from agno.tools.xpoz.tiktok import XpozTiktokTools
from agno.tools.xpoz.tracking import XpozTrackingTools
from agno.tools.xpoz.twitter import XpozTwitterTools


# ============================================================================
# FIXTURES
# ============================================================================


def _mock_paginated_result(data_items, total_rows=None):
    """Create a mock PaginatedResult."""
    mock = Mock()
    mock.data = data_items
    mock.pagination = Mock()
    mock.pagination.total_rows = total_rows if total_rows is not None else len(data_items)
    return mock


def _mock_model(data):
    """Create a mock Pydantic model with model_dump."""
    mock = Mock()
    mock.model_dump.return_value = data
    return mock


@pytest.fixture
def mock_xpoz_client():
    """Create a mock XpozClient."""
    with patch("agno.tools.xpoz._client.XpozClient") as mock_client_cls:
        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def twitter_tools(mock_xpoz_client):
    """Create XpozTwitterTools with mocked client."""
    with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
        tools = XpozTwitterTools()
        tools._client = mock_xpoz_client
        return tools


@pytest.fixture
def instagram_tools(mock_xpoz_client):
    """Create XpozInstagramTools with mocked client."""
    with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
        tools = XpozInstagramTools()
        tools._client = mock_xpoz_client
        return tools


@pytest.fixture
def reddit_tools(mock_xpoz_client):
    """Create XpozRedditTools with mocked client."""
    with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
        tools = XpozRedditTools()
        tools._client = mock_xpoz_client
        return tools


@pytest.fixture
def tiktok_tools(mock_xpoz_client):
    """Create XpozTiktokTools with mocked client."""
    with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
        tools = XpozTiktokTools()
        tools._client = mock_xpoz_client
        return tools


@pytest.fixture
def tracking_tools(mock_xpoz_client):
    """Create XpozTrackingTools with mocked client."""
    with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
        tools = XpozTrackingTools()
        tools._client = mock_xpoz_client
        return tools


@pytest.fixture
def account_tools(mock_xpoz_client):
    """Create XpozAccountTools with mocked client."""
    with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
        tools = XpozAccountTools()
        tools._client = mock_xpoz_client
        return tools


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_twitter_tools_init_with_env_var():
    """Test XpozTwitterTools uses XPOZ_API_KEY env var."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozTwitterTools()
            tool_names = [t.__name__ for t in tools.tools]
            assert "twitter_search_posts" in tool_names
            assert "twitter_get_user" in tool_names
            assert len(tool_names) == 13


def test_twitter_tools_init_with_api_key():
    """Test XpozTwitterTools accepts explicit api_key."""
    with patch("agno.tools.xpoz._client.XpozClient") as mock_cls:
        XpozTwitterTools(api_key="explicit_key")
        mock_cls.assert_called_once_with(api_key="explicit_key", check_update=False, _user_agent="xpoz-agno")


def test_twitter_tools_selective_enable():
    """Test enabling only specific tools."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozTwitterTools(
                enable_search_posts=True,
                enable_get_user=True,
                enable_get_users=False,
                enable_get_posts_by_author=False,
                enable_get_comments=False,
                enable_search_users=False,
                enable_get_user_connections=False,
                enable_get_users_by_keywords=False,
                enable_count_posts=False,
                enable_get_posts_by_ids=False,
                enable_get_retweets=False,
                enable_get_quotes=False,
                enable_get_post_interacting_users=False,
            )
            tool_names = [t.__name__ for t in tools.tools]
            assert tool_names == ["twitter_search_posts", "twitter_get_user"]


def test_twitter_tools_all_flag():
    """Test all=True enables all tools."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozTwitterTools(all=True, enable_search_posts=False, enable_get_user=False)
            assert len(tools.tools) == 13


def test_instagram_tools_init():
    """Test XpozInstagramTools initialization."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozInstagramTools()
            assert len(tools.tools) == 9


def test_reddit_tools_init():
    """Test XpozRedditTools initialization."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozRedditTools()
            assert len(tools.tools) == 9


def test_tiktok_tools_init():
    """Test XpozTiktokTools initialization."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozTiktokTools()
            assert len(tools.tools) == 9


def test_tracking_tools_init():
    """Test XpozTrackingTools initialization."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozTrackingTools()
            assert len(tools.tools) == 3


def test_account_tools_init():
    """Test XpozAccountTools initialization."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            tools = XpozAccountTools()
            assert len(tools.tools) == 1


def test_no_tool_name_collisions():
    """Test that no tool names collide when multiple toolkits are used together."""
    with patch("agno.tools.xpoz._client.XpozClient"):
        with patch.dict("os.environ", {"XPOZ_API_KEY": "test_key"}):
            twitter = XpozTwitterTools()
            instagram = XpozInstagramTools()
            reddit = XpozRedditTools()
            tiktok = XpozTiktokTools()

            all_names = (
                [t.__name__ for t in twitter.tools]
                + [t.__name__ for t in instagram.tools]
                + [t.__name__ for t in reddit.tools]
                + [t.__name__ for t in tiktok.tools]
            )
            assert len(all_names) == len(set(all_names)), f"Duplicate tool names: {[n for n in all_names if all_names.count(n) > 1]}"


# ============================================================================
# TWITTER TOOL TESTS
# ============================================================================


def test_twitter_search_posts(twitter_tools, mock_xpoz_client):
    """Test Twitter search_posts method."""
    mock_post = _mock_model({"id": "123", "text": "test tweet", "authorId": "456"})
    mock_xpoz_client.twitter.search_posts.return_value = _mock_paginated_result([mock_post], total_rows=1)

    result = twitter_tools.twitter_search_posts("AI agents")
    parsed = json.loads(result)

    assert parsed["total_results"] == 1
    assert len(parsed["data"]) == 1
    assert parsed["data"][0]["id"] == "123"
    mock_xpoz_client.twitter.search_posts.assert_called_once_with(
        "AI agents",
        limit=None,
        start_date=None,
        end_date=None,
        language=None,
        author_username=None,
        author_id=None,
        filter_out_retweets=None,
        fields=None,
    )


def test_twitter_get_user(twitter_tools, mock_xpoz_client):
    """Test Twitter get_user method."""
    mock_user = _mock_model({"username": "elonmusk", "followersCount": 100000})
    mock_xpoz_client.twitter.get_user.return_value = mock_user

    result = twitter_tools.twitter_get_user("elonmusk")
    parsed = json.loads(result)

    assert parsed["username"] == "elonmusk"
    mock_xpoz_client.twitter.get_user.assert_called_once_with("elonmusk", identifier_type="username", fields=None)


def test_twitter_count_posts(twitter_tools, mock_xpoz_client):
    """Test Twitter count_posts method."""
    mock_xpoz_client.twitter.count_posts.return_value = 42

    result = twitter_tools.twitter_count_posts("AI agents")
    parsed = json.loads(result)

    assert parsed["count"] == 42


def test_twitter_get_posts_by_ids(twitter_tools, mock_xpoz_client):
    """Test Twitter get_posts_by_ids method."""
    mock_post = _mock_model({"id": "123", "text": "test"})
    mock_xpoz_client.twitter.get_posts_by_ids.return_value = [mock_post]

    result = twitter_tools.twitter_get_posts_by_ids(["123"])
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["id"] == "123"


def test_twitter_search_posts_error(twitter_tools, mock_xpoz_client):
    """Test Twitter search_posts handles errors gracefully."""
    mock_xpoz_client.twitter.search_posts.side_effect = Exception("API Error")

    result = twitter_tools.twitter_search_posts("test query")
    parsed = json.loads(result)

    assert "error" in parsed
    assert "API Error" in parsed["error"]


# ============================================================================
# INSTAGRAM TOOL TESTS
# ============================================================================


def test_instagram_search_posts(instagram_tools, mock_xpoz_client):
    """Test Instagram search_posts method."""
    mock_post = _mock_model({"id": "ig_123", "caption": "test post"})
    mock_xpoz_client.instagram.search_posts.return_value = _mock_paginated_result([mock_post], total_rows=1)

    result = instagram_tools.instagram_search_posts("AI art")
    parsed = json.loads(result)

    assert parsed["total_results"] == 1
    assert parsed["data"][0]["id"] == "ig_123"


def test_instagram_get_user(instagram_tools, mock_xpoz_client):
    """Test Instagram get_user method."""
    mock_user = _mock_model({"username": "natgeo", "followersCount": 50000})
    mock_xpoz_client.instagram.get_user.return_value = mock_user

    result = instagram_tools.instagram_get_user("natgeo")
    parsed = json.loads(result)

    assert parsed["username"] == "natgeo"


# ============================================================================
# REDDIT TOOL TESTS
# ============================================================================


def test_reddit_search_posts(reddit_tools, mock_xpoz_client):
    """Test Reddit search_posts method."""
    mock_post = _mock_model({"id": "r_123", "title": "AI discussion"})
    mock_xpoz_client.reddit.search_posts.return_value = _mock_paginated_result([mock_post], total_rows=1)

    result = reddit_tools.reddit_search_posts("AI agents")
    parsed = json.loads(result)

    assert parsed["total_results"] == 1
    assert parsed["data"][0]["title"] == "AI discussion"


def test_reddit_get_post_with_comments(reddit_tools, mock_xpoz_client):
    """Test Reddit get_post_with_comments method."""
    mock_post = _mock_model({"id": "r_123", "title": "Test post"})
    mock_comment = _mock_model({"id": "c_456", "body": "Great post"})
    mock_result = Mock()
    mock_result.post = mock_post
    mock_result.comments = [mock_comment]
    mock_xpoz_client.reddit.get_post_with_comments.return_value = mock_result

    result = reddit_tools.reddit_get_post_with_comments("r_123")
    parsed = json.loads(result)

    assert parsed["post"]["id"] == "r_123"
    assert len(parsed["comments"]) == 1
    assert parsed["comments"][0]["body"] == "Great post"


def test_reddit_get_subreddit_with_posts(reddit_tools, mock_xpoz_client):
    """Test Reddit get_subreddit_with_posts method."""
    mock_subreddit = _mock_model({"name": "MachineLearning", "subscribers": 3000000})
    mock_post = _mock_model({"id": "r_789", "title": "New paper"})
    mock_result = Mock()
    mock_result.subreddit = mock_subreddit
    mock_result.posts = [mock_post]
    mock_xpoz_client.reddit.get_subreddit_with_posts.return_value = mock_result

    result = reddit_tools.reddit_get_subreddit_with_posts("MachineLearning")
    parsed = json.loads(result)

    assert parsed["subreddit"]["name"] == "MachineLearning"
    assert len(parsed["posts"]) == 1


def test_reddit_null_safety(reddit_tools, mock_xpoz_client):
    """Test Reddit toolkit handles None post/subreddit gracefully."""
    mock_result = Mock()
    mock_result.post = None
    mock_result.comments = []
    mock_xpoz_client.reddit.get_post_with_comments.return_value = mock_result

    result = reddit_tools.reddit_get_post_with_comments("nonexistent")
    parsed = json.loads(result)

    assert parsed["post"] is None
    assert parsed["comments"] == []


# ============================================================================
# TIKTOK TOOL TESTS
# ============================================================================


def test_tiktok_search_posts(tiktok_tools, mock_xpoz_client):
    """Test TikTok search_posts method."""
    mock_post = _mock_model({"id": "tt_123", "description": "AI video"})
    mock_xpoz_client.tiktok.search_posts.return_value = _mock_paginated_result([mock_post], total_rows=1)

    result = tiktok_tools.tiktok_search_posts("AI tutorial")
    parsed = json.loads(result)

    assert parsed["total_results"] == 1
    assert parsed["data"][0]["id"] == "tt_123"


def test_tiktok_get_posts_by_hashtags(tiktok_tools, mock_xpoz_client):
    """Test TikTok get_posts_by_hashtags method."""
    mock_post = _mock_model({"id": "tt_456", "description": "trending"})
    mock_xpoz_client.tiktok.get_posts_by_hashtags.return_value = _mock_paginated_result([mock_post], total_rows=1)

    result = tiktok_tools.tiktok_get_posts_by_hashtags(["ai", "tech"])
    parsed = json.loads(result)

    assert parsed["total_results"] == 1
    mock_xpoz_client.tiktok.get_posts_by_hashtags.assert_called_once()


# ============================================================================
# TRACKING TOOL TESTS
# ============================================================================


def test_tracking_get_tracked_items(tracking_tools, mock_xpoz_client):
    """Test Tracking get_tracked_items method."""
    mock_item = _mock_model({"phrase": "AI", "type": "keyword", "platform": "twitter"})
    mock_xpoz_client.tracking.get_tracked_items.return_value = [mock_item]

    result = tracking_tools.tracking_get_tracked_items()
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["phrase"] == "AI"


def test_tracking_add_tracked_items(tracking_tools, mock_xpoz_client):
    """Test Tracking add_tracked_items method."""
    mock_result = _mock_model({"added": 2, "items": [{"phrase": "AI", "type": "keyword", "platform": "twitter"}]})
    mock_xpoz_client.tracking.add_tracked_items.return_value = mock_result

    with patch("xpoz.types.tracking.TrackedItem") as mock_tracked_item_cls:
        mock_tracked_item_cls.side_effect = lambda **kwargs: Mock(**kwargs)
        result = tracking_tools.tracking_add_tracked_items(
            [{"phrase": "AI", "type": "keyword", "platform": "twitter"}]
        )
        parsed = json.loads(result)

    assert parsed["added"] == 2
    mock_xpoz_client.tracking.add_tracked_items.assert_called_once()


def test_tracking_remove_tracked_items(tracking_tools, mock_xpoz_client):
    """Test Tracking remove_tracked_items method."""
    mock_result = _mock_model({"removed": 1})
    mock_xpoz_client.tracking.remove_tracked_items.return_value = mock_result

    with patch("xpoz.types.tracking.TrackedItem") as mock_tracked_item_cls:
        mock_tracked_item_cls.side_effect = lambda **kwargs: Mock(**kwargs)
        result = tracking_tools.tracking_remove_tracked_items(
            [{"phrase": "AI", "type": "keyword", "platform": "twitter"}]
        )
        parsed = json.loads(result)

    assert parsed["removed"] == 1
    mock_xpoz_client.tracking.remove_tracked_items.assert_called_once()


# ============================================================================
# ACCOUNT TOOL TESTS
# ============================================================================


def test_account_get_details(account_tools, mock_xpoz_client):
    """Test Account get_account_details method."""
    mock_details = _mock_model({"plan": "pro", "usage": {"credits": 1000}})
    mock_xpoz_client.account.get_account_details.return_value = mock_details

    result = account_tools.account_get_account_details()
    parsed = json.loads(result)

    assert parsed["plan"] == "pro"
    assert parsed["usage"]["credits"] == 1000
