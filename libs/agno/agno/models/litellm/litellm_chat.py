import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union

import litellm
from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger


@dataclass
class LiteLLMSDK(Model):
    """
    A class for interacting with LiteLLM Python SDK.

    LiteLLM allows you to use a unified interface for various LLM providers.
    For more information, see: https://docs.litellm.ai/docs/

    Attributes:
        id (str): The id of the model to use. Default is "gpt-4o".
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
    request_params: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize the model after the dataclass initialization."""
        super().__post_init__()
        # Handle Huggingface models
        if self.id.startswith("huggingface/"):
            # Keep the full model name for LiteLLM routing
            self.model_name = self.id
            logger.info(
                f"Using Huggingface model via LiteLLM: {self.model_name}")
        else:
            self.model_name = self.id

        # Set up API key from environment variable if not already set
        if not self.api_key:
            self.api_key = getenv("LITELLM_API_KEY")
            if not self.api_key:
                logger.warning(
                    "LITELLM_API_KEY not set. Please set the LITELLM_API_KEY environment variable.")

    def to_dict(self) -> Dict[str, Any]:
        """Convert the model to a dictionary."""
        model_dict = {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "request_params": self.request_params,
        }
        # Add tools if present
        if self._tools is not None:
            model_dict["tools"] = self._tools
        # Remove None values
        return {k: v for k, v in model_dict.items() if v is not None}

    @staticmethod
    def parse_tool_calls(tool_calls_data: List[Any]) -> List[Dict[str, Any]]:
        """Build tool calls from streamed tool call data."""
        tool_calls: List[Dict[str, Any]] = []
        for tool_call in tool_calls_data:
            tool_call_entry = {
                "id": tool_call.id if hasattr(tool_call, 'id') else None,
                "type": "function",
                "function": {
                    "name": tool_call.function.name if hasattr(tool_call.function, 'name') else "",
                    "arguments": tool_call.function.arguments if hasattr(tool_call.function, 'arguments') else ""
                }
            }
            tool_calls.append(tool_call_entry)
        return tool_calls

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by LiteLLM.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        _message: Dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }

        # Handle images if present
        if message.role == "user" and message.images is not None and len(message.images) > 0:
            content_parts = []

            # Add text content if it exists
            if message.content:
                content_parts.append({"type": "text", "text": message.content})

            # Add image content
            for image in message.images:
                if image.url is not None:
                    content_parts.append(
                        {"type": "image_url", "image_url": {"url": image.url}})
                elif image.filepath is not None:
                    content_parts.append({"type": "image_url", "image_url": {
                                         "url": f"file://{image.filepath}"}})
                elif image.content is not None and isinstance(image.content, bytes):
                    import base64
                    base64_image = base64.b64encode(
                        image.content).decode("utf-8")
                    content_parts.append(
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"}}
                    )

            # Replace content with content parts
            if content_parts:
                _message["content"] = content_parts

        return _message

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """Returns keyword arguments for API requests."""
        base_params = {
            "model": self.model_name if hasattr(self, 'model_name') else self.id,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        
        # Use the correct model identifier based on provider
        if self.id.startswith("huggingface/"):
            # For Huggingface, we need to keep the "huggingface/" prefix
            # LiteLLM expects this format for provider routing
            base_params["model"] = self.id
        else:
            base_params["model"] = self.id

        # Add common parameters
        base_params["temperature"] = self.temperature

        # Handle top_p specially for Huggingface models
        if self.id.startswith("huggingface/"):
            # Ensure top_p is strictly less than 1.0 for Huggingface
            base_params["top_p"] = min(self.top_p, 0.99)
        else:
            base_params["top_p"] = self.top_p

        # Add optional parameters
        if self.max_tokens:
            base_params["max_tokens"] = self.max_tokens
        if self.api_key:
            base_params["api_key"] = self.api_key
        if self.api_base:
            base_params["api_base"] = self.api_base

        # Add tools with proper formatting for OpenAI-style APIs
        if self._tools is not None and len(self._tools) > 0:
            tools_list = []
            for tool in self._tools:
                if isinstance(tool, dict):
                    tool_dict = tool
                else:
                    # Assuming tool has a to_dict method that returns the function definition
                    tool_dict = {
                        "type": "function",
                        "function": {
                            "name": tool.name,  # Make sure the tool has a name attribute
                            "description": tool.description,  # And a description
                            "parameters": tool.parameters  # And parameters schema
                        }
                    }
                tools_list.append(tool_dict)

            base_params["tools"] = tools_list

            # Set tool_choice
            if hasattr(self, 'tool_choice') and self.tool_choice is not None:
                base_params["tool_choice"] = self.tool_choice
            else:
                # Default to "auto" when tools are present
                base_params["tool_choice"] = "auto"

        # Add additional request params
        if self.request_params:
            base_params.update(self.request_params)

        return base_params

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """Format a message for the LiteLLM API."""
        formatted = {
            "role": message.role,
            "content": message.content
        }

        # Handle tool calls in assistant messages
        if message.role == "assistant" and message.tool_calls:
            formatted["tool_calls"] = [{
                "id": tc.get("id", f"call_{i}"),
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"]
                }
            } for i, tc in enumerate(message.tool_calls)]

        # Handle tool responses in tool messages
        if message.role == "tool":
            formatted["tool_call_id"] = message.tool_call_id
            formatted["name"] = message.name

        return formatted

    def invoke(self, messages: List[Message]) -> Mapping[str, Any]:
        """
        Send a chat request to the LiteLLM API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Mapping[str, Any]: The response from the API.
        """
        formatted_messages = [self._format_message(m) for m in messages]

        # Prepare the completion parameters
        completion_kwargs = self.request_kwargs.copy()
        completion_kwargs["messages"] = formatted_messages

        # Log request details (without sensitive info)
        debug_kwargs = completion_kwargs.copy()
        if "api_key" in debug_kwargs:
            debug_kwargs["api_key"] = "***REDACTED***"
        logger.debug(f"LiteLLM request: {debug_kwargs}")

        # Call the LiteLLM completion API
        return litellm.completion(**completion_kwargs)

    async def ainvoke(self, messages: List[Message]) -> Mapping[str, Any]:
        """
        Sends an asynchronous chat request to the LiteLLM API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Mapping[str, Any]: The response from the API.
        """
        formatted_messages = [self._format_message(m) for m in messages]

        # Prepare the completion parameters
        completion_kwargs = self.request_kwargs.copy()
        completion_kwargs["messages"] = formatted_messages

        # Log request details (without sensitive info)
        debug_kwargs = completion_kwargs.copy()
        if "api_key" in debug_kwargs:
            debug_kwargs["api_key"] = "***REDACTED***"
        logger.debug(f"LiteLLM async request: {debug_kwargs}")

        # Call the LiteLLM async completion API
        return await litellm.acompletion(**completion_kwargs)

    def invoke_stream(self, messages: List[Message]) -> Iterator[Mapping[str, Any]]:
        """
        Sends a streaming chat request to the LiteLLM API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[Mapping[str, Any]]: An iterator of chunks from the API.
        """
        formatted_messages = [self._format_message(m) for m in messages]

        # Prepare the completion parameters
        completion_kwargs = self.request_kwargs.copy()
        completion_kwargs["messages"] = formatted_messages
        completion_kwargs["stream"] = True

        # Call the LiteLLM streaming completion API
        yield from litellm.completion(**completion_kwargs)

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Sends an asynchronous streaming chat completion request to the LiteLLM API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chunks from the API.
        """
        formatted_messages = [self._format_message(m) for m in messages]

        # Prepare the completion parameters
        completion_kwargs = self.request_kwargs.copy()
        completion_kwargs["messages"] = formatted_messages
        completion_kwargs["stream"] = True

        # Call the LiteLLM async streaming completion API
        async_stream = await litellm.acompletion(**completion_kwargs)
        async for chunk in async_stream:
            yield chunk

    def parse_provider_response(self, response: Any) -> ModelResponse:
        """Parse the provider response."""
        model_response = ModelResponse()

        # Get response message
        response_message = response.choices[0].message

        # Set role if available
        if hasattr(response_message, "role"):
            model_response.role = response_message.role

        # Set content if available
        if hasattr(response_message, "content") and response_message.content is not None:
            model_response.content = response_message.content

        # Handle tool calls
        if hasattr(response_message, "tool_calls") and response_message.tool_calls:
            model_response.tool_calls = self.parse_tool_calls(
                response_message.tool_calls)

        # Handle usage stats
        if hasattr(response, "usage"):
            model_response.response_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }

        # Parse structured outputs if enabled
        try:
            if (
                self.response_format is not None
                and self.structured_outputs
                and issubclass(self.response_format, BaseModel)
            ):
                parsed_object = response_message.content
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            logger.warning(f"Error retrieving structured outputs: {e}")

        model_response.raw = response
        return model_response

    def parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """
        Parse the provider response delta.

        Args:
            response_delta (Any): The response from the provider.

        Returns:
            ModelResponse: The model response delta.
        """
        model_response = ModelResponse()

        # Get delta message
        if hasattr(response_delta, "choices") and len(response_delta.choices) > 0:
            delta = response_delta.choices[0].delta

            # Handle content delta
            if hasattr(delta, "content") and delta.content is not None:
                model_response.content = delta.content

            # Handle tool calls delta
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                if model_response.tool_calls is None:
                    model_response.tool_calls = []

                for tool_call in delta.tool_calls:
                    if tool_call.type == "function":
                        function_def = {}

                        if hasattr(tool_call.function, "name") and tool_call.function.name:
                            function_def["name"] = tool_call.function.name

                        if hasattr(tool_call.function, "arguments") and tool_call.function.arguments:
                            function_def["arguments"] = tool_call.function.arguments

                        if function_def:
                            model_response.tool_calls.append({
                                "id": tool_call.id if hasattr(tool_call, 'id') else None,
                                "type": "function",
                                "function": function_def
                            })

        # Store the raw response
        model_response.raw = response_delta

        return model_response
