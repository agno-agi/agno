from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.log import log_debug, log_error
from agno.utils.models.ai_foundry import format_message

try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.aio import ChatCompletionsClient as AsyncChatCompletionsClient
    from azure.ai.inference.models import (
        ChatCompletions,
        ChatCompletionsToolDefinition,
        FunctionDefinition,
        JsonSchemaFormat,
        StreamingChatCompletionsUpdate,
        StreamingChatResponseToolCallUpdate,
    )
    from azure.core.credentials import AzureKeyCredential
    from azure.core.exceptions import HttpResponseError
except ImportError:
    raise ImportError(
        "`azure-ai-inference` not installed. Please install it via `pip install azure-ai-inference aiohttp`."
    )


@dataclass
class AzureAIFoundry(Model):
    """
    A class for interacting with Azure AI Interface models.

    - For Managed Compute, set the `api_key` to your Azure AI Foundry API key and the `azure_endpoint` to the endpoint URL in the format `https://<your-host-name>.<your-azure-region>.models.ai.azure.com/models`
    - For Serverless API, set the `api_key` to your Azure AI Foundry API key and the `azure_endpoint` to the endpoint URL in the format `https://<your-host-name>.<your-azure-region>.models.ai.azure.com/models`
    - For Github Models, set the `api_key` to the Github Personal Access Token.
    - For Azure OpenAI, set the `api_key` to your Azure AI Foundry API key, the `api_version` to `2024-06-01` and the `azure_endpoint` to the endpoint URL in the format `https://<your-resource-name>.openai.azure.com/openai/deployments/<your-deployment-name>`

    For more information, see: https://learn.microsoft.com/en-gb/python/api/overview/azure/ai-inference-readme
    """

    id: str = "gpt-4o"
    name: str = "AzureAIFoundry"
    provider: str = "Azure"

    # Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    top_p: Optional[float] = None
    stop: Optional[Union[str, List[str]]] = None
    seed: Optional[int] = None
    model_extras: Optional[Dict[str, Any]] = None
    strict_output: bool = True  # When True, guarantees schema adherence for structured outputs. When False, attempts to follow schema as a guide but may occasionally deviate
    request_params: Optional[Dict[str, Any]] = None
    # Client parameters
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    azure_endpoint: Optional[str] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # Azure AI clients
    client: Optional[ChatCompletionsClient] = None
    async_client: Optional[AsyncChatCompletionsClient] = None

    def get_request_params(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Get the parameters for creating an Azure AI request."""
        base_params = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "top_p": self.top_p,
            "stop": self.stop,
            "seed": self.seed,
            "model": self.id,
            "model_extras": self.model_extras,
        }

        if tools:
            parsed_tools = []
            for _tool in tools:
                parsed_tools.append(
                    ChatCompletionsToolDefinition(
                        function=FunctionDefinition(
                            name=_tool["function"]["name"],
                            description=_tool["function"]["description"],
                            parameters=_tool["function"]["parameters"],
                        )
                    )
                )
            base_params["tools"] = parsed_tools  # type: ignore
            if tool_choice:
                base_params["tool_choice"] = tool_choice

        if response_format is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                base_params["response_format"] = (  # type: ignore
                    JsonSchemaFormat(
                        name=response_format.__name__,
                        schema=response_format.model_json_schema(),  # type: ignore
                        description=response_format.__doc__,
                        strict=self.strict_output,
                    ),
                )

        request_params = {k: v for k, v in base_params.items() if v is not None}
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
        return request_params

    def _get_client_params(self) -> Dict[str, Any]:
        """Get the parameters for creating an Azure AI client."""
        self.api_key = self.api_key or getenv("AZURE_API_KEY")
        self.api_version = self.api_version or getenv("AZURE_API_VERSION", "2024-05-01-preview")
        self.azure_endpoint = self.azure_endpoint or getenv("AZURE_ENDPOINT")

        if not self.api_key:
            log_error("AZURE_API_KEY not set. Please set the AZURE_API_KEY environment variable.")
        if not self.azure_endpoint:
            log_error("AZURE_ENDPOINT not set. Please set the AZURE_ENDPOINT environment variable.")

        base_params: Dict[str, Any] = {
            "endpoint": self.azure_endpoint,
            "api_version": self.api_version,
        }
        if self.api_key:
            base_params["credential"] = AzureKeyCredential(self.api_key)

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}
        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def get_client(self) -> ChatCompletionsClient:
        """
        Returns an Azure AI client.

        Returns:
            ChatCompletionsClient: An instance of the Azure AI client.
        """
        # Check if client exists and is not closed
        # Azure's client doesn't have is_closed(), so we check if _client exists
        if self.client and hasattr(self.client, "_client"):
            return self.client

        client_params = self._get_client_params()
        self.client = ChatCompletionsClient(**client_params)
        return self.client

    def get_async_client(self) -> AsyncChatCompletionsClient:
        """
        Returns an asynchronous Azure AI client.

        Returns:
            AsyncChatCompletionsClient: An instance of the asynchronous Azure AI client.
        """
        # Check if client exists and is not closed
        # Azure's async client doesn't have is_closed(), so we check if _client exists
        if self.async_client and hasattr(self.async_client, "_client"):
            return self.async_client

        client_params = self._get_client_params()

        self.async_client = AsyncChatCompletionsClient(**client_params)
        return self.async_client

    def close(self) -> None:
        """Close the synchronous client and clean up resources."""
        if self.client:
            self.client.close()
            self.client = None

    async def aclose(self) -> None:
        """Close the asynchronous client and clean up resources."""
        if self.async_client:
            await self.async_client.close()
            self.async_client = None

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
        Send a chat completion request to the Azure AI API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()
            provider_response = self.get_client().complete(
                messages=[format_message(m, compress_tool_results) for m in messages],
                **self.get_request_params(tools=tools, response_format=response_format, tool_choice=tool_choice),
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except HttpResponseError as e:
            log_error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from Azure AI API: {e}")
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
        Sends an asynchronous chat completion request to the Azure AI API.
        """

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()
            provider_response = await self.get_async_client().complete(
                messages=[format_message(m, compress_tool_results) for m in messages],
                **self.get_request_params(tools=tools, response_format=response_format, tool_choice=tool_choice),
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(provider_response, response_format=response_format)  # type: ignore

            return model_response

        except HttpResponseError as e:
            log_error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from Azure AI API: {e}")
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
        Send a streaming chat completion request to the Azure AI API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()

            for chunk in self.get_client().complete(
                messages=[format_message(m, compress_tool_results) for m in messages],
                stream=True,
                **self.get_request_params(tools=tools, response_format=response_format, tool_choice=tool_choice),
            ):
                yield self._parse_provider_response_delta(chunk)

            assistant_message.metrics.stop_timer()

        except HttpResponseError as e:
            log_error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from Azure AI API: {e}")
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
        Sends an asynchronous streaming chat completion request to the Azure AI API.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            assistant_message.metrics.start_timer()

            async_stream = await self.get_async_client().complete(
                messages=[format_message(m, compress_tool_results) for m in messages],
                stream=True,
                **self.get_request_params(tools=tools, response_format=response_format, tool_choice=tool_choice),
            )
            async for chunk in async_stream:  # type: ignore
                yield self._parse_provider_response_delta(chunk)

            assistant_message.metrics.stop_timer()

        except HttpResponseError as e:
            log_error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            log_error(f"Error from Azure AI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def _parse_provider_response(self, response: ChatCompletions, **kwargs) -> ModelResponse:
        """
        Parse the Azure AI response into a ModelResponse.

        Args:
            response: Raw response from Azure AI

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        try:
            # Get the first choice from the response
            choice = response.choices[0]

            # Add content
            if choice.message.content is not None:
                model_response.content = choice.message.content

            # Add role
            if choice.message.role is not None:
                model_response.role = choice.message.role

            # Add tool calls if present
            if choice.message.tool_calls and len(choice.message.tool_calls) > 0:
                model_response.tool_calls = [
                    {
                        "id": t.id,
                        "type": t.type,
                        "function": {
                            "name": t.function.name,
                            "arguments": t.function.arguments,
                        },
                    }
                    for t in choice.message.tool_calls
                ]

            # Add usage metrics if present
            if response.usage is not None:
                model_response.response_usage = self._get_metrics(response.usage)

        except Exception as e:
            log_error(f"Error parsing Azure AI response: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

        return model_response

    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[StreamingChatResponseToolCallUpdate]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data (List[StreamingChatResponseToolCallUpdate]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        tool_calls: List[Dict[str, Any]] = []

        current_tool_call: Dict[str, Any] = {}
        for tool_call in tool_calls_data:
            if tool_call.id:  # New tool call starts
                if current_tool_call:  # Store previous tool call if exists
                    tool_calls.append(current_tool_call)
                current_tool_call = {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments or ""},
                }
            elif current_tool_call and tool_call.function and tool_call.function.arguments:
                # Append arguments to current tool call
                current_tool_call["function"]["arguments"] += tool_call.function.arguments

        if current_tool_call:  # Append final tool call
            tool_calls.append(current_tool_call)

        return tool_calls

    def _parse_provider_response_delta(self, response_delta: StreamingChatCompletionsUpdate) -> ModelResponse:
        """
        Parse the Azure AI streaming response into ModelResponse objects.

        Args:
            response_delta: Raw response chunk from Azure AI

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        try:
            if response_delta.choices and len(response_delta.choices) > 0:
                choice_delta = response_delta.choices[0].delta

                if choice_delta:
                    # Add content
                    if choice_delta.content is not None:
                        model_response.content = choice_delta.content

                    # Add tool calls if present
                    if choice_delta.tool_calls and len(choice_delta.tool_calls) > 0:
                        model_response.tool_calls = choice_delta.tool_calls  # type: ignore
            # Add usage metrics if present
            if response_delta.usage is not None:
                model_response.response_usage = self._get_metrics(response_delta.usage)

        except Exception as e:
            log_error(f"Error parsing Azure AI response delta: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

        return model_response

    def _get_metrics(self, response_usage) -> MessageMetrics:
        """
        Parse the given Azure AI Foundry usage into an Agno MessageMetrics object.
        """
        metrics = MessageMetrics()

        metrics.input_tokens = response_usage.get("prompt_tokens", 0)
        metrics.output_tokens = response_usage.get("completion_tokens", 0)
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        if prompt_details := response_usage.get("prompt_tokens_details"):
            metrics.cache_read_tokens = prompt_details.get("cached_tokens", 0) or 0
        if completion_details := response_usage.get("completion_tokens_details"):
            metrics.reasoning_tokens = completion_details.get("reasoning_tokens", 0) or 0

        return metrics
