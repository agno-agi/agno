"""
OpenRouteService toolkit for accurate, real-world routing between locations.

OpenRouteService (https://openrouteservice.org) is a free, OpenStreetMap-based
routing service. Unlike a language model estimating distances, it returns the
actual routed distance and travel time for driving, cycling and walking
profiles, so an agent can answer questions like "how far is it to drive from
Berlin to Amsterdam?" precisely instead of guessing.

Prerequisites:
- Create a free account at https://account.heigit.org and generate an API token
  (no credit card required).
- Set the environment variable `ORS_API_KEY` with your token, or pass
  `api_key="..."` when constructing the toolkit.

Note:
- OpenRouteService does not provide public transit / train routing. Use the
  `driving-car`, `cycling-*` or `foot-*` profiles for road-based routing, or
  fall back to `GoogleMapTools` for transit directions.
"""

from os import getenv
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install it via `pip install httpx`.")

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

# Routing profiles supported by OpenRouteService.
VALID_PROFILES = {
    "driving-car",
    "driving-hgv",
    "cycling-regular",
    "cycling-road",
    "cycling-mountain",
    "cycling-electric",
    "foot-walking",
    "foot-hiking",
    "wheelchair",
}


class OpenRouteServiceTools(Toolkit):
    """Toolkit for geocoding and accurate road routing via OpenRouteService.

    Args:
        api_key (Optional[str]): OpenRouteService API token. If not provided, the
            `ORS_API_KEY` environment variable is used.
        base_url (str): Base URL for the OpenRouteService API.
        timeout (float): Per-request HTTP timeout in seconds. Default is 30.
        enable_directions (bool): Enable the `get_directions` tool. Default is True.
        enable_distance_matrix (bool): Enable the `get_distance_matrix` tool. Default is True.
        enable_geocoding (bool): Enable the `geocode_location` tool. Default is True.
        all (bool): Enable all tools regardless of the individual flags. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openrouteservice.org",
        timeout: float = 30.0,
        enable_directions: bool = True,
        enable_distance_matrix: bool = True,
        enable_geocoding: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("ORS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenRouteService API key is required. Provide it as an argument or set the ORS_API_KEY "
                "environment variable. Get a free token at https://account.heigit.org (no credit card required)."
            )

        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)

        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []

        if all or enable_geocoding:
            tools.append(self.geocode_location)
            async_tools.append((self.ageocode_location, "geocode_location"))
        if all or enable_directions:
            tools.append(self.get_directions)
            async_tools.append((self.aget_directions, "get_directions"))
        if all or enable_distance_matrix:
            tools.append(self.get_distance_matrix)
            async_tools.append((self.aget_distance_matrix, "get_distance_matrix"))

        name = kwargs.pop("name", "openrouteservice_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    # ---------------------------------------------------------------------
    # Helpers (pure — no I/O)
    # ---------------------------------------------------------------------
    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": self.api_key or "", "Content-Type": "application/json"}

    @staticmethod
    def _validate_profile(profile: str) -> Optional[Dict[str, str]]:
        """Return an error dict if the profile is invalid, otherwise None."""
        if profile not in VALID_PROFILES:
            return {"error": f"Invalid profile '{profile}'. Valid profiles are: {', '.join(sorted(VALID_PROFILES))}."}
        return None

    @staticmethod
    def _http_error(exc: "httpx.HTTPStatusError") -> Dict[str, str]:
        status = exc.response.status_code
        if status in (401, 403):
            return {"error": "Invalid or unauthorized OpenRouteService API key."}
        if status == 404:
            return {"error": "No route found between the given locations for this profile."}
        if status == 429:
            return {"error": "OpenRouteService rate limit exceeded. Try again later."}
        return {"error": f"OpenRouteService API error: {status}."}

    @staticmethod
    def _parse_geocode(data: Dict[str, Any], location: str) -> Dict[str, Any]:
        features = data.get("features") or []
        if not features:
            return {"error": f"No location found for '{location}'."}
        top = features[0]
        lon, lat = top["geometry"]["coordinates"]
        return {
            "query": location,
            "label": top.get("properties", {}).get("label", location),
            "latitude": lat,
            "longitude": lon,
        }

    @staticmethod
    def _format_directions(data: Dict[str, Any], start_label: str, end_label: str, profile: str) -> Dict[str, Any]:
        routes = data.get("routes") or []
        if not routes:
            return {"error": "No route found between the given locations for this profile."}
        summary = routes[0].get("summary", {})
        distance_m = summary.get("distance", 0.0)
        duration_s = summary.get("duration", 0.0)
        return {
            "start": start_label,
            "end": end_label,
            "profile": profile,
            "distance_km": round(distance_m / 1000, 2),
            "distance_meters": round(distance_m, 1),
            "duration_seconds": round(duration_s, 1),
            "duration_minutes": round(duration_s / 60, 1),
        }

    # ---------------------------------------------------------------------
    # Geocoding
    # ---------------------------------------------------------------------
    def geocode_location(self, location: str) -> Dict[str, Any]:
        """Convert a place name or address into geographic coordinates.

        Args:
            location (str): A place name or address, e.g. "Berlin", "Amsterdam", "1600 Amphitheatre Pkwy".

        Returns:
            Dict[str, Any]: The resolved label, latitude and longitude, or an error.
        """
        log_info(f"Geocoding location: {location}")
        params = {"api_key": self.api_key, "text": location, "size": 1}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/geocode/search", params=params)
                response.raise_for_status()
                return self._parse_geocode(response.json(), location)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception("Error geocoding location")
            return {"error": str(e)}

    async def ageocode_location(self, location: str) -> Dict[str, Any]:
        """Convert a place name or address into geographic coordinates (async).

        Args:
            location (str): A place name or address, e.g. "Berlin", "Amsterdam", "1600 Amphitheatre Pkwy".

        Returns:
            Dict[str, Any]: The resolved label, latitude and longitude, or an error.
        """
        log_info(f"Geocoding location: {location}")
        params = {"api_key": self.api_key, "text": location, "size": 1}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/geocode/search", params=params)
                response.raise_for_status()
                return self._parse_geocode(response.json(), location)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception("Error geocoding location")
            return {"error": str(e)}

    # ---------------------------------------------------------------------
    # Directions
    # ---------------------------------------------------------------------
    def get_directions(self, start_location: str, end_location: str, profile: str = "driving-car") -> Dict[str, Any]:
        """Get the accurate routed distance and travel time between two locations.

        Place names or addresses are geocoded automatically, so you can pass values
        like "Berlin" and "Amsterdam" directly.

        Args:
            start_location (str): Starting place name or address (e.g. "Berlin").
            end_location (str): Destination place name or address (e.g. "Amsterdam").
            profile (str): Travel profile. One of: "driving-car", "driving-hgv",
                "cycling-regular", "cycling-road", "cycling-mountain", "cycling-electric",
                "foot-walking", "foot-hiking", "wheelchair". Defaults to "driving-car".
                Public transit / train routing is not supported.

        Returns:
            Dict[str, Any]: Route summary with distance (km and meters) and duration
            (seconds and minutes), or an error.
        """
        invalid = self._validate_profile(profile)
        if invalid:
            return invalid

        start = self.geocode_location(start_location)
        if "error" in start:
            return {"error": f"Could not resolve start location: {start['error']}"}
        end = self.geocode_location(end_location)
        if "error" in end:
            return {"error": f"Could not resolve end location: {end['error']}"}

        log_info(f"Getting {profile} directions from {start['label']} to {end['label']}")
        payload = {"coordinates": [[start["longitude"], start["latitude"]], [end["longitude"], end["latitude"]]]}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/v2/directions/{profile}", headers=self._auth_headers(), json=payload
                )
                response.raise_for_status()
                return self._format_directions(response.json(), start["label"], end["label"], profile)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception("Error getting directions")
            return {"error": str(e)}

    async def aget_directions(
        self, start_location: str, end_location: str, profile: str = "driving-car"
    ) -> Dict[str, Any]:
        """Get the accurate routed distance and travel time between two locations (async).

        Place names or addresses are geocoded automatically, so you can pass values
        like "Berlin" and "Amsterdam" directly.

        Args:
            start_location (str): Starting place name or address (e.g. "Berlin").
            end_location (str): Destination place name or address (e.g. "Amsterdam").
            profile (str): Travel profile. One of: "driving-car", "driving-hgv",
                "cycling-regular", "cycling-road", "cycling-mountain", "cycling-electric",
                "foot-walking", "foot-hiking", "wheelchair". Defaults to "driving-car".
                Public transit / train routing is not supported.

        Returns:
            Dict[str, Any]: Route summary with distance (km and meters) and duration
            (seconds and minutes), or an error.
        """
        invalid = self._validate_profile(profile)
        if invalid:
            return invalid

        start = await self.ageocode_location(start_location)
        if "error" in start:
            return {"error": f"Could not resolve start location: {start['error']}"}
        end = await self.ageocode_location(end_location)
        if "error" in end:
            return {"error": f"Could not resolve end location: {end['error']}"}

        log_info(f"Getting {profile} directions from {start['label']} to {end['label']}")
        payload = {"coordinates": [[start["longitude"], start["latitude"]], [end["longitude"], end["latitude"]]]}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v2/directions/{profile}", headers=self._auth_headers(), json=payload
                )
                response.raise_for_status()
                return self._format_directions(response.json(), start["label"], end["label"], profile)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception("Error getting directions")
            return {"error": str(e)}

    # ---------------------------------------------------------------------
    # Distance matrix
    # ---------------------------------------------------------------------
    def _resolve_locations(self, locations: List[str]) -> Any:
        """Geocode a list of place names to [lon, lat] pairs (sync). Returns error dict on failure."""
        coordinates: List[List[float]] = []
        labels: List[str] = []
        for location in locations:
            resolved = self.geocode_location(location)
            if "error" in resolved:
                return {"error": f"Could not resolve location '{location}': {resolved['error']}"}
            coordinates.append([resolved["longitude"], resolved["latitude"]])
            labels.append(resolved["label"])
        return coordinates, labels

    async def _aresolve_locations(self, locations: List[str]) -> Any:
        """Geocode a list of place names to [lon, lat] pairs (async). Returns error dict on failure."""
        coordinates: List[List[float]] = []
        labels: List[str] = []
        for location in locations:
            resolved = await self.ageocode_location(location)
            if "error" in resolved:
                return {"error": f"Could not resolve location '{location}': {resolved['error']}"}
            coordinates.append([resolved["longitude"], resolved["latitude"]])
            labels.append(resolved["label"])
        return coordinates, labels

    @staticmethod
    def _matrix_payload(coordinates: List[List[float]]) -> Dict[str, Any]:
        return {"locations": coordinates, "metrics": ["distance", "duration"], "units": "km"}

    @staticmethod
    def _format_matrix(data: Dict[str, Any], labels: List[str], profile: str) -> Dict[str, Any]:
        return {
            "profile": profile,
            "locations": labels,
            "distances_km": data.get("distances"),
            "durations_seconds": data.get("durations"),
        }

    def get_distance_matrix(self, locations: List[str], profile: str = "driving-car") -> Dict[str, Any]:
        """Compute a matrix of routed distances and travel times between many locations.

        Args:
            locations (List[str]): Place names or addresses (e.g. ["Berlin", "Amsterdam", "Paris"]).
            profile (str): Travel profile (see `get_directions`). Defaults to "driving-car".

        Returns:
            Dict[str, Any]: `distances_km` and `durations_seconds` matrices where entry
            [i][j] is from location i to location j, or an error.
        """
        invalid = self._validate_profile(profile)
        if invalid:
            return invalid
        if not locations or len(locations) < 2:
            return {"error": "Provide at least two locations for a distance matrix."}

        resolved = self._resolve_locations(locations)
        if isinstance(resolved, dict):
            return resolved
        coordinates, labels = resolved

        log_info(f"Getting {profile} distance matrix for {len(labels)} locations")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/v2/matrix/{profile}",
                    headers=self._auth_headers(),
                    json=self._matrix_payload(coordinates),
                )
                response.raise_for_status()
                return self._format_matrix(response.json(), labels, profile)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception("Error getting distance matrix")
            return {"error": str(e)}

    async def aget_distance_matrix(self, locations: List[str], profile: str = "driving-car") -> Dict[str, Any]:
        """Compute a matrix of routed distances and travel times between many locations (async).

        Args:
            locations (List[str]): Place names or addresses (e.g. ["Berlin", "Amsterdam", "Paris"]).
            profile (str): Travel profile (see `get_directions`). Defaults to "driving-car".

        Returns:
            Dict[str, Any]: `distances_km` and `durations_seconds` matrices where entry
            [i][j] is from location i to location j, or an error.
        """
        invalid = self._validate_profile(profile)
        if invalid:
            return invalid
        if not locations or len(locations) < 2:
            return {"error": "Provide at least two locations for a distance matrix."}

        resolved = await self._aresolve_locations(locations)
        if isinstance(resolved, dict):
            return resolved
        coordinates, labels = resolved

        log_info(f"Getting {profile} distance matrix for {len(labels)} locations")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/v2/matrix/{profile}",
                    headers=self._auth_headers(),
                    json=self._matrix_payload(coordinates),
                )
                response.raise_for_status()
                return self._format_matrix(response.json(), labels, profile)
        except httpx.HTTPStatusError as e:
            return self._http_error(e)
        except Exception as e:
            logger.exception("Error getting distance matrix")
            return {"error": str(e)}
