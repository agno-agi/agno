from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.openai.like import OpenAILike
from agno.utils.log import log_debug


@dataclass
class xAI(OpenAILike):
    """
    Class for interacting with the xAI API.

    Attributes:
        id (str): The ID of the language model. Defaults to "grok-beta".
        name (str): The name of the API. Defaults to "xAI".
        provider (str): The provider of the API. Defaults to "xAI".
        api_key (Optional[str]): The API key for the xAI API.
        base_url (Optional[str]): The base URL for the xAI API. Defaults to "https://api.x.ai/v1".
        search_parameters (Optional[Dict[str, Any]]): Search parameters for enabling live search.
    """

    id: str = "grok-beta"
    name: str = "xAI"
    provider: str = "xAI"

    api_key: Optional[str] = getenv("XAI_API_KEY")
    base_url: str = "https://api.x.ai/v1"

    search_parameters: Optional[Dict[str, Any]] = None

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests, including search parameters.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        request_params = super().get_request_params(
            response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        if self.search_parameters:
            existing_body = request_params.get("extra_body") or {}
            existing_body.update({"search_parameters": self.search_parameters})
            request_params["extra_body"] = existing_body

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)

        return request_params
