import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional

from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.tools.function import FunctionCall
from agno.utils.log import logger
from agno.utils.tools import get_function_call_for_tool_call

try:
    from openai.types.chat.chat_completion_chunk import (
        ChoiceDelta,
        ChoiceDeltaToolCall,
    )
    from openai.types.completion_usage import CompletionUsage
except ImportError:
    logger.error("`openai` not installed")
    raise


@dataclass
class Together(OpenAILike):
    """
    A class for interacting with Together models.

    Attributes:
        id (str): The id of the Together model to use. Default is "mistralai/Mixtral-8x7B-Instruct-v0.1".
        name (str): The name of this chat model instance. Default is "Together"
        provider (str): The provider of the model. Default is "Together".
        api_key (str): The api key to authorize request to Together.
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "mistralai/Mixtral-8x7B-Instruct-v0.1"
    name: str = "Together"
    provider: str = "Together " + id
    api_key: Optional[str] = getenv("TOGETHER_API_KEY")
    base_url: str = "https://api.together.xyz/v1"
    

    def parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """
        Parse the streaming response from Together into a ModelResponse.

        Args:
            response: Raw response chunk from Together API

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        if response_delta.choices and len(response_delta.choices) > 0:
            delta = response_delta.choices[0].delta
            # Add content if present
            if delta.content is not None:
                model_response.content = delta.content

            # Add tool calls if present
            if delta.tool_calls is not None:
                model_response.tool_calls = delta.tool_calls

            # Add role if present 
            if delta.role is not None:
                model_response.role = delta.role

        # Add usage metrics if present
        if response_delta.usage is not None:
            model_response.response_usage = response_delta.usage

        return model_response
