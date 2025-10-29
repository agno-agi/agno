import uuid
from os import getenv
from typing import Any, List, Optional, Union

import httpx

from agno.agent import Agent
from agno.media import Image
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import logger


class GiphyTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        limit: int = 1,
        enable_search_gifs: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Giphy tools.

        Args:
            api_key: Giphy API key. Defaults to GIPHY_API_KEY environment variable.
            limit: Number of GIFs to return. Defaults to 1.
            enable_search_gifs: Whether to enable GIF search functionality. Defaults to True.
            all: Enable all functions. Defaults to False.
        """
        self.api_key = api_key or getenv("GIPHY_API_KEY")
        if not self.api_key:
            logger.error("No Giphy API key provided")

        self.limit: int = limit

        tools: List[Any] = []
        if all or enable_search_gifs:
            tools.append(self.search_gifs)

        super().__init__(name="giphy_tools", tools=tools, **kwargs)

    def search_gifs(self, agent: Union[Agent, Team], query: str) -> ToolResult:
        """Find a GIPHY gif

        Args:
            query (str): A text description of the required gif.

        Returns:
            ToolResult: Contains the found GIF images or error message.
        """

        base_url = "https://api.giphy.com/v1/gifs/search"
        params = {
            "api_key": self.api_key,
            "q": query,
            "limit": self.limit,
        }

        try:
            response = httpx.get(base_url, params=params)
            response.raise_for_status()

            # Extract the GIF URLs
            data = response.json()
            gif_urls = []
            image_artifacts = []

            for gif in data.get("data", []):
                images = gif.get("images", {})
                original_image = images["original"]

                media_id = str(uuid.uuid4())
                gif_url = original_image["url"]
                alt_text = gif["alt_text"]
                gif_urls.append(gif_url)

                # Create ImageArtifact for the GIF
                image_artifact = Image(id=media_id, url=gif_url, alt_text=alt_text, revised_prompt=query)
                image_artifacts.append(image_artifact)

            if image_artifacts:
                return ToolResult(content=f"Found {len(gif_urls)} GIF(s): {gif_urls}", images=image_artifacts)
            else:
                return ToolResult(content="No gifs found")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
            return ToolResult(content=f"HTTP error occurred: {e.response.status_code}")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            return ToolResult(content=f"An error occurred: {e}")
