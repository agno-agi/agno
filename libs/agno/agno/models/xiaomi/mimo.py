from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput


@dataclass
class MiMo(OpenAILike):
    """
    A class for interacting with Xiaomi MiMo models.

    Attributes:
        id (str): The model id. Defaults to "mimo-v2.5-pro".
        name (str): The model name. Defaults to "MiMo".
        provider (str): The provider name. Defaults to "Xiaomi MiMo".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.xiaomimimo.com/v1".
        thinking (Optional[Dict[str, Any]]): MiMo thinking configuration, e.g. {"type": "enabled"}.
    """

    id: str = "mimo-v2.5-pro"
    name: str = "MiMo"
    provider: str = "Xiaomi MiMo"

    api_key: Optional[str] = field(default_factory=lambda: getenv("MIMO_API_KEY"))
    base_url: str = "https://api.xiaomimimo.com/v1"

    thinking: Optional[Dict[str, Any]] = None

    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("MIMO_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="MIMO_API_KEY not set. Please set the MIMO_API_KEY environment variable.",
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
        request_params = super().get_request_params(
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )

        if self.thinking is not None:
            extra_body = dict(request_params.get("extra_body") or {})
            extra_body["thinking"] = self.thinking
            request_params["extra_body"] = extra_body

        return request_params

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        message_dict = super()._format_message(message, compress_tool_results)

        if message.reasoning_content is not None:
            message_dict["reasoning_content"] = message.reasoning_content

        return message_dict

    def to_dict(self) -> Dict[str, Any]:
        model_dict = super().to_dict()
        model_dict.update({"thinking": self.thinking})
        return {k: v for k, v in model_dict.items() if v is not None}
