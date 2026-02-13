"""Unit tests for UnsplashTools class."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.tools.unsplash import UnsplashTools


@pytest.fixture
def mock_urlopen():
    """Create a mock urlopen."""
    with patch("agno.tools.unsplash.urlopen") as mock:
        yield mock


@pytest.fixture
def unsplash_tools():
    """Create UnsplashTools instance with mocked API key."""
    with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}):
        return UnsplashTools()


@pytest.fixture
def unsplash_tools_all():
    """Create UnsplashTools instance with all tools enabled."""
    with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}):
        return UnsplashTools(all=True)


def create_mock_photo(
    photo_id: str = "abc123",
    description: str = "A beautiful sunset",
    alt_description: str = "Orange sky over mountains",
    width: int = 4000,
    height: int = 3000,
    color: str = "#FF5733",
    created_at: str = "2024-01-15T12:00:00Z",
    likes: int = 150,
):
    """Helper function to create mock photo data."""
    return {
        "id": photo_id,
        "description": description,
        "alt_description": alt_description,
        "width": width,
        "height": height,
        "color": color,
        "created_at": created_at,
        "likes": likes,
        "urls": {
            "raw": f"https://images.unsplash.com/photo-{photo_id}?format=raw",
            "full": f"https://images.unsplash.com/photo-{photo_id}?format=full",
            "regular": f"https://images.unsplash.com/photo-{photo_id}?format=regular",
            "small": f"https://images.unsplash.com/photo-{photo_id}?format=small",
            "thumb": f"https://images.unsplash.com/photo-{photo_id}?format=thumb",
        },
        "user": {
            "name": "John Photographer",
            "username": "johnphoto",
            "links": {"html": "https://unsplash.com/@johnphoto"},
        },
        "links": {
            "html": f"https://unsplash.com/photos/{photo_id}",
            "download": f"https://unsplash.com/photos/{photo_id}/download",
        },
        "tags": [
            {"title": "sunset"},
            {"title": "mountain"},
            {"title": "nature"},
        ],
    }


def create_mock_response(data):
    """Create a mock HTTP response."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(data).encode()
    mock_response.__enter__ = Mock(return_value=mock_response)
    mock_response.__exit__ = Mock(return_value=False)
    return mock_response


