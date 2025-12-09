"""Unit tests for HackerNewsTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.hackernews import HackerNewsTools


@pytest.fixture
def hackernews_tools():
    """Create a HackerNewsTools instance with all tools enabled."""
    return HackerNewsTools()


@pytest.fixture
def stories_only_tools():
    """Create a HackerNewsTools instance with only get_top_stories enabled."""
    return HackerNewsTools(enable_get_top_stories=True, enable_get_user_details=False)


@pytest.fixture
def user_details_only_tools():
    """Create a HackerNewsTools instance with only get_user_details enabled."""
    return HackerNewsTools(enable_get_top_stories=False, enable_get_user_details=True)


class TestHackerNewsToolsInitialization:
    """Tests for HackerNewsTools initialization."""

    def test_default_initialization(self):
        """Test default initialization enables all tools."""
        tools = HackerNewsTools()

        function_names = [func.name for func in tools.functions.values()]

        assert "get_top_hackernews_stories" in function_names
        assert "get_user_details" in function_names
        assert tools.name == "hackers_news"

    def test_initialization_with_all_flag(self):
        """Test initialization with all=True enables all tools."""
        tools = HackerNewsTools(enable_get_top_stories=False, enable_get_user_details=False, all=True)

        function_names = [func.name for func in tools.functions.values()]

        assert "get_top_hackernews_stories" in function_names
        assert "get_user_details" in function_names

    def test_initialization_stories_only(self):
        """Test initialization with only stories enabled."""
        tools = HackerNewsTools(enable_get_top_stories=True, enable_get_user_details=False)

        function_names = [func.name for func in tools.functions.values()]

        assert "get_top_hackernews_stories" in function_names
        assert "get_user_details" not in function_names

    def test_initialization_user_details_only(self):
        """Test initialization with only user details enabled."""
        tools = HackerNewsTools(enable_get_top_stories=False, enable_get_user_details=True)

        function_names = [func.name for func in tools.functions.values()]

        assert "get_top_hackernews_stories" not in function_names
        assert "get_user_details" in function_names

    def test_initialization_no_tools_enabled(self):
        """Test initialization with no tools enabled."""
        tools = HackerNewsTools(enable_get_top_stories=False, enable_get_user_details=False)

        function_names = [func.name for func in tools.functions.values()]

        assert "get_top_hackernews_stories" not in function_names
        assert "get_user_details" not in function_names

    def test_toolkit_name(self):
        """Test that toolkit has correct name."""
        tools = HackerNewsTools()
        assert tools.name == "hackers_news"


class TestGetTopHackerNewsStories:
    """Tests for get_top_hackernews_stories method."""

    def test_get_top_stories_default_count(self, hackernews_tools):
        """Test getting top stories with default count."""
        mock_story_ids = [12345, 67890, 11111]
        mock_stories = [
            {"id": 12345, "title": "Story 1", "by": "user1", "url": "https://example1.com"},
            {"id": 67890, "title": "Story 2", "by": "user2", "url": "https://example2.com"},
            {"id": 11111, "title": "Story 3", "by": "user3", "url": "https://example3.com"},
        ]

        def mock_get(url):
            response = MagicMock()
            if "topstories" in url:
                response.json.return_value = mock_story_ids
            else:
                # Extract story ID from URL
                story_id = int(url.split("/")[-1].replace(".json", ""))
                story = next((s for s in mock_stories if s["id"] == story_id), None)
                response.json.return_value = story
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=3)

        stories = json.loads(result)
        assert len(stories) == 3
        assert stories[0]["title"] == "Story 1"
        assert stories[0]["username"] == "user1"
        assert stories[1]["title"] == "Story 2"
        assert stories[2]["title"] == "Story 3"

    def test_get_top_stories_custom_count(self, hackernews_tools):
        """Test getting top stories with custom count."""
        mock_story_ids = [1, 2, 3, 4, 5]
        mock_stories = {
            1: {"id": 1, "title": "Story 1", "by": "user1"},
            2: {"id": 2, "title": "Story 2", "by": "user2"},
        }

        def mock_get(url):
            response = MagicMock()
            if "topstories" in url:
                response.json.return_value = mock_story_ids
            else:
                story_id = int(url.split("/")[-1].replace(".json", ""))
                response.json.return_value = mock_stories.get(story_id, {})
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=2)

        stories = json.loads(result)
        assert len(stories) == 2

    def test_get_top_stories_adds_username_field(self, hackernews_tools):
        """Test that username field is added from 'by' field."""
        mock_story_ids = [12345]
        mock_story = {"id": 12345, "title": "Test Story", "by": "testuser", "score": 100}

        def mock_get(url):
            response = MagicMock()
            if "topstories" in url:
                response.json.return_value = mock_story_ids
            else:
                response.json.return_value = mock_story
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=1)

        stories = json.loads(result)
        assert stories[0]["username"] == "testuser"
        assert stories[0]["by"] == "testuser"

    def test_get_top_stories_empty_response(self, hackernews_tools):
        """Test handling of empty story list."""

        def mock_get(url):
            response = MagicMock()
            response.json.return_value = []
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=10)

        stories = json.loads(result)
        assert len(stories) == 0

    def test_get_top_stories_with_story_metadata(self, hackernews_tools):
        """Test that all story metadata is preserved."""
        mock_story_ids = [12345]
        mock_story = {
            "id": 12345,
            "title": "Test Story",
            "by": "testuser",
            "score": 100,
            "time": 1234567890,
            "descendants": 50,
            "url": "https://example.com/story",
            "type": "story",
        }

        def mock_get(url):
            response = MagicMock()
            if "topstories" in url:
                response.json.return_value = mock_story_ids
            else:
                response.json.return_value = mock_story
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=1)

        stories = json.loads(result)
        assert stories[0]["id"] == 12345
        assert stories[0]["score"] == 100
        assert stories[0]["time"] == 1234567890
        assert stories[0]["descendants"] == 50
        assert stories[0]["url"] == "https://example.com/story"


class TestGetUserDetails:
    """Tests for get_user_details method."""

    def test_get_user_details_success(self, hackernews_tools):
        """Test successful user details retrieval."""
        mock_user = {
            "id": "testuser",
            "karma": 5000,
            "about": "A test user",
            "submitted": [1, 2, 3, 4, 5],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_user

        with patch("agno.tools.hackernews.httpx.get", return_value=mock_response):
            result = hackernews_tools.get_user_details("testuser")

        user_details = json.loads(result)
        assert user_details["karma"] == 5000
        assert user_details["about"] == "A test user"
        assert user_details["total_items_submitted"] == 5

    def test_get_user_details_user_id_field(self, hackernews_tools):
        """Test that user_id is extracted correctly."""
        mock_user = {
            "user_id": "testuser123",
            "karma": 1000,
            "about": None,
            "submitted": [],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_user

        with patch("agno.tools.hackernews.httpx.get", return_value=mock_response):
            result = hackernews_tools.get_user_details("testuser123")

        user_details = json.loads(result)
        assert user_details["id"] == "testuser123"

    def test_get_user_details_no_submitted_items(self, hackernews_tools):
        """Test user with no submitted items."""
        mock_user = {
            "id": "newuser",
            "karma": 1,
            "about": "New to HN",
            # No 'submitted' key
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_user

        with patch("agno.tools.hackernews.httpx.get", return_value=mock_response):
            result = hackernews_tools.get_user_details("newuser")

        user_details = json.loads(result)
        assert user_details["total_items_submitted"] == 0

    def test_get_user_details_empty_about(self, hackernews_tools):
        """Test user with empty about field."""
        mock_user = {
            "id": "quietuser",
            "karma": 500,
            "submitted": [1, 2],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_user

        with patch("agno.tools.hackernews.httpx.get", return_value=mock_response):
            result = hackernews_tools.get_user_details("quietuser")

        user_details = json.loads(result)
        assert user_details["about"] is None

    def test_get_user_details_error_handling(self, hackernews_tools):
        """Test error handling when API call fails."""
        with patch("agno.tools.hackernews.httpx.get", side_effect=Exception("Network error")):
            result = hackernews_tools.get_user_details("testuser")

        assert "Error getting user details" in result
        assert "Network error" in result

    def test_get_user_details_null_user(self, hackernews_tools):
        """Test handling of non-existent user (returns null)."""
        mock_response = MagicMock()
        mock_response.json.return_value = None

        with patch("agno.tools.hackernews.httpx.get", return_value=mock_response):
            result = hackernews_tools.get_user_details("nonexistentuser12345")

        # Should handle None gracefully by catching the exception
        assert "Error getting user details" in result


class TestToolkitIntegration:
    """Integration tests for HackerNewsTools as a Toolkit."""

    def test_tools_list_populated(self, hackernews_tools):
        """Test that tools list is properly populated."""
        assert len(hackernews_tools.tools) == 2

    def test_tools_list_stories_only(self, stories_only_tools):
        """Test tools list with only stories enabled."""
        assert len(stories_only_tools.tools) == 1
        assert stories_only_tools.tools[0].__name__ == "get_top_hackernews_stories"

    def test_tools_list_user_details_only(self, user_details_only_tools):
        """Test tools list with only user details enabled."""
        assert len(user_details_only_tools.tools) == 1
        assert user_details_only_tools.tools[0].__name__ == "get_user_details"

    def test_functions_dict_populated(self, hackernews_tools):
        """Test that functions dict is properly populated."""
        function_names = list(hackernews_tools.functions.keys())
        assert "get_top_hackernews_stories" in function_names
        assert "get_user_details" in function_names


class TestEdgeCases:
    """Edge case tests for HackerNewsTools."""

    def test_get_top_stories_zero_count(self, hackernews_tools):
        """Test requesting zero stories."""
        mock_story_ids = [1, 2, 3]

        def mock_get(url):
            response = MagicMock()
            response.json.return_value = mock_story_ids
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=0)

        stories = json.loads(result)
        assert len(stories) == 0

    def test_get_top_stories_more_than_available(self, hackernews_tools):
        """Test requesting more stories than available."""
        mock_story_ids = [1, 2]
        mock_stories = {
            1: {"id": 1, "title": "Story 1", "by": "user1"},
            2: {"id": 2, "title": "Story 2", "by": "user2"},
        }

        def mock_get(url):
            response = MagicMock()
            if "topstories" in url:
                response.json.return_value = mock_story_ids
            else:
                story_id = int(url.split("/")[-1].replace(".json", ""))
                response.json.return_value = mock_stories.get(story_id, {})
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=100)

        stories = json.loads(result)
        assert len(stories) == 2  # Only 2 available

    def test_get_user_details_special_characters_username(self, hackernews_tools):
        """Test user details with special characters in username."""
        mock_user = {
            "id": "user_with-special.chars",
            "karma": 100,
            "about": "Test",
            "submitted": [],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_user

        with patch("agno.tools.hackernews.httpx.get", return_value=mock_response):
            result = hackernews_tools.get_user_details("user_with-special.chars")

        user_details = json.loads(result)
        assert user_details["karma"] == 100

    def test_get_top_stories_high_karma_user(self, hackernews_tools):
        """Test story from high karma user."""
        mock_story_ids = [12345]
        mock_story = {
            "id": 12345,
            "title": "Story from popular user",
            "by": "pg",  # Paul Graham's username
            "score": 5000,
        }

        def mock_get(url):
            response = MagicMock()
            if "topstories" in url:
                response.json.return_value = mock_story_ids
            else:
                response.json.return_value = mock_story
            return response

        with patch("agno.tools.hackernews.httpx.get", side_effect=mock_get):
            result = hackernews_tools.get_top_hackernews_stories(num_stories=1)

        stories = json.loads(result)
        assert stories[0]["by"] == "pg"
        assert stories[0]["score"] == 5000
