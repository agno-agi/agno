from dataclasses import dataclass
from os import getenv
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence, Tuple

from agno.exceptions import ModelProviderError
from agno.media import Image
from agno.models.base import MessageData, Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning

try:
    from cohere import AsyncClientV2 as CohereAsyncClient
    from cohere import ClientV2 as CohereClient
    from cohere.types.chat_response import ChatResponse
    from cohere.types.streamed_chat_response_v2 import StreamedChatResponseV2
except (ModuleNotFoundError, ImportError):
    raise ImportError("`cohere` not installed. Please install using `pip install cohere`")


def _format_images_for_message(message: Message, images: Sequence[Image]) -> List[Dict[str, Any]]:
    """
    Format an image into the format expected by WatsonX.
    """

    # Create a default message content with text
    message_content_with_image: List[Dict[str, Any]] = [{"type": "text", "text": message.content}]

    # Add images to the message content
    for image in images:
        try:
            if image.content is not None:
                image_content = image.content
            elif image.url is not None:
                image_content = image.image_url_content
            elif image.filepath is not None:
                if isinstance(image.filepath, Path):
                    image_content = image.filepath.read_bytes()
                else:
                    with open(image.filepath, "rb") as f:
                        image_content = f.read()
            else:
                log_warning(f"Unsupported image format: {image}")
                continue

            if image_content is not None:
                import base64

                base64_image = base64.b64encode(image_content).decode("utf-8")
                image_url = f"data:image/jpeg;base64,{base64_image}"
                image_payload = {"type": "image_url", "image_url": {"url": image_url}}
                message_content_with_image.append(image_payload)

        except Exception as e:
            log_error(f"Failed to process image: {str(e)}")

    # Update the message content with the images
    return message_content_with_image


def _format_messages(messages: List[Message]) -> List[Dict[str, Any]]:
    """
    Format messages for the Cohere API.

    Args:
        messages (List[Message]): The list of messages.

    Returns:
        List[Dict[str, Any]]: The formatted messages.
    """
    formatted_messages = []
    for message in messages:
        message_dict = {
            "role": message.role,
            "content": message.content,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
        }

        if message.images is not None and len(message.images) > 0:
            # Ignore non-string message content
            if isinstance(message.content, str):
                message_content_with_image = _format_images_for_message(message=message, images=message.images)
                if len(message_content_with_image) > 1:
                    message_dict["content"] = message_content_with_image

        message_dict = {k: v for k, v in message_dict.items() if v is not None}
        formatted_messages.append(message_dict)
    return formatted_messages


