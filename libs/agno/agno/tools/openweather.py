import json
from os import getenv
from typing import Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")


class OpenWeatherTools(Toolkit):
    # Agno 2.x kwarg names accepted for backwards compatibility
    _legacy_param_aliases = {
        "enable_current_weather": "get_current_weather",
        "enable_forecast": "get_forecast",
        "enable_air_pollution": "get_air_pollution",
        "enable_geocoding": "geocode_location",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        units: str = "metric",
        get_current_weather: bool = True,
        get_forecast: bool = True,
        get_air_pollution: bool = True,
        geocode_location: bool = True,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        """
        OpenWeather toolkit for accessing weather data from OpenWeatherMap API.

        Args:
            api_key: OpenWeatherMap API key. Falls back to OPENWEATHER_API_KEY env var.
            units: Units of measurement - 'standard', 'metric', or 'imperial'.
            get_current_weather: Register the get_current_weather tool.
            get_forecast: Register the get_forecast tool.
            get_air_pollution: Register the get_air_pollution tool.
            geocode_location: Register the geocode_location tool.
            all: Register all tools regardless of individual flags.
            timeout: Per-request HTTP timeout in seconds.
        """
        self.api_key = api_key or getenv("OPENWEATHER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenWeather API key is required. Provide it as an argument or set the OPENWEATHER_API_KEY environment variable."
            )

        self.units = units
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self.geo_url = "https://api.openweathermap.org/geo/1.0"

        tools: List[Callable] = []
        if all or get_current_weather:
            tools.append(self.get_current_weather)
        if all or get_forecast:
            tools.append(self.get_forecast)
        if all or get_air_pollution:
            tools.append(self.get_air_pollution)
        if all or geocode_location:
            tools.append(self.geocode_location)

        super().__init__(name="openweather_tools", tools=tools, timeout=timeout, **kwargs)

    def _make_request(self, url: str, params: Dict) -> Dict:
        """Make a request to the OpenWeatherMap API.

        Args:
            url: The API endpoint URL.
            params: Query parameters for the request.

        Returns:
            The JSON response from the API.
        """
        try:
            params["appid"] = self.api_key
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.exception(f"Error making request to {url}")
            return {"error": str(e)}

    def geocode_location(self, location: str, limit: int = 1) -> str:
        """Convert a location name to geographic coordinates.

        Args:
            location: The name of the city, e.g., "London", "Paris", "New York".
            limit: Maximum number of location results.

        Returns:
            JSON string containing location data with coordinates.
        """
        try:
            log_info(f"Geocoding location: {location}")
            url = f"{self.geo_url}/direct"
            params = {"q": location, "limit": limit}

            result = self._make_request(url, params)

            if "error" in result:
                return json.dumps(result)

            if not result:
                return json.dumps({"error": f"No location found for '{location}'"})

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error geocoding location")
            return json.dumps({"error": str(e)})

    def get_current_weather(self, location: str) -> str:
        """Get current weather data for a location.

        Args:
            location: The name of the city, e.g., "London", "Paris", "New York".

        Returns:
            JSON string containing current weather data including temperature,
            humidity, wind, and conditions.
        """
        try:
            log_info(f"Getting current weather for: {location}")

            # First geocode the location to get coordinates
            geocode_result = json.loads(self.geocode_location(location))
            if "error" in geocode_result:
                return json.dumps(geocode_result)

            if not geocode_result:
                return json.dumps({"error": f"No location found for '{location}'"})

            # Get the first location result
            loc_data = geocode_result[0]
            lat, lon = loc_data["lat"], loc_data["lon"]

            # Get current weather using coordinates
            url = f"{self.base_url}/weather"
            params = {"lat": lat, "lon": lon, "units": self.units}

            result = self._make_request(url, params)

            # Add the location name to the result
            if "error" not in result:
                result["location_name"] = loc_data.get("name", location)
                result["country"] = loc_data.get("country", "")

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error getting current weather")
            return json.dumps({"error": str(e)})

    def get_forecast(self, location: str, days: int = 5) -> str:
        """Get weather forecast for a location.

        Args:
            location: The name of the city, e.g., "London", "Paris", "New York".
            days: Number of days for forecast (max 5).

        Returns:
            JSON string containing forecast data with 3-hour intervals.
        """
        try:
            log_info(f"Getting {days}-day forecast for: {location}")

            # First geocode the location to get coordinates
            geocode_result = json.loads(self.geocode_location(location))
            if "error" in geocode_result:
                return json.dumps(geocode_result)

            if not geocode_result:
                return json.dumps({"error": f"No location found for '{location}'"})

            # Get the first location result
            loc_data = geocode_result[0]
            lat, lon = loc_data["lat"], loc_data["lon"]

            # Get forecast using coordinates
            url = f"{self.base_url}/forecast"
            params = {
                "lat": lat,
                "lon": lon,
                "units": self.units,
                # Each day has 8 3-hour forecasts, max 5 days (40 entries)
                "cnt": min(days * 8, 40),
            }

            result = self._make_request(url, params)

            # Add the location name to the result
            if "error" not in result:
                result["location_name"] = loc_data.get("name", location)
                result["country"] = loc_data.get("country", "")

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error getting forecast")
            return json.dumps({"error": str(e)})

    def get_air_pollution(self, location: str) -> str:
        """Get current air pollution data for a location.

        Args:
            location: The name of the city, e.g., "London", "Paris", "New York".

        Returns:
            JSON string containing air quality index and pollutant concentrations.
        """
        try:
            log_info(f"Getting air pollution data for: {location}")

            # First geocode the location to get coordinates
            geocode_result = json.loads(self.geocode_location(location))
            if "error" in geocode_result:
                return json.dumps(geocode_result)

            if not geocode_result:
                return json.dumps({"error": f"No location found for '{location}'"})

            # Get the first location result
            loc_data = geocode_result[0]
            lat, lon = loc_data["lat"], loc_data["lon"]

            # Get air pollution data using coordinates
            url = f"{self.base_url}/air_pollution"
            params = {"lat": lat, "lon": lon}

            result = self._make_request(url, params)

            # Add the location name to the result
            if "error" not in result:
                result["location_name"] = loc_data.get("name", location)
                result["country"] = loc_data.get("country", "")

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error getting air pollution data")
            return json.dumps({"error": str(e)})
