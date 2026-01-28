"""Unsplash Tools for searching and retrieving high-quality, royalty-free images.

This toolkit provides AI agents with the ability to search for and retrieve images
from Unsplash, a popular platform with over 4.3 million high-quality photos.

Get your free API key at: https://unsplash.com/developers
"""

import json
from os import getenv
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class UnsplashTools(Toolkit):
    """A toolkit for searching and retrieving images from Unsplash.

    Unsplash provides access to over 4.3 million high-quality, royalty-free images
    that can be used for various purposes. This toolkit enables AI agents to:
    - Search for photos by keywords
    - Get detailed information about specific photos
    - Retrieve random photos with optional filters
    - Track downloads (required by Unsplash API guidelines)

    Example:
        ```python
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        from agno.tools.unsplash import UnsplashTools

        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[UnsplashTools()],
        )
        agent.print_response("Find me 3 photos of mountains at sunset")
        ```
    """

    def __init__(
        self,
        access_key: Optional[str] = None,
        enable_search_photos: bool = True,
        enable_get_photo: bool = True,
        enable_get_random_photo: bool = True,
        enable_download_photo: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        """Initialize the Unsplash toolkit.

        Args:
            access_key: Unsplash API access key. If not provided, will look for
                UNSPLASH_ACCESS_KEY environment variable.
            enable_search_photos: Enable the search_photos tool. Default: True.
            enable_get_photo: Enable the get_photo tool. Default: True.
            enable_get_random_photo: Enable the get_random_photo tool. Default: True.
            enable_download_photo: Enable the download_photo tool. Default: False.
            all: Enable all tools. Default: False.
            **kwargs: Additional arguments passed to the Toolkit base class.
        """
        self.access_key = access_key or getenv("UNSPLASH_ACCESS_KEY")
        if not self.access_key:
            logger.warning("No Unsplash API key provided. Set UNSPLASH_ACCESS_KEY environment variable.")

        self.base_url = "https://api.unsplash.com"

        tools: List[Any] = []
        if all or enable_search_photos:
            tools.append(self.search_photos)
        if all or enable_get_photo:
            tools.append(self.get_photo)
        if all or enable_get_random_photo:
            tools.append(self.get_random_photo)
        if all or enable_download_photo:
            tools.append(self.download_photo)

        super().__init__(name="unsplash_tools", tools=tools, **kwargs)

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make an authenticated request to the Unsplash API.

        Args:
            endpoint: API endpoint path (e.g., "/search/photos").
            params: Optional query parameters.

        Returns:
            JSON response as a dictionary.

        Raises:
            Exception: If the API request fails.
        """
        url = f"{self.base_url}{endpoint}"
        if params:
            url = f"{url}?{urlencode(params)}"

        headers = {
            "Authorization": f"Client-ID {self.access_key}",
            "Accept-Version": "v1",
        }

        request = Request(url, headers=headers)
        with urlopen(request) as response:
            return json.loads(response.read().decode())

    def _format_photo(self, photo: Dict[str, Any]) -> Dict[str, Any]:
        """Format photo data into a clean, consistent structure.

        Args:
            photo: Raw photo data from Unsplash API.

        Returns:
            Formatted photo dictionary with essential fields.
        """
        return {
            "id": photo.get("id"),
            "description": photo.get("description") or photo.get("alt_description"),
            "width": photo.get("width"),
            "height": photo.get("height"),
            "color": photo.get("color"),
            "created_at": photo.get("created_at"),
            "urls": {
                "raw": photo.get("urls", {}).get("raw"),
                "full": photo.get("urls", {}).get("full"),
                "regular": photo.get("urls", {}).get("regular"),
                "small": photo.get("urls", {}).get("small"),
                "thumb": photo.get("urls", {}).get("thumb"),
            },
            "author": {
                "name": photo.get("user", {}).get("name"),
                "username": photo.get("user", {}).get("username"),
                "profile_url": photo.get("user", {}).get("links", {}).get("html"),
            },
            "links": {
                "html": photo.get("links", {}).get("html"),
                "download": photo.get("links", {}).get("download"),
            },
            "likes": photo.get("likes"),
            "tags": [tag.get("title") for tag in photo.get("tags", [])[:5] if tag.get("title")],
        }

    def search_photos(
        self,
        query: str,
        per_page: int = 10,
        page: int = 1,
        orientation: Optional[str] = None,
        color: Optional[str] = None,
    ) -> str:
        """Search for photos on Unsplash by keyword.

        Args:
            query: The search query string (e.g., "mountain sunset", "office workspace").
            per_page: Number of results per page (1-30). Default: 10.
            page: Page number to retrieve. Default: 1.
            orientation: Filter by orientation: "landscape", "portrait", or "squarish".
            color: Filter by color: "black_and_white", "black", "white", "yellow",
                "orange", "red", "purple", "magenta", "green", "teal", "blue".

        Returns:
            JSON string containing search results with photo details including
            URLs, author information, and metadata.
        """
        if not self.access_key:
            return "Error: No Unsplash API key provided. Set UNSPLASH_ACCESS_KEY environment variable."

        if not query:
            return "Error: Please provide a search query."

        log_debug(f"Searching Unsplash for: {query}")

        try:
            params: Dict[str, Any] = {
                "query": query,
                "per_page": min(max(1, per_page), 30),
                "page": max(1, page),
            }

            if orientation and orientation in ["landscape", "portrait", "squarish"]:
                params["orientation"] = orientation

            if color:
                valid_colors = [
                    "black_and_white",
                    "black",
                    "white",
                    "yellow",
                    "orange",
                    "red",
                    "purple",
                    "magenta",
                    "green",
                    "teal",
                    "blue",
                ]
                if color in valid_colors:
                    params["color"] = color

            response = self._make_request("/search/photos", params)

            results = {
                "total": response.get("total", 0),
                "total_pages": response.get("total_pages", 0),
                "photos": [self._format_photo(photo) for photo in response.get("results", [])],
            }

            return json.dumps(results, indent=2)

        except Exception as e:
            return f"Error searching Unsplash: {e}"

    def get_photo(self, photo_id: str) -> str:
        """Get detailed information about a specific photo.

        Args:
            photo_id: The unique identifier of the photo.

        Returns:
            JSON string containing detailed photo information including
            URLs, author, metadata, EXIF data, and location if available.
        """
        if not self.access_key:
            return "Error: No Unsplash API key provided. Set UNSPLASH_ACCESS_KEY environment variable."

        if not photo_id:
            return "Error: Please provide a photo ID."

        log_debug(f"Getting Unsplash photo: {photo_id}")

        try:
            photo = self._make_request(f"/photos/{photo_id}")

            result = self._format_photo(photo)

            # Add extra details available for single photo requests
            if photo.get("exif"):
                result["exif"] = {
                    "make": photo["exif"].get("make"),
                    "model": photo["exif"].get("model"),
                    "aperture": photo["exif"].get("aperture"),
                    "exposure_time": photo["exif"].get("exposure_time"),
                    "focal_length": photo["exif"].get("focal_length"),
                    "iso": photo["exif"].get("iso"),
                }

            if photo.get("location"):
                result["location"] = {
                    "name": photo["location"].get("name"),
                    "city": photo["location"].get("city"),
                    "country": photo["location"].get("country"),
                }

            result["views"] = photo.get("views")
            result["downloads"] = photo.get("downloads")

            return json.dumps(result, indent=2)

        except Exception as e:
            return f"Error getting photo: {e}"

    def get_random_photo(
        self,
        query: Optional[str] = None,
        orientation: Optional[str] = None,
        count: int = 1,
    ) -> str:
        """Get random photo(s) from Unsplash.

        Args:
            query: Optional search query to filter random photos.
            orientation: Filter by orientation: "landscape", "portrait", or "squarish".
            count: Number of random photos to return (1-30). Default: 1.

        Returns:
            JSON string containing random photo(s) data.
        """
        if not self.access_key:
            return "Error: No Unsplash API key provided. Set UNSPLASH_ACCESS_KEY environment variable."

        log_debug(f"Getting random Unsplash photo (query={query})")

        try:
            params: Dict[str, Any] = {
                "count": min(max(1, count), 30),
            }

            if query:
                params["query"] = query

            if orientation and orientation in ["landscape", "portrait", "squarish"]:
                params["orientation"] = orientation

            response = self._make_request("/photos/random", params)

            # Response is a list when count > 1, single object when count = 1
            if isinstance(response, list):
                photos = [self._format_photo(photo) for photo in response]
            else:
                photos = [self._format_photo(response)]

            return json.dumps({"photos": photos}, indent=2)

        except Exception as e:
            return f"Error getting random photo: {e}"

    def download_photo(self, photo_id: str) -> str:
        """Trigger a download event for a photo.

        This is required by the Unsplash API guidelines when a photo is downloaded
        or used. It helps photographers track the usage of their work.

        Args:
            photo_id: The unique identifier of the photo being downloaded.

        Returns:
            JSON string with the download URL.
        """
        if not self.access_key:
            return "Error: No Unsplash API key provided. Set UNSPLASH_ACCESS_KEY environment variable."

        if not photo_id:
            return "Error: Please provide a photo ID."

        log_debug(f"Tracking download for Unsplash photo: {photo_id}")

        try:
            response = self._make_request(f"/photos/{photo_id}/download")

            return json.dumps(
                {
                    "photo_id": photo_id,
                    "download_url": response.get("url"),
                },
                indent=2,
            )

        except Exception as e:
            return f"Error tracking download: {e}"
