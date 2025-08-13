import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")


class OpenWeatherTools(Toolkit):
    """
    OpenWeather is a toolkit for accessing weather data from OpenWeatherMap API.

    Args:
        api_key (Optional[str]): OpenWeatherMap API key. If not provided, will try to get from OPENWEATHER_API_KEY env var.
        units (str): Units of measurement. Options are 'standard', 'metric', and 'imperial'. Default is 'metric'.
        current_weather (bool): Enable current weather function. Default is True.
        forecast (bool): Enable forecast function. Default is True.
        air_pollution (bool): Enable air pollution function. Default is True.
        geocoding (bool): Enable geocoding function. Default is True.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        units: str = "metric",
        current_weather: bool = True,
        forecast: bool = True,
        air_pollution: bool = True,
        geocoding: bool = True,
        **kwargs,
    ):
        self.api_key = api_key or getenv("OPENWEATHER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenWeather API key is required. Provide it as an argument or set the OPENWEATHER_API_KEY environment variable."
            )

        self.units = units
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self.geo_url = "https://api.openweathermap.org/geo/1.0"

        tools: List[Any] = []
        if current_weather:
            tools.append(self.get_current_weather)
        if forecast:
            tools.append(self.get_forecast)
        if air_pollution:
            tools.append(self.get_air_pollution)
        if geocoding:
            tools.append(self.geocode_location)

        super().__init__(name="openweather_tools", tools=tools, **kwargs)

    def _make_request(self, url: str, params: Dict) -> Dict:
        """Make a request to the OpenWeatherMap API.

        Args:
            url (str): The API endpoint URL.
            params (Dict): Query parameters for the request.

        Returns:
            Dict: The JSON response from the API.
        """
        try:
            params["appid"] = self.api_key
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {url}: {e}")
            return {"error": str(e)}

    def geocode_location(self, location: str, limit: int = 1) -> str:
        """Convert a location name to geographic coordinates.

        Args:
            location (str): The name of the city, e.g., "London", "Paris", "New York".
            limit (int): Maximum number of location results. Default is 1.

        Returns:
            str: JSON string containing location data with coordinates.
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
            logger.error(f"Error geocoding location: {e}")
            return json.dumps({"error": str(e)})

    def get_current_weather(self, location: str) -> str:
        """Get current weather data for a location.

        Args:
            location (str): The name of the city, e.g., "London", "Paris", "New York".

        Returns:
            str: JSON string containing current weather data.
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
            logger.error(f"Error getting current weather: {e}")
            return json.dumps({"error": str(e)})

    def get_forecast(self, location: str, days: int = 5) -> str:
        """Get weather forecast for a location.

        Args:
            location (str): The name of the city, e.g., "London", "Paris", "New York".
            days (int): Number of days for forecast (max 5). Default is 5.

        Returns:
            str: JSON string containing forecast data.
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
            logger.error(f"Error getting forecast: {e}")
            return json.dumps({"error": str(e)})

    def get_air_pollution(self, location: str) -> str:
        """Get current air pollution data for a location.

        Args:
            location (str): The name of the city, e.g., "London", "Paris", "New York".

        Returns:
            str: JSON string containing air pollution data.
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
            logger.error(f"Error getting air pollution data: {e}")
            return json.dumps({"error": str(e)})
