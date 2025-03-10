from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Union

import litellm

from agno.models.base import Message, Model
from agno.models.base import ModelResponse as AgnoModelResponse
from agno.models.openai.like import OpenAILike
from agno.utils.log import logger


@dataclass
class LiteLLM(OpenAILike):
    """
    A class for interacting with LiteLLM Python SDK.

    LiteLLM allows you to use a unified interface for various LLM providers.
    For more information, see: https://docs.litellm.ai/docs/

    Attributes:
        id (str): The id of the model to use. Default is "gpt-3.5-turbo".
        name (str): The name of this model instance. Default is "LiteLLM".
        provider (str): The provider of the model. Default is "LiteLLM".
        api_key (str): The API key to authorize requests (if needed).
        api_base (str): The API base URL (if needed).
        max_tokens (int): Maximum number of tokens to generate.
        temperature (float): Controls randomness. Higher values mean more randomness.
        top_p (float): Controls diversity via nucleus sampling.
    """

    id: str = "gpt-4o"
    name: str = "LiteLLM"
    provider: str = "LiteLLM"

    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: float = 0.7
    top_p: float = 1.0

    def __post_init__(self):
        super().__post_init__()
        # Set up API key from environment variable if not already set
        if not self.api_key:
            self.api_key = getenv("LITELLM_API_KEY")
            if not self.api_key:
                logger.warning(
                    "LITELLM_API_KEY not set. Please set the LITELLM_API_KEY environment variable.")

    def _prepare_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        """Convert Agno messages to LiteLLM format."""
        return [{"role": msg.role, "content": msg.content} for msg in messages]

    def _prepare_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert Agno tools to LiteLLM format."""
        # LiteLLM uses the same format as OpenAI for tools
        return tools

    def _convert_response(self, response) -> AgnoModelResponse:
        """Convert LiteLLM response to Agno ModelResponse."""
        # Extract the relevant information from the LiteLLM response
        content = response.choices[0].message.content

        # Handle tool calls if present
        tool_calls = None
        if hasattr(response.choices[0].message, "tool_calls") and response.choices[0].message.tool_calls:
            tool_calls = response.choices[0].message.tool_calls

        return AgnoModelResponse(content=content, raw=response, tool_calls=tool_calls)

    def complete(
        self, messages: List[Message], tools: Optional[List[Dict[str, Any]]] = None, **kwargs
    ) -> AgnoModelResponse:
        """
        Complete a conversation with the model.

        Args:
            messages: List of messages in the conversation.
            tools: Optional list of tools to make available to the model.
            **kwargs: Additional arguments to pass to the model.

        Returns:
            ModelResponse: The model's response.
        """
        litellm_messages = self._prepare_messages(messages)

        # Prepare the completion parameters
        completion_kwargs = {
            "model": self.id,
            "messages": litellm_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        # Add optional parameters if they are set
        if self.max_tokens:
            completion_kwargs["max_tokens"] = self.max_tokens

        if self.api_key:
            completion_kwargs["api_key"] = self.api_key

        if self.api_base:
            completion_kwargs["api_base"] = self.api_base

        # Add tools if provided
        if tools:
            completion_kwargs["tools"] = self._prepare_tools(tools)

        # Add any additional kwargs
        completion_kwargs.update(kwargs)

        # Call the LiteLLM completion API
        response = litellm.completion(**completion_kwargs)

        return self._convert_response(response)

    async def acomplete(
        self, messages: List[Message], tools: Optional[List[Dict[str, Any]]] = None, **kwargs
    ) -> AgnoModelResponse:
        """
        Asynchronously complete a conversation with the model.

        Args:
            messages: List of messages in the conversation.
            tools: Optional list of tools to make available to the model.
            **kwargs: Additional arguments to pass to the model.

        Returns:
            ModelResponse: The model's response.
        """
        litellm_messages = self._prepare_messages(messages)

        # Prepare the completion parameters
        completion_kwargs = {
            "model": self.id,
            "messages": litellm_messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        # Add optional parameters if they are set
        if self.max_tokens:
            completion_kwargs["max_tokens"] = self.max_tokens

        if self.api_key:
            completion_kwargs["api_key"] = self.api_key

        if self.api_base:
            completion_kwargs["api_base"] = self.api_base

        # Add tools if provided
        if tools:
            completion_kwargs["tools"] = self._prepare_tools(tools)

        # Add any additional kwargs
        completion_kwargs.update(kwargs)

        # Call the LiteLLM async completion API
        response = await litellm.acompletion(**completion_kwargs)

        return self._convert_response(response)