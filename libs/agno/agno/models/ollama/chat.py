import json
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union

from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_debug, log_warning

try:
    from ollama import AsyncClient as AsyncOllamaClient
    from ollama import Client as OllamaClient
    from ollama._types import ChatResponse
    from ollama._types import Message as OllamaMessage
except ImportError:
    raise ImportError("`ollama` not installed. Please install using `pip install ollama`")


@dataclass
class OllamaResponseUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_duration: int = 0
    load_duration: int = 0
    prompt_eval_duration: int = 0
    eval_duration: int = 0


@dataclass
class Ollama(Model):
    """
    A class for interacting with Ollama models.

    For more information, see: https://github.com/ollama/ollama/blob/main/docs/api.md
    """

    id: str = "llama3.1"
    name: str = "Ollama"
    provider: str = "Ollama"

    supports_native_structured_outputs: bool = True

    # Request parameters
    format: Optional[Any] = None
    options: Optional[Any] = None
    keep_alive: Optional[Union[float, str]] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    host: Optional[str] = None
    timeout: Optional[Any] = None
    client_params: Optional[Dict[str, Any]] = None

    # Ollama clients
    client: Optional[OllamaClient] = None
    async_client: Optional[AsyncOllamaClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        base_params = {
            "host": self.host,
            "timeout": self.timeout,
        }
        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}
        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)
        return client_params

    def get_client(self) -> OllamaClient:
        """
        Returns an Ollama client.

        Returns:
            OllamaClient: An instance of the Ollama client.
        """
        if self.client is not None:
            return self.client

        self.client = OllamaClient(**self._get_client_params())
        return self.client

    def get_async_client(self) -> AsyncOllamaClient:
        """
        Returns an asynchronous Ollama client.

        Returns:
            AsyncOllamaClient: An instance of the Ollama client.
        """
        if self.async_client is not None:
            return self.async_client

        return AsyncOllamaClient(**self._get_client_params())

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The API kwargs for the model.
        """
        base_params = {
            "format": self.format,
            "options": self.options,
            "keep_alive": self.keep_alive,
            "request_params": self.request_params,
        }
        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}
        # Add tools
        if self._tools is not None and len(self._tools) > 0:
            request_params["tools"] = self._tools
            # Fix optional parameters where the "type" is [type, null]
            for tool in request_params["tools"]:  # type: ignore
                if "parameters" in tool["function"] and "properties" in tool["function"]["parameters"]:  # type: ignore
                    for _, obj in tool["function"]["parameters"].get("properties", {}).items():  # type: ignore
                        if "type" in obj and isinstance(obj["type"], list) and len(obj["type"]) > 1:
                            obj["type"] = obj["type"][0]

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: A dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "format": self.format,
                "options": self.options,
                "keep_alive": self.keep_alive,
                "request_params": self.request_params,
            }
        )
        if self._tools is not None:
            model_dict["tools"] = self._tools
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by Ollama.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        _message: Dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.role == "user":
            if message.images is not None:
                message_images = []
                for image in message.images:
                    if image.url is not None:
                        message_images.append(image.image_url_content)
                    if image.filepath is not None:
                        message_images.append(image.filepath)  # type: ignore
                    if image.content is not None and isinstance(image.content, bytes):
                        message_images.append(image.content)
                if message_images:
                    _message["images"] = message_images
        return _message

    def _prepare_request_kwargs_for_invoke(self) -> Dict[str, Any]:
        request_kwargs = self.request_kwargs
        if self.response_format is not None and self.structured_outputs:
            if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                log_debug("Using structured outputs")
                format_schema = self.response_format.model_json_schema()
                if "format" not in request_kwargs:
                    request_kwargs["format"] = format_schema
        return request_kwargs

    def invoke(self, messages: List[Message]) -> Mapping[str, Any]:
        """
        Send a chat request to the Ollama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Mapping[str, Any]: The response from the API.
        """
        request_kwargs = self._prepare_request_kwargs_for_invoke()

        return self.get_client().chat(
            model=self.id.strip(),
            messages=[self._format_message(m) for m in messages],  # type: ignore
            **request_kwargs,
        )  # type: ignore

    async def ainvoke(self, messages: List[Message]) -> Mapping[str, Any]:
        """
        Sends an asynchronous chat request to the Ollama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Mapping[str, Any]: The response from the API.
        """
        request_kwargs = self._prepare_request_kwargs_for_invoke()

        return await self.get_async_client().chat(
            model=self.id.strip(),
            messages=[self._format_message(m) for m in messages],  # type: ignore
            **request_kwargs,
        )  # type: ignore

    def invoke_stream(self, messages: List[Message]) -> Iterator[Mapping[str, Any]]:
        """
        Sends a streaming chat request to the Ollama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[Mapping[str, Any]]: An iterator of chunks from the API.
        """
        yield from self.get_client().chat(
            model=self.id,
            messages=[self._format_message(m) for m in messages],  # type: ignore
            stream=True,
            **self.request_kwargs,
        )  # type: ignore

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Sends an asynchronous streaming chat completion request to the Ollama API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chunks from the API.
        """
        async_stream = await self.get_async_client().chat(
            model=self.id.strip(),
            messages=[self._format_message(m) for m in messages],  # type: ignore
            stream=True,
            **self.request_kwargs,
        )
        async for chunk in async_stream:  # type: ignore
            yield chunk

    def parse_provider_response(self, response: ChatResponse) -> ModelResponse:
        """
        Parse the provider response.

        Args:
            response (ChatResponse): The response from the provider.

        Returns:
            ModelResponse: The model response.
        """
        model_response = ModelResponse()
        # Get response message
        response_message: OllamaMessage = response.get("message")

        # Parse structured outputs if enabled
        try:
            if (
                self.response_format is not None
                and self.structured_outputs
                and issubclass(self.response_format, BaseModel)
            ):
                parsed_object = response_message.content  # type: ignore
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            log_warning(f"Error retrieving structured outputs: {e}")

        if response_message.get("role") is not None:
            model_response.role = response_message.get("role")

        if response_message.get("content") is not None:
            model_response.content = response_message.get("content")

        if response_message.get("tool_calls") is not None:
            if model_response.tool_calls is None:
                model_response.tool_calls = []
            for block in response_message.get("tool_calls"):
                tool_call = block.get("function")
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("arguments")

                function_def = {
                    "name": tool_name,
                    "arguments": (json.dumps(tool_args) if tool_args is not None else None),
                }
                model_response.tool_calls.append({"type": "function", "function": function_def})

        # if response_message.get("images") is not None:
        #     model_response.images = response_message.get("images")

        # Get response usage
        if response.get("done"):
            model_response.response_usage = {
                "input_tokens": response.get("prompt_eval_count", 0),
                "output_tokens": response.get("eval_count", 0),
                "total_tokens": response.get("prompt_eval_count", 0) + response.get("eval_count", 0),
                "additional_metrics": {
                    "total_duration": response.get("total_duration", 0),
                    "load_duration": response.get("load_duration", 0),
                    "prompt_eval_duration": response.get("prompt_eval_duration", 0),
                    "eval_duration": response.get("eval_duration", 0),
                },
            }

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatResponse) -> ModelResponse:
        """
        Parse the provider response delta.

        Args:
            response_delta (ChatResponse): The response from the provider.

        Returns:
            Iterator[ModelResponse]: An iterator of the model response.
        """
        model_response = ModelResponse()

        response_message = response_delta.get("message")

        if response_message is not None:
            content_delta = response_message.get("content")
            if content_delta is not None and content_delta != "":
                model_response.content = content_delta

            tool_calls = response_message.get("tool_calls")
            if tool_calls is not None:
                for tool_call in tool_calls:
                    tc = tool_call.get("function")
                    tool_name = tc.get("name")
                    tool_args = tc.get("arguments")
                    function_def = {
                        "name": tool_name,
                        "arguments": json.dumps(tool_args) if tool_args is not None else None,
                    }
                    model_response.tool_calls.append({"type": "function", "function": function_def})

        if response_delta.get("done"):
            model_response.response_usage = {
                "input_tokens": response_delta.get("prompt_eval_count", 0),
                "output_tokens": response_delta.get("eval_count", 0),
                "total_tokens": response_delta.get("prompt_eval_count", 0) + response_delta.get("eval_count", 0),
                "additional_metrics": {
                    "total_duration": response_delta.get("total_duration", 0),
                    "load_duration": response_delta.get("load_duration", 0),
                    "prompt_eval_duration": response_delta.get("prompt_eval_duration", 0),
                    "eval_duration": response_delta.get("eval_duration", 0),
                },
            }

        return model_response