class TestUnsplashToolsInit:
    """Tests for UnsplashTools initialization."""

    def test_init_with_env_api_key(self):
        """Test initialization with API key from environment."""
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "env_test_key"}):
            tools = UnsplashTools()
            assert tools.access_key == "env_test_key"

    def test_init_with_provided_api_key(self):
        """Test initialization with provided API key."""
        tools = UnsplashTools(access_key="provided_key")
        assert tools.access_key == "provided_key"

    def test_init_without_api_key_logs_warning(self):
        """Test initialization without API key logs a warning."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("agno.tools.unsplash.logger") as mock_logger:
                # Remove UNSPLASH_ACCESS_KEY if present
                import os

                old_key = os.environ.pop("UNSPLASH_ACCESS_KEY", None)
                try:
                    tools = UnsplashTools()
                    mock_logger.warning.assert_called_once()
                    assert tools.access_key is None
                finally:
                    if old_key:
                        os.environ["UNSPLASH_ACCESS_KEY"] = old_key

    def test_init_with_default_tools(self):
        """Test initialization with default tools."""
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}):
            tools = UnsplashTools()
            function_names = [func.name for func in tools.functions.values()]
            assert "search_photos" in function_names
            assert "get_photo" in function_names
            assert "get_random_photo" in function_names
            # download_photo is disabled by default
            assert "download_photo" not in function_names

    def test_init_with_all_tools(self):
        """Test initialization with all tools enabled."""
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}):
            tools = UnsplashTools(all=True)
            function_names = [func.name for func in tools.functions.values()]
            assert "search_photos" in function_names
            assert "get_photo" in function_names
            assert "get_random_photo" in function_names
            assert "download_photo" in function_names

    def test_init_with_selective_tools(self):
        """Test initialization with only selected tools."""
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}):
            tools = UnsplashTools(
                enable_search_photos=True,
                enable_get_photo=False,
                enable_get_random_photo=True,
                enable_download_photo=False,
            )
            function_names = [func.name for func in tools.functions.values()]
            assert "search_photos" in function_names
            assert "get_photo" not in function_names
            assert "get_random_photo" in function_names
            assert "download_photo" not in function_names


class TestSearchPhotos:
    """Tests for search_photos method."""

    def test_search_photos_success(self, unsplash_tools, mock_urlopen):
        """Test successful photo search."""
        mock_response_data = {
            "total": 100,
            "total_pages": 10,
            "results": [create_mock_photo()],
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = unsplash_tools.search_photos("sunset")
        result_data = json.loads(result)

        assert result_data["total"] == 100
        assert result_data["total_pages"] == 10
        assert len(result_data["photos"]) == 1
        assert result_data["photos"][0]["id"] == "abc123"
        assert result_data["photos"][0]["description"] == "A beautiful sunset"

    def test_search_photos_with_filters(self, unsplash_tools, mock_urlopen):
        """Test photo search with orientation and color filters."""
        mock_response_data = {
            "total": 50,
            "total_pages": 5,
            "results": [create_mock_photo()],
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = unsplash_tools.search_photos(
            "nature",
            per_page=5,
            orientation="landscape",
            color="green",
        )
        result_data = json.loads(result)

        assert result_data["total"] == 50
        assert len(result_data["photos"]) == 1

    def test_search_photos_without_api_key(self):
        """Test search_photos without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            old_key = os.environ.pop("UNSPLASH_ACCESS_KEY", None)
            try:
                tools = UnsplashTools()
                result = tools.search_photos("test")
                assert "Error: No Unsplash API key provided" in result
            finally:
                if old_key:
                    os.environ["UNSPLASH_ACCESS_KEY"] = old_key

    def test_search_photos_empty_query(self, unsplash_tools):
        """Test search_photos with empty query."""
        result = unsplash_tools.search_photos("")
        assert "Error: Please provide a search query" in result

    def test_search_photos_api_error(self, unsplash_tools, mock_urlopen):
        """Test search_photos with API error."""
        mock_urlopen.side_effect = Exception("API Connection Error")

        result = unsplash_tools.search_photos("sunset")
        assert "Error searching Unsplash: API Connection Error" in result

    def test_search_photos_invalid_orientation_ignored(self, unsplash_tools, mock_urlopen):
        """Test that invalid orientation is ignored."""
        mock_response_data = {
            "total": 10,
            "total_pages": 1,
            "results": [create_mock_photo()],
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        # Invalid orientation should be ignored
        result = unsplash_tools.search_photos("test", orientation="invalid")
        result_data = json.loads(result)
        assert result_data["total"] == 10

    def test_search_photos_per_page_bounds(self, unsplash_tools, mock_urlopen):
        """Test per_page parameter is bounded correctly."""
        mock_response_data = {
            "total": 10,
            "total_pages": 1,
            "results": [],
        }
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        # Test with value too high (should be capped at 30)
        unsplash_tools.search_photos("test", per_page=100)
        # Test with value too low (should be at least 1)
        unsplash_tools.search_photos("test", per_page=0)


class TestGetPhoto:
    """Tests for get_photo method."""

    def test_get_photo_success(self, unsplash_tools, mock_urlopen):
        """Test successful photo retrieval."""
        photo_data = create_mock_photo()
        photo_data["exif"] = {
            "make": "Canon",
            "model": "EOS 5D",
            "aperture": "f/2.8",
            "exposure_time": "1/500",
            "focal_length": "50mm",
            "iso": 400,
        }
        photo_data["location"] = {
            "name": "Yosemite Valley",
            "city": "Yosemite",
            "country": "USA",
        }
        photo_data["views"] = 10000
        photo_data["downloads"] = 500

        mock_urlopen.return_value = create_mock_response(photo_data)

        result = unsplash_tools.get_photo("abc123")
        result_data = json.loads(result)

        assert result_data["id"] == "abc123"
        assert result_data["exif"]["make"] == "Canon"
        assert result_data["location"]["country"] == "USA"
        assert result_data["views"] == 10000
        assert result_data["downloads"] == 500

    def test_get_photo_without_api_key(self):
        """Test get_photo without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            old_key = os.environ.pop("UNSPLASH_ACCESS_KEY", None)
            try:
                tools = UnsplashTools()
                result = tools.get_photo("abc123")
                assert "Error: No Unsplash API key provided" in result
            finally:
                if old_key:
                    os.environ["UNSPLASH_ACCESS_KEY"] = old_key

    def test_get_photo_empty_id(self, unsplash_tools):
        """Test get_photo with empty photo ID."""
        result = unsplash_tools.get_photo("")
        assert "Error: Please provide a photo ID" in result

    def test_get_photo_api_error(self, unsplash_tools, mock_urlopen):
        """Test get_photo with API error."""
        mock_urlopen.side_effect = Exception("Photo not found")

        result = unsplash_tools.get_photo("nonexistent")
        assert "Error getting photo: Photo not found" in result


class TestGetRandomPhoto:
    """Tests for get_random_photo method."""

    def test_get_random_photo_success_single(self, unsplash_tools, mock_urlopen):
        """Test successful single random photo retrieval."""
        # When count=1, API returns single object, not list
        mock_urlopen.return_value = create_mock_response([create_mock_photo()])

        result = unsplash_tools.get_random_photo()
        result_data = json.loads(result)

        assert "photos" in result_data
        assert len(result_data["photos"]) == 1
        assert result_data["photos"][0]["id"] == "abc123"

    def test_get_random_photo_success_multiple(self, unsplash_tools, mock_urlopen):
        """Test successful multiple random photos retrieval."""
        mock_photos = [
            create_mock_photo(photo_id="photo1"),
            create_mock_photo(photo_id="photo2"),
            create_mock_photo(photo_id="photo3"),
        ]
        mock_urlopen.return_value = create_mock_response(mock_photos)

        result = unsplash_tools.get_random_photo(count=3)
        result_data = json.loads(result)

        assert len(result_data["photos"]) == 3
        assert result_data["photos"][0]["id"] == "photo1"
        assert result_data["photos"][1]["id"] == "photo2"

    def test_get_random_photo_with_query(self, unsplash_tools, mock_urlopen):
        """Test random photo with query filter."""
        mock_urlopen.return_value = create_mock_response([create_mock_photo()])

        result = unsplash_tools.get_random_photo(query="nature")
        result_data = json.loads(result)

        assert len(result_data["photos"]) == 1

    def test_get_random_photo_with_orientation(self, unsplash_tools, mock_urlopen):
        """Test random photo with orientation filter."""
        mock_urlopen.return_value = create_mock_response([create_mock_photo()])

        result = unsplash_tools.get_random_photo(orientation="portrait")
        result_data = json.loads(result)

        assert len(result_data["photos"]) == 1

    def test_get_random_photo_without_api_key(self):
        """Test get_random_photo without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            old_key = os.environ.pop("UNSPLASH_ACCESS_KEY", None)
            try:
                tools = UnsplashTools()
                result = tools.get_random_photo()
                assert "Error: No Unsplash API key provided" in result
            finally:
                if old_key:
                    os.environ["UNSPLASH_ACCESS_KEY"] = old_key

    def test_get_random_photo_api_error(self, unsplash_tools, mock_urlopen):
        """Test get_random_photo with API error."""
        mock_urlopen.side_effect = Exception("API Error")

        result = unsplash_tools.get_random_photo()
        assert "Error getting random photo: API Error" in result

    def test_get_random_photo_count_bounds(self, unsplash_tools, mock_urlopen):
        """Test count parameter is bounded correctly."""
        mock_urlopen.return_value = create_mock_response([create_mock_photo()])

        # Test with value too high (should be capped at 30)
        unsplash_tools.get_random_photo(count=100)
        # Test with value too low (should be at least 1)
        unsplash_tools.get_random_photo(count=0)


class TestDownloadPhoto:
    """Tests for download_photo method."""

    def test_download_photo_success(self, unsplash_tools_all, mock_urlopen):
        """Test successful download tracking."""
        mock_response_data = {"url": "https://images.unsplash.com/photo-abc123?download=true"}
        mock_urlopen.return_value = create_mock_response(mock_response_data)

        result = unsplash_tools_all.download_photo("abc123")
        result_data = json.loads(result)

        assert result_data["photo_id"] == "abc123"
        assert "download" in result_data["download_url"]

    def test_download_photo_without_api_key(self):
        """Test download_photo without API key."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            old_key = os.environ.pop("UNSPLASH_ACCESS_KEY", None)
            try:
                tools = UnsplashTools(enable_download_photo=True)
                result = tools.download_photo("abc123")
                assert "Error: No Unsplash API key provided" in result
            finally:
                if old_key:
                    os.environ["UNSPLASH_ACCESS_KEY"] = old_key

    def test_download_photo_empty_id(self, unsplash_tools_all):
        """Test download_photo with empty photo ID."""
        result = unsplash_tools_all.download_photo("")
        assert "Error: Please provide a photo ID" in result

    def test_download_photo_api_error(self, unsplash_tools_all, mock_urlopen):
        """Test download_photo with API error."""
        mock_urlopen.side_effect = Exception("Download tracking failed")

        result = unsplash_tools_all.download_photo("abc123")
        assert "Error tracking download: Download tracking failed" in result


class TestFormatPhoto:
    """Tests for _format_photo helper method."""

    def test_format_photo_with_all_fields(self, unsplash_tools):
        """Test photo formatting with all fields present."""
        photo = create_mock_photo()
        result = unsplash_tools._format_photo(photo)

        assert result["id"] == "abc123"
        assert result["description"] == "A beautiful sunset"
        assert result["width"] == 4000
        assert result["height"] == 3000
        assert result["color"] == "#FF5733"
        assert "regular" in result["urls"]
        assert result["author"]["name"] == "John Photographer"
        assert result["likes"] == 150
        assert "sunset" in result["tags"]

    def test_format_photo_with_missing_description(self, unsplash_tools):
        """Test photo formatting falls back to alt_description."""
        photo = create_mock_photo()
        photo["description"] = None
        result = unsplash_tools._format_photo(photo)

        assert result["description"] == "Orange sky over mountains"

    def test_format_photo_with_empty_tags(self, unsplash_tools):
        """Test photo formatting with no tags."""
        photo = create_mock_photo()
        photo["tags"] = []
        result = unsplash_tools._format_photo(photo)

        assert result["tags"] == []

    def test_format_photo_limits_tags_to_five(self, unsplash_tools):
        """Test that only first 5 tags are included."""
        photo = create_mock_photo()
        photo["tags"] = [{"title": f"tag{i}"} for i in range(10)]
        result = unsplash_tools._format_photo(photo)

        assert len(result["tags"]) == 5


class TestMakeRequest:
    """Tests for _make_request helper method."""

    def test_make_request_with_params(self, unsplash_tools, mock_urlopen):
        """Test request includes query parameters."""
        mock_urlopen.return_value = create_mock_response({"test": "data"})

        unsplash_tools._make_request("/test", {"param1": "value1", "param2": "value2"})

        # Verify the URL was constructed correctly
        call_args = mock_urlopen.call_args[0][0]
        assert "/test?" in call_args.full_url
        assert "param1=value1" in call_args.full_url
        assert "param2=value2" in call_args.full_url

    def test_make_request_includes_auth_header(self, unsplash_tools, mock_urlopen):
        """Test request includes authorization header."""
        mock_urlopen.return_value = create_mock_response({"test": "data"})

        unsplash_tools._make_request("/test")

        call_args = mock_urlopen.call_args[0][0]
        assert call_args.headers["Authorization"] == "Client-ID test_key"
        assert call_args.headers["Accept-version"] == "v1"
