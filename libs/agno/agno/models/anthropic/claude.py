import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.exceptions import ModelProviderError
from agno.media import Image
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger

try:
    from anthropic import Anthropic as AnthropicClient
    from anthropic import APIConnectionError, APIStatusError, RateLimitError
    from anthropic import AsyncAnthropic as AsyncAnthropicClient
    from anthropic.types import (
        ContentBlockDeltaEvent,
        ContentBlockStopEvent,
        MessageDeltaEvent,
        MessageStopEvent,
        TextBlock,
        TextDelta,
        ToolUseBlock,
    )
    from anthropic.types import Message as AnthropicMessage
except (ModuleNotFoundError, ImportError):
    raise ImportError("`anthropic` not installed. Please install using `pip install anthropic`")

ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "user",
}


def _format_image_for_message(image: Image) -> Optional[Dict[str, Any]]:
    """
    Add an image to a message by converting it to base64 encoded format.
    """
    import base64
    import imghdr

    type_mapping = {"jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}

    try:
        # Case 1: Image is a URL
        if image.url is not None:
            content_bytes = image.image_url_content

        # Case 2: Image is a local file path
        elif image.filepath is not None:
            from pathlib import Path

            path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
            if path.exists() and path.is_file():
                with open(image.filepath, "rb") as f:
                    content_bytes = f.read()
            else:
                logger.error(f"Image file not found: {image}")
                return None

        # Case 3: Image is a bytes object
        elif image.content is not None:
            content_bytes = image.content

        else:
            logger.error(f"Unsupported image type: {type(image)}")
            return None

        img_type = imghdr.what(None, h=content_bytes)  # type: ignore
        if not img_type:
            logger.error("Unable to determine image type")
            return None

        media_type = type_mapping.get(img_type)
        if not media_type:
            logger.error(f"Unsupported image type: {img_type}")
            return None

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(content_bytes).decode("utf-8"),  # type: ignore
            },
        }

    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return None


def _format_messages(messages: List[Message]) -> Tuple[List[Dict[str, str]], str]:
    """
    Process the list of messages and separate them into API messages and system messages.

    Args:
        messages (List[Message]): The list of messages to process.

    Returns:
        Tuple[List[Dict[str, str]], str]: A tuple containing the list of API messages and the concatenated system messages.
    """
    chat_messages: List[Dict[str, str]] = []
    system_messages: List[str] = []

    for idx, message in enumerate(messages):
        content = message.content or ""
        if message.role == "system" or (message.role != "user" and idx in [0, 1]):
            if content is not None:
                system_messages.append(content)  # type: ignore
            continue
        elif message.role == "user":
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]

            if message.images is not None:
                for image in message.images:
                    image_content = _format_image_for_message(image)
                    if image_content:
                        content.append(image_content)

        # Handle tool calls from history
        elif message.role == "assistant":
            content = []
            if isinstance(message.content, str) and message.content:
                content.append(TextBlock(text=message.content, type="text"))
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    content.append(
                        ToolUseBlock(
                            id=tool_call["id"],
                            input=json.loads(tool_call["function"]["arguments"])
                            if "arguments" in tool_call["function"]
                            else {},
                            name=tool_call["function"]["name"],
                            type="tool_use",
                        )
                    )

        chat_messages.append({"role": ROLE_MAP[message.role], "content": content})  # type: ignore
    return chat_messages, " ".join(system_messages)


