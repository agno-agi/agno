"""Unit tests for Google Maps tools."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from agno.tools.google.maps import GoogleMapsTools

MOCK_DIRECTIONS_RESPONSE = [
    {
        "legs": [
            {
                "distance": {"text": "5 km", "value": 5000},
                "duration": {"text": "10 mins", "value": 600},
                "steps": [],
            }
        ]
    }
]

MOCK_ADDRESS_VALIDATION_RESPONSE = {
    "result": {
        "verdict": {"validationGranularity": "PREMISE", "hasInferredComponents": False},
        "address": {"formattedAddress": "123 Test St, Test City, ST 12345"},
    }
}

MOCK_GEOCODE_RESPONSE = [
    {
        "formatted_address": "123 Test St, Test City, ST 12345",
        "geometry": {"location": {"lat": 40.7128, "lng": -74.0060}},
    }
]

MOCK_DISTANCE_MATRIX_RESPONSE = {
    "rows": [
        {
            "elements": [
                {
                    "distance": {"text": "5 km", "value": 5000},
                    "duration": {"text": "10 mins", "value": 600},
                }
            ]
        }
    ]
}

MOCK_ELEVATION_RESPONSE = [{"elevation": 100.0}]

MOCK_TIMEZONE_RESPONSE = {
    "timeZoneId": "America/New_York",
    "timeZoneName": "Eastern Daylight Time",
}


@pytest.fixture
def google_maps_tools():
    """Create a GoogleMapsTools instance with a mock API key."""
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "AIzaTest"}):
        with patch("googlemaps.Client"):
            return GoogleMapsTools(all=True)


def test_get_directions(google_maps_tools):
    """Test the get_directions method."""
    with patch.object(google_maps_tools.client, "directions") as mock_directions:
        mock_directions.return_value = MOCK_DIRECTIONS_RESPONSE

        result = json.loads(google_maps_tools.get_directions(origin="Test Origin", destination="Test Destination"))

        assert isinstance(result, dict)
        assert "routes" in result
        assert isinstance(result["routes"], list)
        assert result["routes"][0]["legs"][0]["distance"]["value"] == 5000


def test_validate_address(google_maps_tools):
    """Test the validate_address method."""
    with patch.object(google_maps_tools.client, "addressvalidation") as mock_validate:
        mock_validate.return_value = MOCK_ADDRESS_VALIDATION_RESPONSE

        result = json.loads(google_maps_tools.validate_address("123 Test St"))

        assert isinstance(result, dict)
        assert "validation" in result
        assert "result" in result["validation"]
        assert "verdict" in result["validation"]["result"]


def test_geocode_address(google_maps_tools):
    """Test the geocode_address method."""
    with patch.object(google_maps_tools.client, "geocode") as mock_geocode:
        mock_geocode.return_value = MOCK_GEOCODE_RESPONSE

        result = json.loads(google_maps_tools.geocode_address("123 Test St"))

        assert isinstance(result, dict)
        assert "results" in result
        assert isinstance(result["results"], list)
        assert result["results"][0]["formatted_address"] == "123 Test St, Test City, ST 12345"


def test_reverse_geocode(google_maps_tools):
    """Test the reverse_geocode method."""
    with patch.object(google_maps_tools.client, "reverse_geocode") as mock_reverse:
        mock_reverse.return_value = MOCK_GEOCODE_RESPONSE

        result = json.loads(google_maps_tools.reverse_geocode(40.7128, -74.0060))

        assert isinstance(result, dict)
        assert "results" in result
        assert isinstance(result["results"], list)
        assert result["results"][0]["formatted_address"] == "123 Test St, Test City, ST 12345"


def test_get_distance_matrix(google_maps_tools):
    """Test the get_distance_matrix method."""
    with patch.object(google_maps_tools.client, "distance_matrix") as mock_matrix:
        mock_matrix.return_value = MOCK_DISTANCE_MATRIX_RESPONSE

        result = json.loads(google_maps_tools.get_distance_matrix(origins=["Origin"], destinations=["Destination"]))

        assert isinstance(result, dict)
        assert "matrix" in result
        assert "rows" in result["matrix"]
        assert result["matrix"]["rows"][0]["elements"][0]["distance"]["value"] == 5000


def test_get_elevation(google_maps_tools):
    """Test the get_elevation method."""
    with patch.object(google_maps_tools.client, "elevation") as mock_elevation:
        mock_elevation.return_value = MOCK_ELEVATION_RESPONSE

        result = json.loads(google_maps_tools.get_elevation(40.7128, -74.0060))

        assert isinstance(result, dict)
        assert "elevation" in result
        assert isinstance(result["elevation"], list)
        assert result["elevation"][0]["elevation"] == 100.0


def test_get_timezone(google_maps_tools):
    """Test the get_timezone method."""
    with patch.object(google_maps_tools.client, "timezone") as mock_timezone:
        mock_timezone.return_value = MOCK_TIMEZONE_RESPONSE
        test_time = datetime(2024, 1, 1, 12, 0)

        result = json.loads(google_maps_tools.get_timezone(40.7128, -74.0060, test_time))

        assert isinstance(result, dict)
        assert "timezone" in result
        assert result["timezone"]["timeZoneId"] == "America/New_York"


def test_error_handling(google_maps_tools):
    """Test error handling in various methods."""
    with patch.object(google_maps_tools.client, "directions") as mock_directions:
        mock_directions.side_effect = Exception("API Error")

        result = json.loads(google_maps_tools.get_directions("origin", "destination"))
        assert "error" in result
        assert result["error"] == "API Error"

    with patch.object(google_maps_tools.client, "geocode") as mock_geocode:
        mock_geocode.side_effect = Exception("Geocode Error")

        result = json.loads(google_maps_tools.geocode_address("123 Test St"))
        assert "error" in result
        assert result["error"] == "Geocode Error"


def test_initialization_without_api_key():
    """Test initialization without API key."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="GOOGLE_MAPS_API_KEY is not set"):
            GoogleMapsTools()


def test_default_tools_registered():
    """Test that default tools are registered correctly."""
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "AIzaTest"}):
        with patch("googlemaps.Client"):
            tools = GoogleMapsTools()
            # Default: get_directions, geocode_address, reverse_geocode
            assert len(tools.functions) == 3
            assert "get_directions" in tools.functions
            assert "geocode_address" in tools.functions
            assert "reverse_geocode" in tools.functions


def test_all_tools_registered():
    """Test that all tools are registered when all=True."""
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "AIzaTest"}):
        with patch("googlemaps.Client"):
            tools = GoogleMapsTools(all=True)
            # All tools: get_directions, validate_address, geocode_address,
            # reverse_geocode, get_distance_matrix, get_elevation, get_timezone
            assert len(tools.functions) == 7
            assert "get_directions" in tools.functions
            assert "validate_address" in tools.functions
            assert "geocode_address" in tools.functions
            assert "reverse_geocode" in tools.functions
            assert "get_distance_matrix" in tools.functions
            assert "get_elevation" in tools.functions
            assert "get_timezone" in tools.functions
