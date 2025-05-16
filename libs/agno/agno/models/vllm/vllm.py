from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.models.openai.like import OpenAILike


@dataclass
class Vllm(OpenAILike):
    """
    Class for interacting with the vLLM models via OpenAI-like interface.

    Attributes:
        id (str): The ID of the language model.
        name (str): The name of the API.
        provider (str): The provider of the API.
        base_url (str): The base URL for the vLLM API.
    """

    # Agno metadata
    id: str = "not-provided"
    name: str = "vLLM"
    provider: str = "vLLM"

    # Client parameters
    api_key: Optional[str] = getenv("VLLM_API_KEY") or None  # do not send header if unset
    base_url: str = getenv("VLLM_BASE_URL", "http://localhost:8000/v1/")  # trailing slash

    # Common request parameters (piggy-back on OpenAIChat)
    max_tokens: Optional[int] = 1024
    top_k: Optional[int] = None
    repetition_penalty: Optional[float] = None
    supports_json_schema_outputs: bool = True

    def _get_client_params(self) -> Dict[str, Any]:
        """Get the client parameters for the vLLM API."""
        base_params: Dict[str, Any] = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }
        if self.http_client:
            base_params["http_client"] = self.http_client
        return {k: v for k, v in base_params.items() if v is not None}

    def get_request_kwargs(self, **kwargs) -> Dict[str, Any]:
        """Add vLLM-specific generation parameters."""
        request = super().get_request_kwargs(**kwargs)
        if self.top_k is not None:
            request["top_k"] = self.top_k
        if self.repetition_penalty is not None:
            request["repetition_penalty"] = self.repetition_penalty
        return request
