"""Unit tests for OpenWeatherTools class."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.openweather import OpenWeatherTools


@pytest.fixture
def mock_openweather_api():
    """Create a mock OpenWeatherMap API client."""
    with patch("agno.tools.openweather.requests.get") as mock_get:
        yield mock_get


@pytest.fixture
def openweather_tools():
    """Create an OpenWeatherTools instance with a mock API key."""
    with patch.dict("os.environ", {"OPENWEATHER_API_KEY": "test_api_key"}):
        return OpenWeatherTools()


def test_initialization_without_api_key():
    """Test initialization without API key."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="OpenWeather API key is required"):
            OpenWeatherTools()


def test_init_with_selective_tools():
    """Test initialization with only selected tools."""
    with patch.dict("os.environ", {"OPENWEATHER_API_KEY": "test_api_key"}):
        tools = OpenWeatherTools(
            current_weather=True,
            forecast=False,
            air_pollution=True,
            geocoding=False,
        )

        assert "get_current_weather" in [func.name for func in tools.functions.values()]
        assert "get_forecast" not in [func.name for func in tools.functions.values()]
        assert "get_air_pollution" in [func.name for func in tools.functions.values()]
        assert "geocode_location" not in [func.name for func in tools.functions.values()]


def test_get_current_weather_success(openweather_tools, mock_openweather_api):
    """Test successful current weather retrieval."""
    # First mock the geocode response
    geocode_response = Mock()
    geocode_response.status_code = 200
    geocode_response.json.return_value = [{"name": "New York", "lat": 40.7128, "lon": -74.0060, "country": "US"}]

    # Then mock the weather response
    weather_response = Mock()
    weather_response.status_code = 200
    weather_response.json.return_value = {
        "name": "New York",
        "main": {
            "temp": 20.5,
            "feels_like": 19.8,
            "temp_min": 18.9,
            "temp_max": 22.1,
            "pressure": 1015,
            "humidity": 65,
        },
        "weather": [{"id": 800, "main": "Clear", "description": "clear sky", "icon": "01d"}],
        "wind": {"speed": 3.6, "deg": 160},
        "sys": {"country": "US"},
        "coord": {"lat": 40.7128, "lon": -74.0060},
    }

    # Set up the mock to return different responses for different calls
    mock_openweather_api.side_effect = [geocode_response, weather_response]

    result = openweather_tools.get_current_weather("New York")
    result_data = json.loads(result)

    assert result_data["name"] == "New York"
    assert result_data["main"]["temp"] == 20.5
    assert result_data["weather"][0]["main"] == "Clear"
    assert result_data["location_name"] == "New York"


def test_get_forecast_success(openweather_tools, mock_openweather_api):
    """Test successful weather forecast retrieval."""
    # First mock the geocode response
    geocode_response = Mock()
    geocode_response.status_code = 200
    geocode_response.json.return_value = [{"name": "New York", "lat": 40.7128, "lon": -74.0060, "country": "US"}]

    # Then mock the forecast response
    forecast_response = Mock()
    forecast_response.status_code = 200
    forecast_response.json.return_value = {
        "city": {"name": "New York", "country": "US"},
        "list": [
            {
                "dt": 1625097600,
                "main": {
                    "temp": 22.5,
                    "feels_like": 21.8,
                    "temp_min": 20.9,
                    "temp_max": 24.1,
                    "pressure": 1015,
                    "humidity": 60,
                },
                "weather": [{"main": "Clouds", "description": "scattered clouds", "icon": "03d"}],
                "wind": {"speed": 4.1, "deg": 180},
                "dt_txt": "2023-07-01 12:00:00",
            },
            {
                "dt": 1625108400,
                "main": {
                    "temp": 24.5,
                    "feels_like": 23.8,
                    "temp_min": 22.9,
                    "temp_max": 26.1,
                    "pressure": 1014,
                    "humidity": 55,
                },
                "weather": [{"main": "Clear", "description": "clear sky", "icon": "01d"}],
                "wind": {"speed": 3.6, "deg": 190},
                "dt_txt": "2023-07-01 15:00:00",
            },
        ],
    }

    # Set up the mock to return different responses for different calls
    mock_openweather_api.side_effect = [geocode_response, forecast_response]

    result = openweather_tools.get_forecast("New York", days=2)
    result_data = json.loads(result)

    assert result_data["city"]["name"] == "New York"
    assert len(result_data["list"]) == 2
    assert result_data["list"][0]["weather"][0]["main"] == "Clouds"
    assert result_data["list"][1]["weather"][0]["main"] == "Clear"
    assert result_data["location_name"] == "New York"


