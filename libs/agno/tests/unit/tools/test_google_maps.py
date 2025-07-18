"""Unit tests for Google Maps tools."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

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

MOCK_PLACES_V1_RESPONSE = MagicMock()
MOCK_PLACES_V1_RESPONSE.places = [
    MagicMock(
        display_name=MagicMock(text="Test Business"),
        formatted_address="123 Test St, Test City",
        rating=4.5,
        reviews=[
            MagicMock(text=MagicMock(text="Great place!"), rating=5),
            MagicMock(text=MagicMock(text="Good service"), rating=4),
        ],
        id="test_place_id",
        international_phone_number="123-456-7890",
        website_uri="https://test.com",
        regular_opening_hours=MagicMock(
            weekday_descriptions=["Monday: 9:00 AM – 5:00 PM", "Tuesday: 9:00 AM – 5:00 PM"]
        ),
    )
]

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
        with patch("google.maps.places_v1.PlacesClient"):
            return GoogleMapTools()


@pytest.fixture
def mock_client():
    """Create a mock Google Maps client."""
    with patch("googlemaps.Client") as mock:
        yield mock


def test_search_places(google_maps_tools):
    """Test the search_places method."""
    with patch.object(google_maps_tools.places_client, "search_text") as mock_search_text:
        mock_search_text.return_value = MOCK_PLACES_V1_RESPONSE

        result = json.loads(google_maps_tools.search_places("test query"))

        assert len(result) == 1
        assert result[0]["name"] == "Test Business"
        assert result[0]["address"] == "123 Test St, Test City"
        assert result[0]["phone"] == "123-456-7890"
        assert result[0]["website"] == "https://test.com"
        assert result[0]["rating"] == 4.5
        assert len(result[0]["reviews"]) == 2
        assert result[0]["reviews"][0]["text"] == "Great place!"
        assert result[0]["reviews"][0]["rating"] == 5
        assert len(result[0]["hours"]) == 2
        assert result[0]["hours"][0] == "Monday: 9:00 AM – 5:00 PM"

        # Verify the request was made correctly
        mock_search_text.assert_called_once()
        request_arg = mock_search_text.call_args[1]["request"]
        assert request_arg.text_query == "test query"
        assert mock_search_text.call_args[1]["metadata"] == [("x-goog-fieldmask", "*")]


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


def test_search_places_success(google_maps_tools):
    """Test the search_places method with successful response."""
    with patch.object(google_maps_tools.places_client, "search_text") as mock_search_text:
        mock_search_text.return_value = MOCK_PLACES_V1_RESPONSE

        result = json.loads(google_maps_tools.search_places("test query"))

        assert len(result) == 1
        assert result[0]["name"] == "Test Business"
        assert result[0]["phone"] == "123-456-7890"
        assert result[0]["website"] == "https://test.com"

        # Verify the request was made correctly
        mock_search_text.assert_called_once()
        request_arg = mock_search_text.call_args[1]["request"]
        assert request_arg.text_query == "test query"


def test_search_places_no_results(google_maps_tools):
    """Test search_places when no results are returned."""
    with patch.object(google_maps_tools.places_client, "search_text") as mock_search_text:
        empty_response = MagicMock()
        empty_response.places = []
        mock_search_text.return_value = empty_response

        result = json.loads(google_maps_tools.search_places("test query"))
        assert result == []


def test_search_places_error(google_maps_tools):
    """Test search_places when an error occurs."""
    with patch.object(google_maps_tools.places_client, "search_text") as mock_search_text:
        mock_search_text.side_effect = Exception("API Error")

        result = json.loads(google_maps_tools.search_places("test query"))
        assert result == []
