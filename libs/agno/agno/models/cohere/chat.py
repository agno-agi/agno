from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Type, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.models.cohere import format_messages

try:
    from cohere import AsyncClientV2 as CohereAsyncClient
    from cohere import ClientV2 as CohereClient
    from cohere.v2.types.v2chat_response import V2ChatResponse
    from cohere.v2.types.v2chat_stream_response import V2ChatStreamResponse
except ImportError:
    raise ImportError("`cohere` not installed. Please install using `pip install cohere`")


@dataclass
class Cohere(Model):
    """
    A class representing the Cohere model.

    For more information, see: https://docs.cohere.com/docs/chat-api
    """

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
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
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

        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                _client_params["httpx_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                # Use global sync client when user http_client is invalid
                _client_params["httpx_client"] = get_default_sync_client()
        else:
            # Use global sync client when no custom http_client is provided
            _client_params["httpx_client"] = get_default_sync_client()

        self.client = CohereClient(**_client_params)
        return self.client  # type: ignore

    def get_async_client(self) -> CohereAsyncClient:
        if self.async_client:
            return self.async_client

        _client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("CO_API_KEY")

        if not self.api_key:
            raise ModelProviderError(
                message="CO_API_KEY not set. Please set the CO_API_KEY environment variable.",
                model_name=self.name,
                model_id=self.id,
            )

        _client_params["api_key"] = self.api_key

        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                _client_params["httpx_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                # Use global async client when user http_client is invalid
                _client_params["httpx_client"] = get_default_async_client()
        else:
            # Use global async client when no custom http_client is provided
            _client_params["httpx_client"] = get_default_async_client()
        self.async_client = CohereAsyncClient(**_client_params)
        return self.async_client  # type: ignore

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "top_k": self.top_k,
                "top_p": self.top_p,
                "seed": self.seed,
                "frequency_penalty": self.frequency_penalty,
                "presence_penalty": self.presence_penalty,
                "logprobs": self.logprobs,
                "strict_tools": self.strict_tools,
                "add_chat_history": self.add_chat_history,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
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

        if response_format:
            _request_params["response_format"] = response_format

        # Format tools
        if tools is not None and len(tools) > 0:
            formatted_tools = []
            for tool in tools:
                if tool.get("type") == "function" and "function" in tool:
                    # Extract only the fields that Cohere supports
                    filtered_tool = {
                        "type": "function",
                        "function": {
                            "name": tool["function"]["name"],
                            "description": tool["function"]["description"],
                            "parameters": tool["function"]["parameters"],
                        },
                    }
                    formatted_tools.append(filtered_tool)
                else:
                    # For non-function tools, pass them through as-is
                    formatted_tools.append(tool)

            _request_params["tools"] = formatted_tools
            # Fix optional parameters where the "type" is [type, null]
            for tool in _request_params["tools"]:  # type: ignore
                if "parameters" in tool["function"] and "properties" in tool["function"]["parameters"]:  # type: ignore
                    params = tool["function"]["parameters"]
                    # Cohere requires at least one required parameter, so if unset, set it to all parameters
                    if len(params.get("required", [])) == 0:
                        params["required"] = list(params["properties"].keys())
            _request_params["strict_tools"] = self.strict_tools

        if self.request_params:
            _request_params.update(self.request_params)

        if _request_params:
            log_debug(f"Calling {self.provider} with request parameters: {_request_params}", log_level=2)
        return _request_params

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Invoke a non-streamed chat response from the Cohere API.
        """
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools)

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()
            provider_response = self.get_client().chat(
                model=self.id,
                messages=format_messages(messages, compress_tool_results),  # type: ignore
                **request_kwargs,
            )  # type: ignore
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> Iterator[ModelResponse]:
        """
        Invoke a streamed chat response from the Cohere API.
        """
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools)

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            tool_use: Dict[str, Any] = {}

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()

            for response in self.get_client().chat_stream(
                model=self.id,
                messages=format_messages(messages, compress_tool_results),  # type: ignore
                **request_kwargs,
            ):
                model_response, tool_use = self._parse_provider_response_delta(response, tool_use=tool_use)
                yield model_response

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Asynchronously invoke a non-streamed chat response from the Cohere API.
        """
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools)

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()
            provider_response = await self.get_async_client().chat(
                model=self.id,
                messages=format_messages(messages, compress_tool_results),  # type: ignore
                **request_kwargs,
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """
        Asynchronously invoke a streamed chat response from the Cohere API.
        """
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools)

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            tool_use: Dict[str, Any] = {}

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()

            async for response in self.get_async_client().chat_stream(
                model=self.id,
                messages=format_messages(messages, compress_tool_results),  # type: ignore
                **request_kwargs,
            ):
                model_response, tool_use = self._parse_provider_response_delta(response, tool_use=tool_use)
                yield model_response

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Unexpected error calling Cohere API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def _parse_provider_response(self, response: V2ChatResponse, **kwargs) -> ModelResponse:
        """
        Parse the model provider response.

        Args:
            response (V2ChatResponse): The response from the Cohere API.
        """
        model_response = ModelResponse()

        model_response.role = response.message.role

        response_message = response.message
        if response_message.content is not None:
            full_content = ""
            for item in response_message.content:
                if hasattr(item, "text") and item.text is not None:  # type: ignore
                    full_content += item.text  # type: ignore
            model_response.content = full_content

        if response_message.tool_calls is not None:
            model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]

        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def _parse_provider_response_delta(
        self, response: V2ChatStreamResponse, tool_use: Dict[str, Any]
    ) -> Tuple[ModelResponse, Dict[str, Any]]:  # type: ignore
        """
        Parse the streaming response from the model provider into ModelResponse objects.

        Args:
            response: Raw response chunk from the model provider

        Returns:
            ModelResponse: Parsed response delta
        """
        model_response = ModelResponse()

        # 1. Add content
        if (
            response.type == "content-delta"
            and response.delta is not None
            and response.delta.message is not None
            and response.delta.message.content is not None
            and response.delta.message.content.text is not None
        ):
            model_response.content = response.delta.message.content.text

        # 2. Add tool calls information

        # 2.1 Add starting tool call
        elif response.type == "tool-call-start" and response.delta is not None:
            if response.delta.message is not None and response.delta.message.tool_calls is not None:
                tool_use = response.delta.message.tool_calls.model_dump()

        # 2.2 Add tool call delta
        elif response.type == "tool-call-delta" and response.delta is not None:
            if (
                response.delta.message is not None
                and response.delta.message.tool_calls is not None
                and response.delta.message.tool_calls.function is not None
                and response.delta.message.tool_calls.function.arguments is not None
            ):
                tool_use["function"]["arguments"] += response.delta.message.tool_calls.function.arguments

        # 2.3 Add ending tool call
        elif response.type == "tool-call-end":
            model_response.tool_calls = [tool_use]

        # 3. Add metrics
        elif (
            response.type == "message-end"
            and response.delta is not None
            and response.delta.usage is not None
            and response.delta.usage.tokens is not None
        ):
            model_response.response_usage = self._get_metrics(response.delta.usage)  # type: ignore

        return model_response, tool_use

    def _get_metrics(self, response_usage) -> MessageMetrics:
        """
        Parse the given Cohere usage into an Agno MessageMetrics object.

        Args:
            response_usage: Usage data from Cohere

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        metrics.input_tokens = response_usage.tokens.input_tokens or 0
        metrics.output_tokens = response_usage.tokens.output_tokens or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        return metrics