def test_get_air_pollution_success(openweather_tools, mock_openweather_api):
    """Test successful air pollution data retrieval."""
    # First mock the geocode response
    geocode_response = Mock()
    geocode_response.status_code = 200
    geocode_response.json.return_value = [{"name": "New York", "lat": 40.7128, "lon": -74.0060, "country": "US"}]

    # Then mock the air pollution response
    pollution_response = Mock()
    pollution_response.status_code = 200
    pollution_response.json.return_value = {
        "coord": {"lat": 40.7128, "lon": -74.0060},
        "list": [
            {
                "main": {"aqi": 2},
                "components": {
                    "co": 400.5,
                    "no": 10.2,
                    "no2": 25.6,
                    "o3": 60.8,
                    "so2": 8.5,
                    "pm2_5": 12.3,
                    "pm10": 24.7,
                    "nh3": 5.2,
                },
                "dt": 1625097600,
            }
        ],
    }

    # Set up the mock to return different responses for different calls
    mock_openweather_api.side_effect = [geocode_response, pollution_response]

    result = openweather_tools.get_air_pollution("New York")
    result_data = json.loads(result)

    assert result_data["coord"]["lat"] == 40.7128
    assert result_data["coord"]["lon"] == -74.0060
    assert result_data["list"][0]["main"]["aqi"] == 2
    assert result_data["list"][0]["components"]["pm2_5"] == 12.3
    assert result_data["location_name"] == "New York"


def test_error_handling(openweather_tools, mock_openweather_api):
    """Test error handling in various methods."""
    # Test API error
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"message": "City not found"}
    mock_openweather_api.return_value = mock_response

    result = openweather_tools.geocode_location("NonexistentCity")
    result_data = json.loads(result)

    assert "message" in result_data
    assert "City not found" in result_data["message"]

    # Test exception
    mock_openweather_api.side_effect = Exception("Connection error")
    result = openweather_tools.geocode_location("New York")
    result_data = json.loads(result)
    assert "error" in result_data
    assert "Connection error" in result_data["error"]


def test_geocode_location_empty_result(openweather_tools, mock_openweather_api):
    """Test geocode location with empty result."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = []  # Empty result
    mock_openweather_api.return_value = mock_response

    result = openweather_tools.geocode_location("NonexistentCity")
    result_data = json.loads(result)
    assert "error" in result_data
    assert "No location found" in result_data["error"]


def test_get_current_weather_with_geocode_error(openweather_tools, mock_openweather_api):
    """Test current weather with geocode error."""
    # Mock geocode error
    mock_response = Mock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"message": "City not found"}
    mock_openweather_api.return_value = mock_response

    result = openweather_tools.get_current_weather("NonexistentCity")
    result_data = json.loads(result)
    assert "error" in result_data


def test_units_parameter(openweather_tools, mock_openweather_api):
    """Test units parameter is passed correctly."""
    # First mock the geocode response
    geocode_response = Mock()
    geocode_response.status_code = 200
    geocode_response.json.return_value = [{"name": "London", "lat": 51.5074, "lon": -0.1278, "country": "GB"}]

    # Then mock the weather response
    weather_response = Mock()
    weather_response.status_code = 200
    weather_response.json.return_value = {"name": "London", "main": {"temp": 15.5}, "weather": [{"main": "Rain"}]}

    # Set up the mock to return different responses for different calls
    mock_openweather_api.side_effect = [geocode_response, weather_response]

    # Create a tool with imperial units
    with patch.dict("os.environ", {"OPENWEATHER_API_KEY": "test_api_key"}):
        imperial_tools = OpenWeatherTools(units="imperial")

    # Reset the mock
    mock_openweather_api.reset_mock()
    mock_openweather_api.side_effect = [geocode_response, weather_response]

    # Call the method
    imperial_tools.get_current_weather("London")

    # Check that the units parameter was passed correctly
    calls = mock_openweather_api.call_args_list
    assert len(calls) == 2  # Two calls: geocode and weather
    weather_call = calls[1]
    assert weather_call[1]["params"]["units"] == "imperial"
