"""Unit tests for Google Maps tools."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from agno.tools.google_maps import GoogleMapTools

# Mock responses
MOCK_PLACES_RESPONSE = {
    "results": [
        {
            "name": "Test Business",
            "formatted_address": "123 Test St, Test City",
            "rating": 4.5,
            "user_ratings_total": 100,
            "place_id": "test_place_id",
        }
    ]
}

MOCK_PLACE_DETAILS = {
    "result": {
        "formatted_phone_number": "123-456-7890",
        "website": "https://test.com",
        "opening_hours": {"weekday_text": ["Monday: 9:00 AM – 5:00 PM"]},
    }
}

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
    """Create a GoogleMapTools instance with a mock API key."""
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "AIzaTest"}):
        return GoogleMapTools()


@pytest.fixture
def mock_client():
    """Create a mock Google Maps client."""
    with patch("googlemaps.Client") as mock:
        yield mock


def test_search_places(google_maps_tools):
    """Test the search_places method."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        with patch.object(google_maps_tools.client, "place") as mock_place:
            mock_places.return_value = MOCK_PLACES_RESPONSE
            mock_place.return_value = MOCK_PLACE_DETAILS

            result = json.loads(google_maps_tools.search_places("test query"))

            assert len(result) == 1
            assert result[0]["name"] == "Test Business"
            assert result[0]["phone"] == "123-456-7890"
            assert result[0]["website"] == "https://test.com"


def test_get_directions(google_maps_tools):
    """Test the get_directions method."""
    with patch.object(google_maps_tools.client, "directions") as mock_directions:
        mock_directions.return_value = MOCK_DIRECTIONS_RESPONSE

        result = eval(google_maps_tools.get_directions(origin="Test Origin", destination="Test Destination"))

        assert isinstance(result, list)
        assert "legs" in result[0]
        assert result[0]["legs"][0]["distance"]["value"] == 5000


def test_validate_address(google_maps_tools):
    """Test the validate_address method."""
    with patch.object(google_maps_tools.client, "addressvalidation") as mock_validate:
        mock_validate.return_value = MOCK_ADDRESS_VALIDATION_RESPONSE

        result = eval(google_maps_tools.validate_address("123 Test St"))

        assert isinstance(result, dict)
        assert "result" in result
        assert "verdict" in result["result"]


def test_geocode_address(google_maps_tools):
    """Test the geocode_address method."""
    with patch.object(google_maps_tools.client, "geocode") as mock_geocode:
        mock_geocode.return_value = MOCK_GEOCODE_RESPONSE

        result = eval(google_maps_tools.geocode_address("123 Test St"))

        assert isinstance(result, list)
        assert result[0]["formatted_address"] == "123 Test St, Test City, ST 12345"


def test_reverse_geocode(google_maps_tools):
    """Test the reverse_geocode method."""
    with patch.object(google_maps_tools.client, "reverse_geocode") as mock_reverse:
        mock_reverse.return_value = MOCK_GEOCODE_RESPONSE

        result = eval(google_maps_tools.reverse_geocode(40.7128, -74.0060))

        assert isinstance(result, list)
        assert result[0]["formatted_address"] == "123 Test St, Test City, ST 12345"


def test_get_distance_matrix(google_maps_tools):
    """Test the get_distance_matrix method."""
    with patch.object(google_maps_tools.client, "distance_matrix") as mock_matrix:
        mock_matrix.return_value = MOCK_DISTANCE_MATRIX_RESPONSE

        result = eval(google_maps_tools.get_distance_matrix(origins=["Origin"], destinations=["Destination"]))

        assert isinstance(result, dict)
        assert "rows" in result
        assert result["rows"][0]["elements"][0]["distance"]["value"] == 5000


def test_get_elevation(google_maps_tools):
    """Test the get_elevation method."""
    with patch.object(google_maps_tools.client, "elevation") as mock_elevation:
        mock_elevation.return_value = MOCK_ELEVATION_RESPONSE

        result = eval(google_maps_tools.get_elevation(40.7128, -74.0060))

        assert isinstance(result, list)
        assert result[0]["elevation"] == 100.0