@dataclass
class Cohere(Model):
    id: str = "command-r-plus"
    name: str = "cohere"
    provider: str = "Cohere"

    # -*- Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    seed: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    logprobs: Optional[bool] = None
    request_params: Optional[Dict[str, Any]] = None
    strict_tools: bool = False
    # Add chat history to the cohere messages instead of using the conversation_id
    add_chat_history: bool = False
    # -*- Client parameters
    api_key: Optional[str] = None
    client_params: Optional[Dict[str, Any]] = None
    # -*- Provide the Cohere client manually
    client: Optional[CohereClient] = None
    async_client: Optional[CohereAsyncClient] = None

    def get_client(self) -> CohereClient:
        if self.client:
            return self.client

        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("CO_API_KEY")
        if not self.api_key:
            log_error("CO_API_KEY not set. Please set the CO_API_KEY environment variable.")

        _client_params["api_key"] = self.api_key

        self.client = CohereClient(**_client_params)
        return self.client  # type: ignore

    def get_async_client(self) -> CohereAsyncClient:
        if self.async_client:
            return self.async_client

        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("CO_API_KEY")

        if not self.api_key:
            log_error("CO_API_KEY not set. Please set the CO_API_KEY environment variable.")

        _client_params["api_key"] = self.api_key

        self.async_client = CohereAsyncClient(**_client_params)
        return self.async_client  # type: ignore

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        _request_params: Dict[str, Any] = {}
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.top_k:
            _request_params["k"] = self.top_k
        if self.top_p:
            _request_params["p"] = self.top_p
        if self.seed:
            _request_params["seed"] = self.seed
        if self.logprobs:
            _request_params["logprobs"] = self.logprobs
        if self.frequency_penalty:
            _request_params["frequency_penalty"] = self.frequency_penalty
        if self.presence_penalty:
            _request_params["presence_penalty"] = self.presence_penalty

        if self.response_format:
            _request_params["response_format"] = self.response_format

        if self._tools is not None and len(self._tools) > 0:
            _request_params["tools"] = self._tools
            # Fix optional parameters where the "type" is [type, null]
            for tool in _request_params["tools"]:  # type: ignore
                params = []
                if "parameters" in tool["function"] and "properties" in tool["function"]["parameters"]:  # type: ignore
                    for param_name, obj in tool["function"]["parameters"].get("properties", {}).items():  # type: ignore
                        params.append(param_name)
                        if isinstance(obj["type"], list):
                            obj["type"] = obj["type"][0]

                    # Cohere requires at least one required parameter, so if unset, set it to all parameters
                    if len(tool["function"]["parameters"].get("required", [])) == 0:
                        tool["function"]["parameters"]["required"] = params
            _request_params["strict_tools"] = self.strict_tools

        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def invoke(self, messages: List[Message]) -> ChatResponse:
        """
        Invoke a non-streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.

        Returns:
            ChatResponse: The chat response.
        """

        request_kwargs = self.request_kwargs

        try:
            return self.get_client().chat(model=self.id, messages=_format_messages(messages), **request_kwargs)  # type: ignore
        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[StreamedChatResponseV2]:
        """
        Invoke a streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.

        Returns:
            Iterator[StreamedChatResponseV2]: An iterator of streamed chat responses.
        """
        request_kwargs = self.request_kwargs

        try:
            return self.get_client().chat_stream(
                model=self.id,
                messages=_format_messages(messages),  # type: ignore
                **request_kwargs,
            )
        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(self, messages: List[Message]) -> ChatResponse:
        """
        Asynchronously invoke a non-streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.

        Returns:
            ChatResponse: The chat response.
        """
        request_kwargs = self.request_kwargs

        try:
            return await self.get_async_client().chat(
                model=self.id,
                messages=_format_messages(messages),  # type: ignore
                **request_kwargs,
            )
        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[StreamedChatResponseV2]:
        """
        Asynchronously invoke a streamed chat response from the Cohere API.

        Args:
            messages (List[Message]): The list of messages.

        Returns:
            AsyncIterator[StreamedChatResponseV2]: An async iterator of streamed chat responses.
        """
        request_kwargs = self.request_kwargs

        try:
            async for response in self.get_async_client().chat_stream(
                model=self.id,
                messages=_format_messages(messages),  # type: ignore
                **request_kwargs,
            ):
                yield response
        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def parse_provider_response(self, response: ChatResponse) -> ModelResponse:
        """
        Parse the model provider response.

        Args:
            response (ChatResponse): The response from the Cohere API.
        """
        model_response = ModelResponse()

        model_response.role = response.message.role

        response_message = response.message
        if response_message.content is not None:
            full_content = ""
            for item in response_message.content:
                full_content += item.text
            model_response.content = full_content

        if response_message.tool_calls is not None:
            model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]

        if response.usage is not None and response.usage.tokens is not None:
            model_response.response_usage = {
                "input_tokens": int(response.usage.tokens.input_tokens) or 0,  # type: ignore
                "output_tokens": int(response.usage.tokens.output_tokens) or 0,  # type: ignore
                "total_tokens": int(response.usage.tokens.input_tokens + response.usage.tokens.output_tokens) or 0,  # type: ignore
            }

        return model_response

    def _process_stream_response(
        self,
        response: StreamedChatResponseV2,
        assistant_message: Message,
        stream_data: MessageData,
        tool_use: Dict[str, Any],
    ) -> Tuple[Optional[ModelResponse], Dict[str, Any]]:
        """
        Common handler for processing stream responses from Cohere.

        Args:
            response: The streamed response from Cohere
            assistant_message: The assistant message being built
            stream_data: Data accumulated during streaming
            tool_use: Current tool use data being built

        Returns:
            Tuple containing the ModelResponse to yield and updated tool_use dict
        """
        model_response = None

        if (
            response.type == "content-delta"
            and response.delta is not None
            and response.delta.message is not None
            and response.delta.message.content is not None
        ):
            # Update metrics
            assistant_message.metrics.completion_tokens += 1
            if not assistant_message.metrics.time_to_first_token:
                assistant_message.metrics.set_time_to_first_token()

            # Update provider response content
            stream_data.response_content += response.delta.message.content.text
            model_response = ModelResponse(content=response.delta.message.content.text)

        elif response.type == "tool-call-start" and response.delta is not None:
            if response.delta.message is not None and response.delta.message.tool_calls is not None:
                tool_use = response.delta.message.tool_calls.model_dump()

        elif response.type == "tool-call-delta" and response.delta is not None:
            if (
                response.delta.message is not None
                and response.delta.message.tool_calls is not None
                and response.delta.message.tool_calls.function is not None
            ):
                tool_use["function"]["arguments"] += response.delta.message.tool_calls.function.arguments

        elif response.type == "tool-call-end":
            if assistant_message.tool_calls is None:
                assistant_message.tool_calls = []
            assistant_message.tool_calls.append(tool_use)
            tool_use = {}

        elif (
            response.type == "message-end"
            and response.delta is not None
            and response.delta.usage is not None
            and response.delta.usage.tokens is not None
        ):
            self._add_usage_metrics_to_assistant_message(
                assistant_message=assistant_message,
                response_usage={
                    "input_tokens": int(response.delta.usage.tokens.input_tokens) or 0,  # type: ignore
                    "output_tokens": int(response.delta.usage.tokens.output_tokens) or 0,  # type: ignore
                    "total_tokens": int(
                        response.delta.usage.tokens.input_tokens + response.delta.usage.tokens.output_tokens  # type: ignore
                    )
                    or 0,
                },
            )

        return model_response, tool_use

    def process_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data: MessageData
    ) -> Iterator[ModelResponse]:
        """Process the synchronous response stream."""
        tool_use: Dict[str, Any] = {}

        for response in self.invoke_stream(messages=messages):
            model_response, tool_use = self._process_stream_response(
                response=response, assistant_message=assistant_message, stream_data=stream_data, tool_use=tool_use
            )
            if model_response is not None:
                yield model_response

    async def aprocess_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data: MessageData
    ) -> AsyncIterator[ModelResponse]:
        """Process the asynchronous response stream."""
        tool_use: Dict[str, Any] = {}

        async for response in self.ainvoke_stream(messages=messages):
            model_response, tool_use = self._process_stream_response(
                response=response, assistant_message=assistant_message, stream_data=stream_data, tool_use=tool_use
            )
            if model_response is not None:
                yield model_response

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:  # type: ignore
        pass
