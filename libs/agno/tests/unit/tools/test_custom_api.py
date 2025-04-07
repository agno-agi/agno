"""Unit tests for CustomApiTools class."""

import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.tools.api import CustomApiTools


@pytest.fixture
def api_tools():
    """Create a CustomApiTools instance with test configuration."""
    return CustomApiTools(
        base_url="https://dog.ceo/api",
        username="test_user",
        password="test_pass",
        api_key="test_key",
        headers={"X-Custom-Header": "test_value"},
        verify_ssl=True,
        timeout=10,
    )


@pytest.fixture
def mock_dog_image_response():
    """Create a mock response for dog image API."""
    mock = Mock(spec=requests.Response)
    mock.status_code = 200
    mock.ok = True
    mock.text = '{"status": "success", "message": "https://images.dog.ceo/breeds/hound-afghan/n02088094_1003.jpg"}'
    mock.json.return_value = {
        "status": "success",
        "message": "https://images.dog.ceo/breeds/hound-afghan/n02088094_1003.jpg",
    }
    mock.headers = {"Content-Type": "application/json"}
    return mock


@pytest.fixture
def mock_dog_breeds_response():
    """Create a mock response for dog breeds API."""
    mock = Mock(spec=requests.Response)
    mock.status_code = 200
    mock.ok = True
    mock.text = (
        '{"status": "success", "message": {"affenpinscher": [], "african": [], "terrier": ["american", "australian"]}}'
    )
    mock.json.return_value = {
        "status": "success",
        "message": {"affenpinscher": [], "african": [], "terrier": ["american", "australian"]},
    }
    mock.headers = {"Content-Type": "application/json"}
    return mock


def test_init_with_default_values():
    """Test initialization with default values."""
    tools = CustomApiTools()
    assert tools.base_url is None
    assert tools.username is None
    assert tools.password is None
    assert tools.api_key is None
    assert tools.default_headers == {}
    assert tools.verify_ssl is True
    assert tools.timeout == 30


def test_init_with_custom_values():
    """Test initialization with custom values."""
    tools = CustomApiTools(
        base_url="https://dog.ceo/api",
        username="custom_user",
        password="custom_pass",
        api_key="custom_key",
        headers={"X-Custom-Header": "custom_value"},
        verify_ssl=False,
        timeout=60,
        make_request=False,
    )

    assert tools.base_url == "https://dog.ceo/api"
    assert tools.username == "custom_user"
    assert tools.password == "custom_pass"
    assert tools.api_key == "custom_key"
    assert tools.default_headers == {"X-Custom-Header": "custom_value"}
    assert tools.verify_ssl is False
    assert tools.timeout == 60


def test_get_auth(api_tools):
    """Test _get_auth method."""
    auth = api_tools._get_auth()
    assert isinstance(auth, requests.auth.HTTPBasicAuth)
    assert auth.username == "test_user"
    assert auth.password == "test_pass"


def test_get_auth_no_credentials():
    """Test _get_auth method with no credentials."""
    tools = CustomApiTools()
    auth = tools._get_auth()
    assert auth is None


def test_get_headers(api_tools):
    """Test _get_headers method."""
    headers = api_tools._get_headers()
    assert headers["X-Custom-Header"] == "test_value"
    assert headers["Authorization"] == "Bearer test_key"


def test_get_headers_with_additional_headers(api_tools):
    """Test _get_headers method with additional headers."""
    headers = api_tools._get_headers({"X-Additional": "additional_value"})
    assert headers["X-Custom-Header"] == "test_value"
    assert headers["Authorization"] == "Bearer test_key"
    assert headers["X-Additional"] == "additional_value"


def test_get_headers_no_api_key():
    """Test _get_headers method with no API key."""
    tools = CustomApiTools(headers={"X-Custom-Header": "test_value"})
    headers = tools._get_headers()
    assert headers["X-Custom-Header"] == "test_value"
    assert "Authorization" not in headers


def test_make_request_dog_image(api_tools, mock_dog_image_response):
    """Test successful GET request to dog image API."""
    with patch("requests.request", return_value=mock_dog_image_response) as mock_request:
        result = api_tools.make_request(
            endpoint="/breeds/image/random",
            method="GET",
        )

        result_data = json.loads(result)
        assert result_data["status_code"] == 200
        assert "https://images.dog.ceo/breeds" in result_data["data"]["message"]

        mock_request.assert_called_once_with(
            method="GET",
            url="https://dog.ceo/api/breeds/image/random",
            params=None,
            data=None,
            json=None,
            headers=api_tools._get_headers(),
            auth=api_tools._get_auth(),
            verify=True,
            timeout=10,
        )


