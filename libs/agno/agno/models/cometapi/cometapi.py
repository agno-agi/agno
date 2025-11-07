from dataclasses import dataclass, field
from os import getenv
from typing import List, Optional

import httpx

from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug


@dataclass
class CometAPI(OpenAILike):
    """
    The CometAPI class provides access to multiple AI model providers
    (GPT, Claude, Gemini, DeepSeek, etc.) through OpenAI-compatible endpoints.

    Args:
        id (str): The id of the CometAPI model to use. Default is "gpt-5-mini".
        name (str): The name for this model. Defaults to "CometAPI".
        api_key (str): The API key for CometAPI. Defaults to COMETAPI_KEY environment variable.
        base_url (str): The base URL for CometAPI. Defaults to "https://api.cometapi.com/v1".
    """

    name: str = "CometAPI"
    id: str = "gpt-5-mini"
    api_key: Optional[str] = field(default_factory=lambda: getenv("COMETAPI_KEY"))
    base_url: str = "https://api.cometapi.com/v1"

    def get_available_models(self) -> List[str]:
        """
        Fetch available chat models from CometAPI, filtering out non-chat models.

        Returns:
            List of available chat model IDs
        """
        if not self.api_key:
            log_debug("No API key provided, returning empty model list")
            return []

        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                    timeout=30.0,
                )
                response.raise_for_status()

                data = response.json()
                all_models = data.get("data", [])

                log_debug(f"Found {len(all_models)} total models")
                return sorted(all_models)

        except Exception as e:
            log_debug(f"Error fetching models from CometAPI: {e}")
            return []
