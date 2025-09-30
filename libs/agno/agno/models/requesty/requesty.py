from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

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

    api_key: Optional[str] = field(default_factory=lambda: getenv("REQUESTY_API_KEY"))
    base_url: str = "https://router.requesty.ai/v1"
    max_tokens: int = 1024

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Dict[str, Any]:
        params = super().get_request_params(response_format=response_format, tools=tools, tool_choice=tool_choice)

        if "extra_body" not in params:
            params["extra_body"] = {}
        params["extra_body"]["requesty"] = {}
        if run_response and run_response.user_id:
            params["extra_body"]["requesty"]["user_id"] = run_response.user_id
        if run_response and run_response.session_id:
            params["extra_body"]["requesty"]["trace_id"] = run_response.session_id

        return params
