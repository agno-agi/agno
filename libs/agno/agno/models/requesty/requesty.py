from dataclasses import dataclass
from os import getenv
from typing import Optional, Dict, Any

from agno.models.openai.like import OpenAILike
from agno.run.agent import RunOutput


@dataclass
class Requesty(OpenAILike):
    """
    A class for using models hosted on Requesty.

    Attributes:
        id (str): The model id. Defaults to "openai/gpt-4.1".
        provider (str): The provider name. Defaults to "Requesty".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://router.requesty.ai/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
    """

    id: str = "openai/gpt-4.1"
    name: str = "Requesty"
    provider: str = "Requesty"

    api_key: Optional[str] = getenv("REQUESTY_API_KEY")
    base_url: str = "https://router.requesty.ai/v1"
    max_tokens: int = 1024

    def _enrich_request_params(
        self, request_params: Dict[str, Any], run_response: Optional[RunOutput] = None
    ) -> Dict[str, Any]:
        if not run_response:
            return request_params

        requesty_extra_body = {
            "requesty": {
                "user_id": run_response.user_id,
                "trace_id": run_response.session_id,
            }
        }

        request_params["extra_body"] = requesty_extra_body

        return request_params
