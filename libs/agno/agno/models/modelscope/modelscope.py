from dataclasses import dataclass
from os import getenv
from typing import Optional, Dict, Any

from agno.models.openai.like import OpenAILike
from agno.utils.log import logger
from agno.exceptions import ModelProviderError


@dataclass
class ModelScope(OpenAILike):
    """
    A class for interacting with ModelScope models.

    For more information, see: https://www.modelscope.cn/
    """

    id: str = "modelscope-chat"
    name: str = "ModelScope"
    provider: str = "ModelScope"

    api_key: Optional[str] = getenv("MODELSCOPE_API_KEY", None)
    base_url: str = "https://api-inference.modelscope.cn/v1/"

    role_map = {
        "system": "system",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }

    def _get_client_params(self) -> Dict[str, Any]:
            # Fetch API key from env if not already set
            if not self.api_key:
                error_message = "MODELSCOPE_API_KEY not set. Please set the MODELSCOPE_API_KEY environment variable."
                logger.error(error_message)
                raise ModelProviderError(message=error_message, model_name=self.name, model_id=self.id)
            # Define base client params
            base_params = {
                "api_key": self.api_key,
                "organization": self.organization,
                "base_url": self.base_url,
                "timeout": self.timeout,
                "max_retries": self.max_retries,
                "default_headers": self.default_headers,
                "default_query": self.default_query,
            }
            # Create client_params dict with non-None values
            client_params = {k: v for k, v in base_params.items() if v is not None}
            # Add additional client params if provided
            if self.client_params:
                client_params.update(self.client_params)
            return client_params