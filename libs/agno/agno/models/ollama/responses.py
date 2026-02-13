from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.models.openai.open_responses import OpenResponses
from agno.utils.log import log_debug


@dataclass
class OllamaResponses(OpenResponses):
    """
    A class for interacting with Ollama models using the OpenAI Responses API.

    This uses Ollama's OpenAI-compatible `/v1/responses` endpoint, which was added
    in Ollama v0.13.3. It allows using Ollama models with the Responses API format.

    Note: Ollama's Responses API is stateless - it does not support `previous_response_id`
    or conversation chaining. Each request is independent.

    Requirements:
    - Ollama v0.13.3 or later
    - For local usage: Ollama server running at http://localhost:11434
    - For Ollama Cloud: Set OLLAMA_API_KEY environment variable

    For more information, see: https://docs.ollama.com/api/openai-compatibility

    Attributes:
        id (str): The model id. Defaults to "gpt-oss:20b".
        name (str): The model name. Defaults to "OllamaResponses".
        provider (str): The provider name. Defaults to "Ollama".
        host (Optional[str]): The Ollama server host. Defaults to "http://localhost:11434".
        api_key (Optional[str]): The API key for Ollama Cloud. Not required for local usage.
    """

    id: str = "gpt-oss:20b"
    name: str = "OllamaResponses"
    provider: str = "Ollama"

    # Ollama server host - defaults to local instance
    host: Optional[str] = None

    # API key for Ollama Cloud (not required for local)
    api_key: Optional[str] = field(default_factory=lambda: getenv("OLLAMA_API_KEY"))

    # Ollama's Responses API is stateless
    store: Optional[bool] = False

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Get client parameters for API requests.

        Returns:
            Dict[str, Any]: Client parameters including base_url and optional api_key.
        """
        # Determine the base URL
        if self.host:
            base_url = self.host.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"
        elif self.api_key:
            # Ollama Cloud
            base_url = "https://ollama.com/v1"
            log_debug(f"Using Ollama Cloud endpoint: {base_url}")
        else:
            # Local Ollama instance
            base_url = "http://localhost:11434/v1"

        # Build client params
        base_params: Dict[str, Any] = {
            "base_url": base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Add API key if provided (required for Ollama Cloud, ignored for local)
        if self.api_key:
            base_params["api_key"] = self.api_key
        else:
            # OpenAI client requires an api_key, but Ollama ignores it locally
            base_params["api_key"] = "ollama"

        # Filter out None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def _using_reasoning_model(self) -> bool:
        """
        Ollama doesn't have native reasoning models like OpenAI's o-series.

        Some models may support thinking/reasoning through their architecture
        (like DeepSeek-R1), but they don't use OpenAI's reasoning API format.
        """
        return False
