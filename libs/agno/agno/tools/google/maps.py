"""
GoogleMapsTools — directions, geocoding, distance matrix, and more via Google Maps API.

Prerequisites:
- Set the environment variable `GOOGLE_MAPS_API_KEY` with your Google Maps API key.
  You can obtain the API key from the Google Cloud Console:
  https://console.cloud.google.com/projectselector2/google/maps-apis/credentials

- Enable the required APIs in your Google Cloud project:
  - Directions API
  - Geocoding API
  - Distance Matrix API
  - Elevation API
  - Time Zone API
  - Address Validation API (optional, for validate_address)

Note: For Places search functionality, use GooglePlacesTools instead (requires service account auth).
"""

import json
from datetime import datetime
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    import googlemaps
except ImportError:
    raise ImportError("`googlemaps` not installed. Please install using `pip install googlemaps`")


class GoogleMapsTools(Toolkit):
    def __init__(
        self,
        key: Optional[str] = None,
        get_directions: bool = True,
        geocode_address: bool = True,
        reverse_geocode: bool = True,
        validate_address: bool = True,
        get_distance_matrix: bool = True,
        get_elevation: bool = True,
        get_timezone: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize GoogleMapsTools with the Google Maps API.

        Args:
            key: Google Maps API key. Defaults to GOOGLE_MAPS_API_KEY env var.
            get_directions: Enable directions between locations. Defaults to True.
            geocode_address: Enable address to coordinates conversion. Defaults to True.
            reverse_geocode: Enable coordinates to address conversion. Defaults to True.
            validate_address: Enable address validation. Defaults to True.
            get_distance_matrix: Enable distance/time calculations. Defaults to True.
            get_elevation: Enable elevation lookups. Defaults to True.
            get_timezone: Enable timezone lookups. Defaults to True.
            all: Enable all tools. Defaults to False.
        """
        self.api_key = key or getenv("GOOGLE_MAPS_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_MAPS_API_KEY is not set in the environment variables.")
        self.client = googlemaps.Client(key=self.api_key)

        tools: List[Callable] = []
        if all or get_directions:
            tools.append(self.get_directions)
        if all or validate_address:
            tools.append(self.validate_address)
        if all or geocode_address:
            tools.append(self.geocode_address)
        if all or reverse_geocode:
            tools.append(self.reverse_geocode)
        if all or get_distance_matrix:
            tools.append(self.get_distance_matrix)
        if all or get_elevation:
            tools.append(self.get_elevation)
        if all or get_timezone:
            tools.append(self.get_timezone)

        super().__init__(name="google_maps", tools=tools, **kwargs)

    def get_directions(
        self,
        origin: str,
        destination: str,
        mode: str = "driving",
        avoid: Optional[List[str]] = None,
    ) -> str:
        """
        Get directions between two locations.

        Args:
            origin (str): Starting address or coordinates.
            destination (str): Destination address or coordinates.
            mode (str): Travel mode - "driving", "walking", "bicycling", or "transit".
            avoid (Optional[List[str]]): Features to avoid - "tolls", "highways", "ferries".

        Returns:
            str: JSON with routes array containing steps, distance, and duration.
        """
        try:
            result = self.client.directions(origin, destination, mode=mode, avoid=avoid)
            return json.dumps({"routes": result})
        except Exception as e:
            log_error(f"Error getting directions: {e}")
            return json.dumps({"error": str(e)})

    def validate_address(self, address: str, region_code: str = "US") -> str:
        """
        Validate and standardize an address.

        Args:
            address (str): The address to validate.
            region_code (str): Country code (e.g., "US", "GB", "DE").

        Returns:
            str: JSON with validated/corrected address components.
        """
        try:
            result = self.client.addressvalidation([address], regionCode=region_code)
            return json.dumps({"validation": result})
        except Exception as e:
            log_error(f"Error validating address: {e}")
            return json.dumps({"error": str(e)})

    def geocode_address(self, address: str) -> str:
        """
        Convert an address to latitude/longitude coordinates.

        Args:
            address (str): The address to geocode.

        Returns:
            str: JSON with results array containing lat/lng coordinates and formatted address.
        """
        try:
            result = self.client.geocode(address)
            return json.dumps({"results": result})
        except Exception as e:
            log_error(f"Error geocoding address: {e}")
            return json.dumps({"error": str(e)})

    def reverse_geocode(self, lat: float, lng: float) -> str:
        """
        Convert latitude/longitude coordinates to an address.

        Args:
            lat (float): Latitude.
            lng (float): Longitude.

        Returns:
            str: JSON with results array containing formatted address and address components.
        """
        try:
            result = self.client.reverse_geocode((lat, lng))
            return json.dumps({"results": result})
        except Exception as e:
            log_error(f"Error reverse geocoding: {e}")
            return json.dumps({"error": str(e)})

    def get_distance_matrix(
        self,
        origins: List[str],
        destinations: List[str],
        mode: str = "driving",
    ) -> str:
        """
        Calculate distances and travel times between multiple origins and destinations.

        Args:
            origins (List[str]): List of origin addresses.
            destinations (List[str]): List of destination addresses.
            mode (str): Travel mode - "driving", "walking", "bicycling", or "transit" (default: "driving").

        Returns:
            str: JSON with matrix containing distance and duration for each origin-destination pair.
        """
        try:
            result = self.client.distance_matrix(origins, destinations, mode=mode)
            return json.dumps({"matrix": result})
        except Exception as e:
            log_error(f"Error getting distance matrix: {e}")
            return json.dumps({"error": str(e)})

    def get_elevation(self, lat: float, lng: float) -> str:
        """
        Get the elevation for a location in meters above sea level.

        Args:
            lat (float): Latitude.
            lng (float): Longitude.

        Returns:
            str: JSON with elevation array containing elevation in meters and resolution.
        """
        try:
            result = self.client.elevation((lat, lng))
            return json.dumps({"elevation": result})
        except Exception as e:
            log_error(f"Error getting elevation: {e}")
            return json.dumps({"error": str(e)})

    def get_timezone(self, lat: float, lng: float, timestamp: Optional[datetime] = None) -> str:
        """
        Get timezone information for a location.

        Args:
            lat (float): Latitude.
            lng (float): Longitude.
            timestamp (Optional[datetime]): Timestamp for timezone calculation (default: now).

        Returns:
            str: JSON with timezone containing timeZoneId, timeZoneName, and UTC offset.
        """
        try:
            result = self.client.timezone(location=(lat, lng), timestamp=timestamp or datetime.now())
            return json.dumps({"timezone": result})
        except Exception as e:
            log_error(f"Error getting timezone: {e}")
            return json.dumps({"error": str(e)})
