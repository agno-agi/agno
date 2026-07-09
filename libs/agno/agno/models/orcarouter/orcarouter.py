from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput


@dataclass
class OrcaRouter(OpenAILike):
    """
    A class for using models hosted on OrcaRouter.

    OrcaRouter (https://www.orcarouter.ai) is an OpenAI-compatible model router. Set the
    ``id`` to any model in the OrcaRouter catalog (https://www.orcarouter.ai/models), e.g.
    ``openai/gpt-4o-mini``, ``anthropic/claude-opus-4.8``, or the virtual router
    ``orcarouter/auto`` which selects an upstream per request based on your console routing
    policy (https://www.orcarouter.ai/console/routing).

    Attributes:
        id (str): The model id. Defaults to "openai/gpt-4o-mini".
        name (str): The model name. Defaults to "OrcaRouter".
        provider (str): The provider name. Defaults to "OrcaRouter".
        api_key (Optional[str]): The API key (OrcaRouter keys start with ``sk-orca-``).
        base_url (str): The base URL. Defaults to "https://api.orcarouter.ai/v1".
        max_tokens (int): The maximum number of tokens. Defaults to 1024.
        models (Optional[List[str]]): Ordered list of fallback model IDs. When the primary
            model fails (rate limit, timeout, unavailability) OrcaRouter tries these in order.
            Sent as ``extra_body={"models": [...], "route": "fallback"}``.
            Example: ["anthropic/claude-opus-4.8", "openai/gpt-4o"].
    """

    id: str = "openai/gpt-4o-mini"
    name: str = "OrcaRouter"
    provider: str = "OrcaRouter"

    api_key: Optional[str] = None
    base_url: str = "https://api.orcarouter.ai/v1"
    max_tokens: int = 1024
    models: Optional[List[str]] = None  # Fallback routing https://docs.orcarouter.ai

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters for API requests, checking for ORCAROUTER_API_KEY.

        Returns:
            Dict[str, Any]: A dictionary of client parameters for API requests.
        """
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("ORCAROUTER_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="ORCAROUTER_API_KEY not set. Please set the ORCAROUTER_API_KEY environment variable.",
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
        """
        Returns keyword arguments for API requests, including fallback models configuration.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Get base request params from parent class
        request_params = super().get_request_params(
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )

        # Add fallback models to extra_body if specified
        if self.models:
            # Get existing extra_body or create new dict
            extra_body = request_params.get("extra_body") or {}

            # Merge fallback routing into extra_body
            extra_body["models"] = self.models
            extra_body["route"] = "fallback"

            # Update request params
            request_params["extra_body"] = extra_body

        return request_params
