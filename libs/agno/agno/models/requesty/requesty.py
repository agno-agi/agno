from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput


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

    api_key: Optional[str] = None
    base_url: str = "https://router.requesty.ai/v1"
    max_tokens: int = 1024

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for REQUESTY_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        if not self.api_key:
            self.api_key = getenv("REQUESTY_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="REQUESTY_API_KEY not set. Please set the REQUESTY_API_KEY environment variable.",
                    model_name=self.name,
                )
        return super()._get_client_params()

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
    ) -> Dict[str, Any]:
        params = super().get_request_params(
            response_format=response_format, tools=tools, tool_choice=tool_choice, run_response=run_response
        )

        if "extra_body" not in params:
            params["extra_body"] = {}
        params["extra_body"]["requesty"] = {}
        if run_response and run_response.user_id:
            params["extra_body"]["requesty"]["user_id"] = run_response.user_id
        if run_response and run_response.session_id:
            params["extra_body"]["requesty"]["trace_id"] = run_response.session_id

        return params
