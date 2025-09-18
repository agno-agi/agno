from dataclasses import dataclass
from os import getenv
from typing import List

from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


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

    def __post_init__(self):
        """Initialize CometAPI with default values."""
        # Set default base_url if not provided
        if not self.base_url:
            self.base_url = "https://api.cometapi.com/v1"

        # Set default api_key from environment if not provided or if it's the default value
        if not self.api_key or self.api_key == "not-provided":
            env_key = getenv("COMETAPI_KEY")
            if env_key:
                self.api_key = env_key

        super().__post_init__()

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
