from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class AtlasCloud(OpenAILike):
    """Chat with Atlas Cloud using its OpenAI-compatible API.

    Use a model ID from the Atlas Cloud catalog, including its organization
    prefix. Credentials come from api_key or ATLASCLOUD_API_KEY.
    """

    id: str = "deepseek-ai/deepseek-v3.2"
    name: str = "AtlasCloud"
    provider: str = "AtlasCloud"
    api_key: Optional[str] = None
    base_url: str = "https://api.atlascloud.ai/v1"
    # Retrying a generation can submit and bill a second request.
    max_retries: Optional[int] = 0

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("ATLASCLOUD_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="ATLASCLOUD_API_KEY not set. Please set the ATLASCLOUD_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()