def test_get_timezone(google_maps_tools):
    """Test the get_timezone method."""
    with patch.object(google_maps_tools.client, "timezone") as mock_timezone:
        mock_timezone.return_value = MOCK_TIMEZONE_RESPONSE
        test_time = datetime(2024, 1, 1, 12, 0)

        result = eval(google_maps_tools.get_timezone(40.7128, -74.0060, test_time))

        assert isinstance(result, dict)
        assert result["timeZoneId"] == "America/New_York"


def test_error_handling(google_maps_tools):
    """Test error handling in various methods."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        mock_places.side_effect = Exception("API Error")

        result = google_maps_tools.search_places("test query")
        assert result == "[]"

    with patch.object(google_maps_tools.client, "directions") as mock_directions:
        mock_directions.side_effect = Exception("API Error")

        result = google_maps_tools.get_directions("origin", "destination")
        assert result == "[]"


def test_initialization_without_api_key():
    """Test initialization without API key."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="GOOGLE_MAPS_API_KEY is not set"):
            GoogleMapTools()


def test_initialization_with_selective_tools():
    """Test initialization with only selected tools."""
    with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "AIzaTest"}):
        tools = GoogleMapTools(
            search_places=True,
            get_directions=False,
            validate_address=False,
            geocode_address=True,
            reverse_geocode=False,
            get_distance_matrix=False,
            get_elevation=False,
            get_timezone=False,
        )

        assert "search_places" in [func.name for func in tools.functions.values()]
        assert "get_directions" not in [func.name for func in tools.functions.values()]
        assert "geocode_address" in [func.name for func in tools.functions.values()]


def test_search_places_success(google_maps_tools):
    """Test the search_places method with successful response."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        with patch.object(google_maps_tools.client, "place") as mock_place:
            mock_places.return_value = MOCK_PLACES_RESPONSE
            mock_place.return_value = MOCK_PLACE_DETAILS

            result = json.loads(google_maps_tools.search_places("test query"))

            assert len(result) == 1
            assert result[0]["name"] == "Test Business"
            assert result[0]["phone"] == "123-456-7890"
            assert result[0]["website"] == "https://test.com"
            mock_places.assert_called_once_with("test query")
            mock_place.assert_called_once_with("test_place_id")


def test_search_places_no_results(google_maps_tools):
    """Test search_places when no results are returned."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        mock_places.return_value = {"results": []}
        result = json.loads(google_maps_tools.search_places("test query"))
        assert result == []


def test_search_places_none_response(google_maps_tools):
    """Test search_places when None is returned."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        mock_places.return_value = None
        result = json.loads(google_maps_tools.search_places("test query"))
        assert result == []


def test_search_places_missing_results_key(google_maps_tools):
    """Test search_places when response is missing results key."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        mock_places.return_value = {"status": "OK"}
        result = json.loads(google_maps_tools.search_places("test query"))
        assert result == []


def test_search_places_missing_place_id(google_maps_tools):
    """Test search_places when place_id is missing."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        mock_places.return_value = {
            "results": [
                {
                    "name": "Test Business",
                    "formatted_address": "123 Test St",
                    "rating": 4.5,
                }
            ]
        }
        result = json.loads(google_maps_tools.search_places("test query"))
        assert len(result) == 1
        assert result[0]["name"] == "Test Business"
        assert "phone" not in result[0]
        assert "website" not in result[0]


def test_search_places_invalid_details(google_maps_tools):
    """Test search_places when place details are invalid."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        with patch.object(google_maps_tools.client, "place") as mock_place:
            mock_places.return_value = MOCK_PLACES_RESPONSE
            mock_place.return_value = {"status": "NOT_FOUND"}  # Missing 'result' key

            result = json.loads(google_maps_tools.search_places("test query"))

            assert len(result) == 1
            assert result[0]["name"] == "Test Business"
            assert "phone" not in result[0]
            assert "website" not in result[0]


def test_search_places_details_error(google_maps_tools):
    """Test search_places when place details call raises an error."""
    with patch.object(google_maps_tools.client, "places") as mock_places:
        with patch.object(google_maps_tools.client, "place") as mock_place:
            mock_places.return_value = MOCK_PLACES_RESPONSE
            mock_place.side_effect = Exception("API Error")

            result = json.loads(google_maps_tools.search_places("test query"))

            assert len(result) == 1
            assert result[0]["name"] == "Test Business"
            assert "phone" not in result[0]
            assert "website" not in result[0]
