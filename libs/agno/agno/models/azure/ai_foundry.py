from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx
from anthropic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger
from agno.utils.openai import images_to_message

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


def _format_message(message: Message) -> Dict[str, Any]:
    """
    Format a message into the format expected by OpenAI.

    Args:
        message (Message): The message to format.

    Returns:
        Dict[str, Any]: The formatted message.
    """
    message_dict: Dict[str, Any] = {
        "role": message.role,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": message.tool_calls,
    }
    message_dict = {k: v for k, v in message_dict.items() if v is not None}

    if message.images is not None and len(message.images) > 0:
        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if isinstance(message.content, str):
            message_dict["content"] = [{"type": "text", "text": message.content}]
            message_dict["content"].extend(images_to_message(images=message.images))

    if message.audio is not None:
        logger.warning("Audio input is currently unsupported.")

    if message.videos is not None:
        logger.warning("Video input is currently unsupported.")

    return message_dict


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

    # Internal parameters
    structured_outputs: bool = False

    def _get_request_kwargs(self) -> Dict[str, Any]:
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

        if self._tools:
            tools = []
            for _tool in self._tools:
                tools.append(
                    ChatCompletionsToolDefinition(
                        function=FunctionDefinition(
                            name=_tool["function"]["name"],
                            description=_tool["function"]["description"],
                            parameters=_tool["function"]["parameters"],
                        )
                    )
                )
            base_params["tools"] = tools  # type: ignore
            if self.tool_choice:
                base_params["tool_choice"] = self.tool_choice

        if self.response_format is not None and self.structured_outputs:
            if isinstance(self.response_format, type) and issubclass(self.response_format, BaseModel):
                base_params["response_format"] = (  # type: ignore
                    JsonSchemaFormat(
                        name=self.response_format.__name__,
                        schema=self.response_format.model_json_schema(),  # type: ignore
                        description=self.response_format.__doc__,
                        strict=True,
                    ),
                )
            else:
                raise ValueError("response_format must be a subclass of BaseModel if structured_outputs=True")

        request_params = {k: v for k, v in base_params.items() if v is not None}
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def _get_client_params(self) -> Dict[str, Any]:
        """Get the parameters for creating an Azure AI client."""
        self.api_key = self.api_key or getenv("AZURE_API_KEY")
        self.api_version = self.api_version or getenv("AZURE_API_VERSION", "2024-05-01-preview")
        self.azure_endpoint = self.azure_endpoint or getenv("AZURE_ENDPOINT")

        if not self.api_key:
            raise ValueError("API key is required")
        if not self.azure_endpoint:
            raise ValueError("Endpoint URL is required")

        base_params = {
            "endpoint": self.azure_endpoint,
            "credential": AzureKeyCredential(self.api_key),
            "api_version": self.api_version,
        }

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
        if self.client:
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
        client_params = self._get_client_params()

        self.async_client = AsyncChatCompletionsClient(**client_params)
        return self.async_client

    def invoke(self, messages: List[Message]) -> Any:
        """
        Send a chat completion request to the Azure AI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The chat completion response from the API.
        """
        try:
            return self.get_client().complete(
                messages=[_format_message(m) for m in messages], **self._get_request_kwargs()
            )
        except HttpResponseError as e:
            logger.error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from Azure AI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(self, messages: List[Message]) -> Any:
        """
        Sends an asynchronous chat completion request to the Azure AI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The chat completion response from the API.
        """

        try:
            async with self.get_async_client() as client:
                return await client.complete(
                    messages=[_format_message(m) for m in messages],
                    **self._get_request_kwargs(),
                )
        except HttpResponseError as e:
            logger.error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from Azure AI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[Any]:
        """
        Send a streaming chat completion request to the Azure AI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[Any]: An iterator of chat completion chunks.
        """
        try:
            yield from self.get_client().complete(
                messages=[_format_message(m) for m in messages], stream=True, **self._get_request_kwargs()
            )
        except HttpResponseError as e:
            logger.error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from Azure AI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[Any]:
        """
        Sends an asynchronous streaming chat completion request to the Azure AI API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AsyncIterator[Any]: An asynchronous iterator of chat completion chunks.
        """
        try:
            async with self.get_async_client() as client:
                stream = await client.complete(
                    messages=[_format_message(m) for m in messages],
                    stream=True,
                    **self._get_request_kwargs(),
                )
                async for chunk in stream:  # type: ignore
                    yield chunk

        except HttpResponseError as e:
            logger.error(f"Azure AI API error: {e}")
            raise ModelProviderError(
                message=e.reason or "Azure AI API error",
                status_code=e.status_code or 502,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from Azure AI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def parse_provider_response(self, response: ChatCompletions) -> ModelResponse:
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
                model_response.response_usage = {
                    "input_tokens": response.usage.prompt_tokens or 0,
                    "output_tokens": response.usage.completion_tokens or 0,
                    "total_tokens": response.usage.total_tokens or 0,
                }

        except Exception as e:
            logger.error(f"Error parsing Azure AI response: {e}")
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

    def parse_provider_response_delta(self, response_delta: StreamingChatCompletionsUpdate) -> ModelResponse:
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
                delta = response_delta.choices[0].delta

                # Add content
                if delta.content is not None:
                    model_response.content = delta.content

                # Add tool calls if present
                if delta.tool_calls and len(delta.tool_calls) > 0:
                    model_response.tool_calls = delta.tool_calls  # type: ignore
            # Add usage metrics if present
            if response_delta.usage is not None:
                model_response.response_usage = {
                    "input_tokens": response_delta.usage.prompt_tokens or 0,
                    "output_tokens": response_delta.usage.completion_tokens or 0,
                    "total_tokens": response_delta.usage.total_tokens or 0,
                }

        except Exception as e:
            logger.error(f"Error parsing Azure AI response delta: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

        return model_response