@dataclass
class Claude(Model):
    """
    A class representing Anthropic Claude model.

    For more information, see: https://docs.anthropic.com/en/api/messages
    """

    id: str = "claude-3-5-sonnet-20241022"
    name: str = "Claude"
    provider: str = "Anthropic"

    # Request parameters
    max_tokens: Optional[int] = 1024
    temperature: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None

    # Anthropic clients
    client: Optional[AnthropicClient] = None
    async_client: Optional[AsyncAnthropicClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.error("ANTHROPIC_API_KEY not set. Please set the ANTHROPIC_API_KEY environment variable.")

        client_params.update(
            {
                "api_key": self.api_key,
            }
        )
        if self.client_params is not None:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> AnthropicClient:
        """
        Returns an instance of the Anthropic client.
        """
        if self.client:
            return self.client

        _client_params = self._get_client_params()
        self.client = AnthropicClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAnthropicClient:
        """
        Returns an instance of the async Anthropic client.
        """
        if self.async_client:
            return self.async_client

        _client_params = self._get_client_params()
        self.async_client = AsyncAnthropicClient(**_client_params)
        return self.async_client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.
        """
        _request_params: Dict[str, Any] = {}
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def _prepare_request_kwargs(self, system_message: str) -> Dict[str, Any]:
        """
        Prepare the request keyword arguments for the API call.

        Args:
            system_message (str): The concatenated system messages.

        Returns:
            Dict[str, Any]: The request keyword arguments.
        """
        request_kwargs = self.request_kwargs.copy()
        request_kwargs["system"] = system_message

        if self._tools:
            request_kwargs["tools"] = self._format_tools_for_model()
        return request_kwargs

    def _format_tools_for_model(self) -> Optional[List[Dict[str, Any]]]:
        """
        Transforms function definitions into a format accepted by the Anthropic API.

        Returns:
            Optional[List[Dict[str, Any]]]: A list of tools formatted for the API, or None if no functions are defined.
        """
        if not self._functions:
            return None

        tools: List[Dict[str, Any]] = []
        for func_name, func_def in self._functions.items():
            parameters: Dict[str, Any] = func_def.parameters or {}
            properties: Dict[str, Any] = parameters.get("properties", {})
            required_params: List[str] = []

            for param_name, param_info in properties.items():
                param_type = param_info.get("type", "")
                param_type_list: List[str] = [param_type] if isinstance(param_type, str) else param_type or []

                if "null" not in param_type_list:
                    required_params.append(param_name)

            input_properties: Dict[str, Dict[str, Union[str, List[str]]]] = {
                param_name: {
                    "type": param_info.get("type", ""),
                    "description": param_info.get("description", ""),
                }
                for param_name, param_info in properties.items()
            }

            tool = {
                "name": func_name,
                "description": func_def.description or "",
                "input_schema": {
                    "type": parameters.get("type", "object"),
                    "properties": input_properties,
                    "required": required_params,
                },
            }
            tools.append(tool)
        return tools

    def invoke(self, messages: List[Message]) -> AnthropicMessage:
        """
        Send a request to the Anthropic API to generate a response.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AnthropicMessage: The response from the model.

        Raises:
            APIConnectionError: If there are network connectivity issues
            RateLimitError: If the API rate limit is exceeded
            APIStatusError: For other API-related errors
        """
        try:
            chat_messages, system_message = _format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message)

            return self.get_client().messages.create(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            )
        except APIConnectionError as e:
            logger.error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Any:
        """
        Stream a response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.
        """
        chat_messages, system_message = _format_messages(messages)
        request_kwargs = self._prepare_request_kwargs(system_message)

        try:
            return (
                self.get_client()
                .messages.stream(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                )
                .__enter__()
            )
        except APIConnectionError as e:
            logger.error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e

    async def ainvoke(self, messages: List[Message]) -> AnthropicMessage:
        """
        Send an asynchronous request to the Anthropic API to generate a response.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AnthropicMessage: The response from the model.

        Raises:
            APIConnectionError: If there are network connectivity issues
            RateLimitError: If the API rate limit is exceeded
            APIStatusError: For other API-related errors
        """
        try:
            chat_messages, system_message = _format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message)

            return await self.get_async_client().messages.create(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            )
        except APIConnectionError as e:
            logger.error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[Any]:
        """
        Stream an asynchronous response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.
        """
        try:
            chat_messages, system_message = _format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message)
            async with self.get_async_client().messages.stream(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except APIConnectionError as e:
            logger.error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except RateLimitError as e:
            logger.warning(f"Rate limit exceeded: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except APIStatusError as e:
            logger.error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e
        except Exception as e:
            logger.error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(e, self.name, self.id) from e

    # Overwrite the default from the base model
    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], tool_ids: List[str]
    ) -> None:
        """
        Handle the results of function calls.

        Args:
            messages (List[Message]): The list of conversation messages.
            function_call_results (List[Message]): The results of the function calls.
            tool_ids (List[str]): The tool ids.
        """
        if len(function_call_results) > 0:
            fc_responses: List = []
            for _fc_message_index, _fc_message in enumerate(function_call_results):
                fc_responses.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_ids[_fc_message_index],
                        "content": _fc_message.content,
                    }
                )
            messages.append(Message(role="user", content=fc_responses))

    # Overwrite the default from the base model
    def get_system_message_for_model(self) -> Optional[str]:
        if self._functions is not None and len(self._functions) > 0:
            tool_call_prompt = "Do not reflect on the quality of the returned search results in your response"
            return tool_call_prompt
        return None

    def parse_provider_response(self, response: AnthropicMessage) -> ModelResponse:
        """
        Parse the Claude response into a ModelResponse.

        Args:
            response: Raw response from Anthropic

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Add role (Claude always uses 'assistant')
        model_response.role = response.role or "assistant"

        if response.content:
            first_block = response.content[0]
            if isinstance(first_block, TextBlock):
                model_response.content = first_block.text
            elif isinstance(first_block, ToolUseBlock):
                tool_name = first_block.name
                tool_input = first_block.input

                if tool_input and isinstance(tool_input, dict):
                    model_response.content = tool_input.get("query", "")

        # -*- Extract tool calls from the response
        if response.stop_reason == "tool_use":
            for block in response.content:
                if isinstance(block, ToolUseBlock):
                    tool_name = block.name
                    tool_input = block.input

                    function_def = {"name": tool_name}
                    if tool_input:
                        function_def["arguments"] = json.dumps(tool_input)

                    model_response.extra = model_response.extra or {}
                    model_response.extra.setdefault("tool_ids", []).append(block.id)
                    model_response.tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": function_def,
                        }
                    )

        # Add usage metrics
        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(
        self, response: Union[ContentBlockDeltaEvent, ContentBlockStopEvent, MessageDeltaEvent]
    ) -> ModelResponse:
        """
        Parse the Claude streaming response into ModelProviderResponse objects.

        Args:
            response: Raw response chunk from Anthropic

        Returns:
            ModelResponse: Iterator of parsed response data
        """
        model_response = ModelResponse()

        if isinstance(response, ContentBlockDeltaEvent):
            # Handle text content
            if isinstance(response.delta, TextDelta):
                model_response.content = response.delta.text

        elif isinstance(response, ContentBlockStopEvent):
            # Handle tool calls
            if isinstance(response.content_block, ToolUseBlock):  # type: ignore
                tool_use = response.content_block  # type: ignore
                tool_name = tool_use.name
                tool_input = tool_use.input

                function_def = {"name": tool_name}
                if tool_input:
                    function_def["arguments"] = json.dumps(tool_input)

                model_response.extra = model_response.extra or {}
                model_response.extra.setdefault("tool_ids", []).append(tool_use.id)

                model_response.tool_calls = [
                    {
                        "id": tool_use.id,
                        "type": "function",
                        "function": function_def,
                    }
                ]

        # Handle message completion and usage metrics
        elif isinstance(response, MessageStopEvent):
            if response.message.usage is not None:
                model_response.response_usage = response.message.usage

        return model_response
