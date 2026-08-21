"""
GooglePlacesTools — search, details, and autocomplete via Google Places API (New).

Prerequisites:
- Enable the Places API (New) in your Google Cloud project:
  https://console.cloud.google.com/apis/library/places.googleapis.com

- Authenticate with an API key (recommended):
  export GOOGLE_PLACES_API_KEY=your-api-key

- Or use Application Default Credentials (ADC):
  gcloud auth application-default login --project=your-project-id
"""

import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from google.maps import places_v1
    from google.protobuf.json_format import MessageToDict
except ImportError:
    raise ImportError("`google-maps-places` not installed. Please install using `pip install google-maps-places`")


class GooglePlacesTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        search_places: bool = True,
        search_nearby: bool = False,
        get_place_details: bool = False,
        autocomplete: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize GooglePlacesTools with the Places API (New).

        Args:
            api_key: Google Places API key. Defaults to GOOGLE_PLACES_API_KEY or GOOGLE_MAPS_API_KEY env var.
            search_places: Enable text-based place search. Defaults to True.
            search_nearby: Enable location-based nearby search. Defaults to False.
            get_place_details: Enable fetching detailed place information. Defaults to False.
            autocomplete: Enable place autocomplete predictions. Defaults to False.
            all: Enable all tools. Defaults to False.
        """
        self.api_key = api_key or getenv("GOOGLE_PLACES_API_KEY") or getenv("GOOGLE_MAPS_API_KEY")
        # ADC fallback: if no API key, let the SDK use Application Default Credentials
        if self.api_key:
            self.client = places_v1.PlacesClient(client_options={"api_key": self.api_key})
        else:
            self.client = places_v1.PlacesClient()

        tools: List[Callable] = []
        if all or search_places:
            tools.append(self.search_places)
        if all or search_nearby:
            tools.append(self.search_nearby)
        if all or get_place_details:
            tools.append(self.get_place_details)
        if all or autocomplete:
            tools.append(self.autocomplete)

        super().__init__(name="google_places", tools=tools, **kwargs)

    def search_places(self, query: str, language_code: str = "en") -> str:
        """
        Search for places using a text query.

        Args:
            query (str): The search query.
            language_code (str): Language for results.

        Returns:
            str: JSON with places array containing name, address, rating, phone, website, hours, reviews.
        """
        try:
            # 1. Build the request object with search parameters
            request = places_v1.SearchTextRequest(text_query=query, language_code=language_code)

            # 2. Call the API with fieldmask="*" to request all available fields
            response = self.client.search_text(request=request, metadata=[("x-goog-fieldmask", "*")])

            # 3. Convert protobuf Place objects to dicts
            places = [MessageToDict(place._pb) for place in response.places]
            return json.dumps({"places": places, "count": len(places)})
        except Exception as e:
            log_error(f"Error searching places: {e}")
            return json.dumps({"error": str(e)})

    def search_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_meters: float = 1000.0,
        place_type: Optional[str] = None,
        max_results: int = 20,
    ) -> str:
        """
        Search for places near a specific location.

        Args:
            latitude (float): Latitude of the center point.
            longitude (float): Longitude of the center point.
            radius_meters (float): Search radius in meters (default: 1000).
            place_type (Optional[str]): Filter by type (e.g., "restaurant", "cafe", "gas_station", "hospital").
            max_results (int): Maximum number of results to return (default: 20).

        Returns:
            str: JSON with nearby places array.
        """
        try:
            # 1. Define search area as a circle around the coordinates
            location_restriction = places_v1.SearchNearbyRequest.LocationRestriction(
                circle=places_v1.Circle(
                    center={"latitude": latitude, "longitude": longitude},
                    radius=radius_meters,
                )
            )

            # 2. Build request with location and result limit
            request = places_v1.SearchNearbyRequest(
                location_restriction=location_restriction,
                max_result_count=max_results,
            )
            if place_type:
                request.included_types = [place_type]

            # 3. Call API and convert results
            response = self.client.search_nearby(request=request, metadata=[("x-goog-fieldmask", "*")])
            places = [MessageToDict(place._pb) for place in response.places]
            return json.dumps({"places": places, "count": len(places)})
        except Exception as e:
            log_error(f"Error searching nearby: {e}")
            return json.dumps({"error": str(e)})

    def get_place_details(self, place_id: str) -> str:
        """
        Get detailed information about a place by its ID.

        Args:
            place_id (str): The place ID from search results.

        Returns:
            str: JSON with place details including name, address, rating, phone, website, hours, reviews.
        """
        try:
            # API expects format "places/{place_id}"
            request = places_v1.GetPlaceRequest(name=f"places/{place_id}")
            response = self.client.get_place(request=request, metadata=[("x-goog-fieldmask", "*")])
            return json.dumps({"place": MessageToDict(response._pb)})
        except Exception as e:
            log_error(f"Error getting place details: {e}")
            return json.dumps({"error": str(e)})

    def autocomplete(self, input_text: str) -> str:
        """
        Get place autocomplete suggestions for partial input.

        Args:
            input_text (str): Partial text to autocomplete.

        Returns:
            str: JSON with suggestions array containing place_id and text.
        """
        try:
            request = places_v1.AutocompletePlacesRequest(input=input_text, include_query_predictions=True)
            response = self.client.autocomplete_places(request=request)

            suggestions = []
            for suggestion in response.suggestions:
                if suggestion.place_prediction:
                    pred = suggestion.place_prediction
                    suggestions.append(
                        {
                            "type": "place",
                            "place_id": pred.place_id,
                            "text": pred.text.text if pred.text else None,
                        }
                    )
                elif suggestion.query_prediction:
                    pred = suggestion.query_prediction
                    suggestions.append(
                        {
                            "type": "query",
                            "text": pred.text.text if pred.text else None,
                        }
                    )

            return json.dumps({"suggestions": suggestions, "count": len(suggestions)})
        except Exception as e:
            log_error(f"Error getting autocomplete: {e}")
            return json.dumps({"error": str(e)})
