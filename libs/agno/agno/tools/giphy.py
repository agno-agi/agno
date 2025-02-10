import os
import uuid
from typing import Optional

import httpx

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools import Toolkit
from agno.utils.log import logger


class GiphyTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        limit: int = 1,
    ):
        super().__init__(name="giphy_tools")

        self.api_key = api_key or os.getenv("GIPHY_API_KEY")
        if not self.api_key:
            logger.error("No Giphy API key provided")

        self.limit: int = limit

        self.register(self.search_gifs)

    def search_gifs(self, agent: Agent, query: str) -> str:
        """Find a GIPHY gif

        Args:
            query (str): A text description of the required gif.

        Returns:
            result (str): A string containing urls of GIFs found
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
            for gif in data.get("data", []):
                images = gif.get("images", {})
                original_image = images["original"]

                media_id = str(uuid.uuid4())
                gif_url = original_image["url"]
                alt_text = gif["alt_text"]
                gif_urls.append(gif_url)

                agent.add_image(ImageArtifact(id=media_id, url=gif_url, alt_text=alt_text, revised_prompt=query))

            return f"These are the found gifs {gif_urls}"

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            logger.error(f"An error occurred: {e}")

        return "No gifs found"
