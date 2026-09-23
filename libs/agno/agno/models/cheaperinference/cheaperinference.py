from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike


@dataclass
class CheaperInference(OpenAILike):
    """
    A class for interacting with models served by Cheaper Inference, an OpenAI-compatible LLM gateway.

    Attributes:
        id (str): The model id. Defaults to "gpt-5.4-mini".
        name (str): The model name. Defaults to "CheaperInference".
        provider (str): The provider name. Defaults to "CheaperInference".
        api_key (Optional[str]): The API key. Defaults to the CHEAPER_INFERENCE_API_KEY environment variable.
        base_url (str): The base URL. Defaults to "https://api.cheaperinference.com/v1".
    """

    id: str = "gpt-5.4-mini"
    name: str = "CheaperInference"
    provider: str = "CheaperInference"

    api_key: Optional[str] = field(default_factory=lambda: getenv("CHEAPER_INFERENCE_API_KEY"))
    base_url: str = "https://api.cheaperinference.com/v1"

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("CHEAPER_INFERENCE_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="CHEAPER_INFERENCE_API_KEY not set. Please set the CHEAPER_INFERENCE_API_KEY environment variable.",
                    model_name=self.name,
                )

        return super()._get_client_params()
