import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union

import litellm

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

    # Additional parameters
    request_params: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """
            Initialize the model after the dataclass initialization.
            
            For Huggingface, we need to use the model name directly
            LiteLLM expects Huggingface models to be formatted as: "huggingface/mistralai/Mistral-7B-Instruct-v0.2"
            But internally it needs to use just "mistralai/Mistral-7B-Instruct-v0.2"
        """
        super().__post_init__()
        # Handle Huggingface models
        if self.id.startswith("huggingface/"):
            # Extract the actual model name without the "huggingface/" prefix
            self.model_name = self.id.replace("huggingface/", "")

            logger.info(f"Using Huggingface model: {self.model_name}")
        else:
            self.model_name = self.id
        
        # Set up API key from environment variable if not already set
        if not self.api_key:
            self.api_key = getenv("LITELLM_API_KEY")
            if not self.api_key:
                logger.warning(
                    "LITELLM_API_KEY not set. Please set the LITELLM_API_KEY environment variable."
                )

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The API kwargs for the model.
        """
        base_params: Dict[str, Any] = {}

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

        # Add optional parameters if they are set
        if self.max_tokens:
            base_params["max_tokens"] = self.max_tokens

        if self.api_key:
            base_params["api_key"] = self.api_key

        if self.api_base:
            base_params["api_base"] = self.api_base

        # Create request_kwargs dict with non-None values
        request_kwargs = {k: v for k,
                          v in base_params.items() if v is not None}

        # Add additional request params if provided
        if self.request_params:
            request_kwargs.update(self.request_params)

        # Debug log (without sensitive info)
        debug_kwargs = request_kwargs.copy()
        if "api_key" in debug_kwargs:
            debug_kwargs["api_key"] = "***REDACTED***"
        logger.debug(f"LiteLLM request parameters: {debug_kwargs}")

        return request_kwargs

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
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": image.url}
                    })
                elif image.filepath is not None:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"file://{image.filepath}"}
                    })
                elif image.content is not None and isinstance(image.content, bytes):
                    import base64
                    base64_image = base64.b64encode(
                        image.content).decode('utf-8')
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    })

            # Replace content with content parts
            if content_parts:
                _message["content"] = content_parts

        return _message

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
        """
        Parse the provider response.

        Args:
            response (Any): The response from the provider.

        Returns:
            ModelResponse: The model response.
        """
        model_response = ModelResponse()

        # Get response message
        response_message = response.choices[0].message

        if hasattr(response_message, "role"):
            model_response.role = response_message.role

        if hasattr(response_message, "content") and response_message.content is not None:
            model_response.content = response_message.content

        # Handle tool calls if present
        if hasattr(response_message, "tool_calls") and response_message.tool_calls:
            if model_response.tool_calls is None:
                model_response.tool_calls = []

            for tool_call in response_message.tool_calls:
                if tool_call.type == "function":
                    function_def = {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments,
                    }
                    model_response.tool_calls.append(
                        {"type": "function", "function": function_def})

        # Get response usage
        if hasattr(response, "usage"):
            model_response.response_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # Store the raw response
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
                            model_response.tool_calls.append(
                                {"type": "function", "function": function_def})

        # Store the raw response
        model_response.raw = response_delta

        return model_response