def test_make_request_dog_breeds(api_tools, mock_dog_breeds_response):
    """Test successful GET request to dog breeds API."""
    with patch("requests.request", return_value=mock_dog_breeds_response) as mock_request:
        result = api_tools.make_request(
            endpoint="/breeds/list/all",
            method="GET",
        )

        result_data = json.loads(result)
        assert result_data["status_code"] == 200
        assert "affenpinscher" in result_data["data"]["message"]
        assert "terrier" in result_data["data"]["message"]

        mock_request.assert_called_once_with(
            method="GET",
            url="https://dog.ceo/api/breeds/list/all",
            params=None,
            data=None,
            json=None,
            headers=api_tools._get_headers(),
            auth=api_tools._get_auth(),
            verify=True,
            timeout=10,
        )


def test_make_request_with_params(api_tools, mock_dog_image_response):
    """Test request with query parameters."""
    with patch("requests.request", return_value=mock_dog_image_response) as mock_request:
        result = api_tools.make_request(
            endpoint="/breeds/image/random",
            method="GET",
            params={"count": 3},
        )

        result_data = json.loads(result)
        assert result_data["status_code"] == 200

        mock_request.assert_called_once_with(
            method="GET",
            url="https://dog.ceo/api/breeds/image/random",
            params={"count": 3},
            data=None,
            json=None,
            headers=api_tools._get_headers(),
            auth=api_tools._get_auth(),
            verify=True,
            timeout=10,
        )


def test_make_request_without_base_url(mock_dog_image_response):
    """Test request without base URL."""
    tools = CustomApiTools()
    with patch("requests.request", return_value=mock_dog_image_response) as mock_request:
        result = tools.make_request(
            endpoint="https://dog.ceo/api/breeds/image/random",
            method="GET",
        )

        result_data = json.loads(result)
        assert result_data["status_code"] == 200

        mock_request.assert_called_once_with(
            method="GET",
            url="https://dog.ceo/api/breeds/image/random",
            params=None,
            data=None,
            json=None,
            headers=tools._get_headers(),
            auth=None,
            verify=True,
            timeout=30,
        )


def test_make_request_error_response(api_tools):
    """Test request with error response."""
    mock_error_response = Mock(spec=requests.Response)
    mock_error_response.status_code = 404
    mock_error_response.ok = False
    mock_error_response.text = '{"status": "error", "message": "Breed not found"}'
    mock_error_response.json.return_value = {"status": "error", "message": "Breed not found"}
    mock_error_response.headers = {"Content-Type": "application/json"}

    with patch("requests.request", return_value=mock_error_response):
        result = api_tools.make_request(
            endpoint="/breed/unknown/images",
            method="GET",
        )

        result_data = json.loads(result)
        assert result_data["status_code"] == 404
        assert result_data["error"] == "Request failed"
        assert result_data["data"]["status"] == "error"


def test_make_request_json_decode_error(api_tools):
    """Test request with JSON decode error."""
    mock_invalid_json = Mock(spec=requests.Response)
    mock_invalid_json.status_code = 200
    mock_invalid_json.ok = True
    mock_invalid_json.text = "Not a JSON response"
    mock_invalid_json.json.side_effect = json.JSONDecodeError("Invalid JSON", "Not a JSON response", 0)
    mock_invalid_json.headers = {"Content-Type": "text/plain"}

    with patch("requests.request", return_value=mock_invalid_json):
        result = api_tools.make_request(
            endpoint="/breeds/image/random",
            method="GET",
        )

        result_data = json.loads(result)
        assert result_data["status_code"] == 200
        assert result_data["data"]["text"] == "Not a JSON response"


def test_make_request_network_error(api_tools):
    """Test request with network error."""
    with patch("requests.request", side_effect=requests.exceptions.RequestException("Connection error")):
        result = api_tools.make_request(
            endpoint="/breeds/image/random",
            method="GET",
        )

        result_data = json.loads(result)
        assert "error" in result_data
        assert "Connection error" in result_data["error"]


def test_make_request_general_exception(api_tools):
    """Test request with general exception."""
    with patch("requests.request", side_effect=Exception("Unexpected error")):
        result = api_tools.make_request(
            endpoint="/breeds/image/random",
            method="GET",
        )

        result_data = json.loads(result)
        assert "error" in result_data
        assert "Unexpected error" in result_data["error"]


def test_make_request_all_http_methods(api_tools, mock_dog_image_response):
    """Test all HTTP methods."""
    http_methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]

    with patch("requests.request", return_value=mock_dog_image_response) as mock_request:
        for method in http_methods:
            result = api_tools.make_request(
                endpoint="/breeds/image/random",
                method=method,
            )

            result_data = json.loads(result)
            assert result_data["status_code"] == 200

            mock_request.assert_called_with(
                method=method,
                url="https://dog.ceo/api/breeds/image/random",
                params=None,
                data=None,
                json=None,
                headers=api_tools._get_headers(),
                auth=api_tools._get_auth(),
                verify=True,
                timeout=10,
            )
