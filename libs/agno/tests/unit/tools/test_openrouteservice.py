"""Unit tests for OpenRouteServiceTools class."""

from unittest.mock import Mock, patch

import httpx
import pytest

from agno.tools.openrouteservice import OpenRouteServiceTools


@pytest.fixture
def ors_tools():
    """Create an OpenRouteServiceTools instance with a mock API key."""
    with patch.dict("os.environ", {"ORS_API_KEY": "test_api_key"}):
        return OpenRouteServiceTools()


def _mock_response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def _geocode_payload(label, lon, lat):
    return {"features": [{"geometry": {"coordinates": [lon, lat]}, "properties": {"label": label}}]}


def test_initialization_without_api_key():
    """Toolkit requires an API key."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="OpenRouteService API key is required"):
            OpenRouteServiceTools()


def test_init_with_selective_tools():
    """Only the enabled tools are registered."""
    with patch.dict("os.environ", {"ORS_API_KEY": "test_api_key"}):
        tools = OpenRouteServiceTools(
            enable_directions=True,
            enable_distance_matrix=False,
            enable_geocoding=False,
        )
        names = [func.name for func in tools.functions.values()]
        assert "get_directions" in names
        assert "get_distance_matrix" not in names
        assert "geocode_location" not in names


def test_geocode_location_success(ors_tools):
    """Geocoding returns latitude/longitude for a place name."""
    payload = _geocode_payload("Berlin, Germany", 13.407, 52.524)
    with patch("agno.tools.openrouteservice.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.return_value = _mock_response(payload)

        result = ors_tools.geocode_location("Berlin")

    assert result["latitude"] == 52.524
    assert result["longitude"] == 13.407
    assert result["label"] == "Berlin, Germany"


def test_geocode_location_empty_result(ors_tools):
    """Geocoding an unknown place returns an error."""
    with patch("agno.tools.openrouteservice.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.return_value = _mock_response({"features": []})

        result = ors_tools.geocode_location("NowhereLand")

    assert "error" in result
    assert "No location found" in result["error"]


def test_get_directions_success(ors_tools):
    """Directions geocode both endpoints then return distance and duration."""
    berlin = _mock_response(_geocode_payload("Berlin, Germany", 13.407, 52.524))
    amsterdam = _mock_response(_geocode_payload("Amsterdam, Netherlands", 4.892, 52.373))
    directions = _mock_response({"routes": [{"summary": {"distance": 649000.0, "duration": 23400.0}}]})

    with patch("agno.tools.openrouteservice.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.side_effect = [berlin, amsterdam]
        client_instance.post.return_value = directions

        result = ors_tools.get_directions("Berlin", "Amsterdam", profile="driving-car")

    assert result["start"] == "Berlin, Germany"
    assert result["end"] == "Amsterdam, Netherlands"
    assert result["profile"] == "driving-car"
    assert result["distance_km"] == 649.0
    assert result["duration_minutes"] == 390.0


def test_get_directions_invalid_profile(ors_tools):
    """An unsupported profile is rejected before any network call."""
    result = ors_tools.get_directions("Berlin", "Amsterdam", profile="transit")
    assert "error" in result
    assert "Invalid profile" in result["error"]


def test_get_directions_geocode_failure(ors_tools):
    """A failed geocode short-circuits with a clear error."""
    with patch("agno.tools.openrouteservice.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.return_value = _mock_response({"features": []})

        result = ors_tools.get_directions("Nowhere", "Amsterdam")

    assert "error" in result
    assert "start location" in result["error"]


def test_get_distance_matrix_success(ors_tools):
    """Distance matrix resolves all locations and returns matrices."""
    berlin = _mock_response(_geocode_payload("Berlin, Germany", 13.407, 52.524))
    amsterdam = _mock_response(_geocode_payload("Amsterdam, Netherlands", 4.892, 52.373))
    matrix = _mock_response({"distances": [[0, 649.0], [649.0, 0]], "durations": [[0, 23400.0], [23400.0, 0]]})

    with patch("agno.tools.openrouteservice.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.side_effect = [berlin, amsterdam]
        client_instance.post.return_value = matrix

        result = ors_tools.get_distance_matrix(["Berlin", "Amsterdam"])

    assert result["locations"] == ["Berlin, Germany", "Amsterdam, Netherlands"]
    assert result["distances_km"][0][1] == 649.0
    assert result["durations_seconds"][1][0] == 23400.0


def test_get_distance_matrix_requires_two_locations(ors_tools):
    """A matrix needs at least two locations."""
    result = ors_tools.get_distance_matrix(["Berlin"])
    assert "error" in result
    assert "at least two" in result["error"]


def test_http_error_handling(ors_tools):
    """HTTP status errors are mapped to friendly messages."""
    request = httpx.Request("GET", "https://api.openrouteservice.org/geocode/search")
    error_response = httpx.Response(status_code=429, request=request)

    def raise_error(*args, **kwargs):
        raise httpx.HTTPStatusError("rate limited", request=request, response=error_response)

    with patch("agno.tools.openrouteservice.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.side_effect = raise_error

        result = ors_tools.geocode_location("Berlin")

    assert "error" in result
    assert "rate limit" in result["error"].lower()


@pytest.mark.asyncio
async def test_aget_directions_success(ors_tools):
    """Async directions mirror the sync behaviour."""
    berlin = _mock_response(_geocode_payload("Berlin, Germany", 13.407, 52.524))
    amsterdam = _mock_response(_geocode_payload("Amsterdam, Netherlands", 4.892, 52.373))
    directions = _mock_response({"routes": [{"summary": {"distance": 649000.0, "duration": 23400.0}}]})

    async def async_get(*args, **kwargs):
        return async_get.responses.pop(0)

    async_get.responses = [berlin, amsterdam]

    async def async_post(*args, **kwargs):
        return directions

    with patch("agno.tools.openrouteservice.httpx.AsyncClient") as mock_client:
        client_instance = mock_client.return_value.__aenter__.return_value
        client_instance.get.side_effect = async_get
        client_instance.post.side_effect = async_post

        result = await ors_tools.aget_directions("Berlin", "Amsterdam", profile="cycling-regular")

    assert result["profile"] == "cycling-regular"
    assert result["distance_km"] == 649.0
