import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.models.openai.like import OpenAILike


@dataclass
class CerebrasOpenAI(OpenAILike):
    id: str = "llama-4-scout-17b-16e-instruct"
    name: str = "CerebrasOpenAI"
    provider: str = "CerebrasOpenAI"

    parallel_tool_calls: bool = False
    base_url: str = "https://api.cerebras.ai/v1"
    api_key: Optional[str] = getenv("CEREBRAS_API_KEY", None)

    def get_request_kwargs(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Get base request kwargs from the parent class
        request_params = super().get_request_kwargs(
            response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        # Add tools with proper formatting
        if tools is not None and len(tools) > 0:
            request_params["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["function"]["name"],
                        "strict": True,  # Ensure strict adherence to expected outputs
                        "description": tool["function"]["description"],
                        "parameters": tool["function"]["parameters"],
                    },
                }
                for tool in tools
            ]
            # Cerebras requires parallel_tool_calls=False for llama-4-scout-17b-16e-instruct
            request_params["parallel_tool_calls"] = self.parallel_tool_calls

        return request_params

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by the Cerebras API.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        # Basic message content
        message_dict: Dict[str, Any] = {
            "role": message.role,
            "content": message.content if message.content is not None else "",
        }

        # Add name if present
        if message.name:
            message_dict["name"] = message.name

        # Handle tool calls
        if message.tool_calls:
            # Ensure tool_calls is properly formatted
            message_dict["tool_calls"] = [
                {
                    "id": tool_call["id"],
                    "type": tool_call["type"],
                    "function": {
                        "name": tool_call["function"]["name"],
                        "arguments": json.dumps(tool_call["function"]["arguments"])
                        if isinstance(tool_call["function"]["arguments"], (dict, list))
                        else tool_call["function"]["arguments"],
                    },
                }
                for tool_call in message.tool_calls
            ]

        # Handle tool responses
        if message.role == "tool" and message.tool_call_id:
            message_dict = {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content if message.content is not None else "",
            }

        # Ensure no None values in the message
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        return message_dict
