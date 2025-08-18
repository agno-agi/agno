import json
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.agent import RunOutput
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import Metrics
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

    def get_request_params(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The API kwargs for the model.
        """
        base_params = {"format": self.format, "options": self.options, "keep_alive": self.keep_alive}
        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}
        # Add tools
        if tools is not None and len(tools) > 0:
            request_params["tools"] = tools

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
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

            if message.audio is not None and len(message.audio) > 0:
                log_warning("Audio input is currently unsupported.")

            if message.files is not None and len(message.files) > 0:
                log_warning("File input is currently unsupported.")

            if message.videos is not None and len(message.videos) > 0:
                log_warning("Video input is currently unsupported.")

        return _message

    def _prepare_request_kwargs_for_invoke(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        request_kwargs = self.get_request_params(tools=tools)
        if response_format is not None and isinstance(response_format, type) and issubclass(response_format, BaseModel):
            log_debug("Using structured outputs")
            format_schema = response_format.model_json_schema()
            if "format" not in request_kwargs:
                request_kwargs["format"] = format_schema
        return request_kwargs

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> ModelResponse:
        """
        Send a chat request to the Ollama API.
        """
        request_kwargs = self._prepare_request_kwargs_for_invoke(response_format=response_format, tools=tools)

        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        provider_response = self.get_client().chat(
            model=self.id.strip(),
            messages=[self._format_message(m) for m in messages],  # type: ignore
            **request_kwargs,
        )  # type: ignore

        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response)  # type: ignore
        return model_response

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> ModelResponse:
        """
        Sends an asynchronous chat request to the Ollama API.
        """
        request_kwargs = self._prepare_request_kwargs_for_invoke(response_format=response_format, tools=tools)

        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        provider_response = await self.get_async_client().chat(
            model=self.id.strip(),
            messages=[self._format_message(m) for m in messages],  # type: ignore
            **request_kwargs,
        )  # type: ignore

        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response)  # type: ignore
        return model_response

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Iterator[ModelResponse]:
        """
        Sends a streaming chat request to the Ollama API.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        for chunk in self.get_client().chat(
            model=self.id,
            messages=[self._format_message(m) for m in messages],  # type: ignore
            stream=True,
            **self.get_request_params(tools=tools),
        ):
            yield self._parse_provider_response_delta(chunk)

        assistant_message.metrics.stop_timer()

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> AsyncIterator[ModelResponse]:
        """
        Sends an asynchronous streaming chat completion request to the Ollama API.
        """
        if run_response and run_response.metrics:
            run_response.metrics.set_time_to_first_token()

        assistant_message.metrics.start_timer()

        async for chunk in await self.get_async_client().chat(
            model=self.id.strip(),
            messages=[self._format_message(m) for m in messages],  # type: ignore
            stream=True,
            **self.get_request_params(tools=tools),
        ):
            yield self._parse_provider_response_delta(chunk)

        assistant_message.metrics.stop_timer()

    def _parse_provider_response(self, response: dict) -> ModelResponse:
        """
        Parse the provider response.
        """
        model_response = ModelResponse()
        # Get response message
        response_message: OllamaMessage = response.get("message")  # type: ignore

        if response_message.get("role") is not None:
            model_response.role = response_message.get("role")

        if response_message.get("content") is not None:
            model_response.content = response_message.get("content")

        if response_message.get("tool_calls") is not None:
            if model_response.tool_calls is None:
                model_response.tool_calls = []
            for block in response_message.get("tool_calls", []):
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
            model_response.response_usage = self._get_metrics(response)

        return model_response

    def _parse_provider_response_delta(self, response: ChatResponse) -> ModelResponse:
        """
        Parse the provider response delta.

        Args:
            response (ChatResponse): The response from the provider.

        Returns:
            Iterator[ModelResponse]: An iterator of the model response.
        """
        model_response = ModelResponse()

        response_message = response.get("message")

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

        if response.get("done"):
            model_response.response_usage = self._get_metrics(response)

        return model_response

    def _get_metrics(self, response: Union[dict, ChatResponse]) -> Metrics:
        """
        Parse the given Ollama usage into an Agno Metrics object.

        Args:
            response: The response from the provider.

        Returns:
            Metrics: Parsed metrics data
        """
        metrics = Metrics()

        metrics.input_tokens = response.get("prompt_eval_count", 0)
        metrics.output_tokens = response.get("eval_count", 0)
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        return metrics
