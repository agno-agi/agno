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
class Zhipu(OpenAILike):
    """
    A class for interacting with Zhipu AI models.

    Attributes:
        id (str): The model id. Defaults to "glm-4.7".
        name (str): The model name. Defaults to "Zhipu".
        provider (str): The provider name. Defaults to "Zhipu".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://open.bigmodel.cn/api/paas/v4".
        enable_thinking (bool): Enable thinking mode. Defaults to False.
    """

    id: str = "glm-4.7"
    name: str = "Zhipu"
    provider: str = "Zhipu"

    api_key: Optional[str] = field(default_factory=lambda: getenv("ZHIPU_API_KEY"))
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    enable_thinking: bool = False
    supports_native_structured_outputs: bool = False
    add_required_to_prompt: bool = True  # Add required arrays to nested objects in prompts

    def _get_client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            self.api_key = getenv("ZHIPU_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message="ZHIPU_API_KEY not set. Please set the ZHIPU_API_KEY environment variable.",
                    model_name=self.name,
                )

        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        client_params = {k: v for k, v in base_params.items() if v is not None}
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """Format message with reasoning_content support for thinking mode."""
        message_dict = super()._format_message(message, compress_tool_results)

        # Add reasoning_content if present (from thinking mode)
        if message.reasoning_content:
            message_dict["reasoning_content"] = message.reasoning_content
            message_dict = {k: v for k, v in message_dict.items() if v is not None}

        return message_dict

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[Union[RunOutput, TeamRunOutput]] = None,
    ) -> Dict[str, Any]:
        params = super().get_request_params(response_format, tools, tool_choice, run_response)

        if self.enable_thinking:
            params.setdefault("extra_body", {})["thinking"] = {"type": "enabled"}

        return params
