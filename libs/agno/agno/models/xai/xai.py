from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.message import Citations, UrlCitation
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.utils.log import log_debug

try:
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.chat_completion_chunk import ChatCompletionChunk
except (ImportError, ModuleNotFoundError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


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

    def parse_provider_response(
        self,
        response: ChatCompletion,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        """
        Parse the xAI response into a ModelResponse.
        """
        model_response = super().parse_provider_response(response, response_format)

        if hasattr(response, "citations") and response.citations:
            citations = Citations()
            url_citations = []
            for citation_url in response.citations:
                url_citations.append(UrlCitation(url=str(citation_url)))

            citations.urls = url_citations
            citations.raw = response.citations
            model_response.citations = citations

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the xAI streaming response.

        Args:
            response_delta: Raw response chunk

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = super().parse_provider_response_delta(response_delta)

        if hasattr(response_delta, "citations") and response_delta.citations:
            citations = Citations()
            url_citations = []
            for citation_url in response_delta.citations:
                url_citations.append(UrlCitation(url=str(citation_url)))

            citations.urls = url_citations
            citations.raw = response_delta.citations
            model_response.citations = citations

        return model_response
