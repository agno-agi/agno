from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug


@dataclass
class ApiRoute(OpenAILike):
    """
    A class for interacting with API Route models.

    API Route is a unified AI router and gateway connecting to hundreds of top models
    (Claude, GPT, Gemini, DeepSeek, Llama, and more) with high availability and OpenAI compatibility.

    Attributes:
        id (str): The model ID to use. Defaults to "claude-3-7-sonnet-20250219".
        name (str): The model name. Defaults to "ApiRoute".
        provider (str): The provider name. Defaults to "ApiRoute".
        api_key (Optional[str]): The API Route API key. Defaults to APIROUTE_API_KEY environment variable.
        base_url (str): The base URL for API Route. Defaults to "https://global.api-route.com/v1".
    """

    id: str = "claude-3-7-sonnet-20250219"
    name: str = "ApiRoute"
    provider: str = "ApiRoute"

    api_key: Optional[str] = field(default_factory=lambda: getenv("APIROUTE_API_KEY"))
    base_url: str = "https://global.api-route.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for APIROUTE_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("APIROUTE_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="APIROUTE_API_KEY not set. Please set the APIROUTE_API_KEY environment variable.",
                    model_name=self.name,
                )

        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        client_params = {k: v for k, v in base_params.items() if v is not None}

        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_available_models(self) -> List[str]:
        """
        Fetch available models from API Route.

        Returns:
            List[str]: List of available model IDs.
        """
        if not self.api_key:
            self.api_key = getenv("APIROUTE_API_KEY")
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
                raw_models = data.get("data", [])
                model_ids = [m.get("id") if isinstance(m, dict) else str(m) for m in raw_models]

                log_debug(f"Found {len(model_ids)} total models")
                return sorted(model_ids)

        except Exception as e:
            log_debug(f"Error fetching models from API Route: {e}")
            return []
