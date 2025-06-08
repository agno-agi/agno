from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error
from agno.utils.models.mistral import format_messages

try:
    from mistralai import CompletionEvent
    from mistralai import Mistral as MistralClient
    from mistralai.extra import response_format_from_pydantic_model
    from mistralai.extra.struct_chat import ParsedChatCompletionResponse
    from mistralai.models import (
        AssistantMessage,
        HTTPValidationError,
        SDKError,
        SystemMessage,
        ToolMessage,
        UserMessage,
    )
    from mistralai.models.chatcompletionresponse import ChatCompletionResponse
    from mistralai.models.deltamessage import DeltaMessage
    from mistralai.types.basemodel import Unset

    MistralMessage = Union[UserMessage, AssistantMessage, SystemMessage, ToolMessage]

except ImportError:
    raise ImportError("`mistralai` not installed. Please install using `pip install mistralai`")


@dataclass
class MistralChat(Model):
    """
    MistralChat is a model that uses the Mistral API to generate responses to messages.

    For more information, see the Mistral API documentation: https://docs.mistral.ai/capabilities/completion/
    """

    id: str = "mistral-large-latest"
    name: str = "MistralChat"
    provider: str = "Mistral"

    supports_native_structured_outputs: bool = True

    # -*- Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    random_seed: Optional[int] = None
    safe_mode: bool = False
    safe_prompt: bool = False
    request_params: Optional[Dict[str, Any]] = None
    # -*- Client parameters
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    max_retries: Optional[int] = None
    timeout: Optional[int] = None
    client_params: Optional[Dict[str, Any]] = None
    # -*- Provide the Mistral Client manually
    mistral_client: Optional[MistralClient] = None

    def get_client(self) -> MistralClient:
        """
        Get the Mistral client.

        Returns:
            MistralClient: The Mistral client instance.
        """
        if self.mistral_client:
            return self.mistral_client

        _client_params = self._get_client_params()
        self.mistral_client = MistralClient(**_client_params)
        return self.mistral_client

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Get the client parameters for initializing Mistral clients.

        Returns:
            Dict[str, Any]: The client parameters.
        """
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("MISTRAL_API_KEY")
        if not self.api_key:
            log_error("MISTRAL_API_KEY not set. Please set the MISTRAL_API_KEY environment variable.")

        client_params.update(
            {
                "api_key": self.api_key,
                "endpoint": self.endpoint,
                "max_retries": self.max_retries,
                "timeout": self.timeout,
            }
        )

        if self.client_params is not None:
            client_params.update(self.client_params)

        # Remove None values
        return {k: v for k, v in client_params.items() if v is not None}

    def get_request_kwargs(
        self, tools: Optional[List[Dict[str, Any]]] = None, tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Get the API kwargs for the Mistral model.

        Returns:
            Dict[str, Any]: The API kwargs.
        """
        _request_params: Dict[str, Any] = {}
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.random_seed:
            _request_params["random_seed"] = self.random_seed
        if self.safe_mode:
            _request_params["safe_mode"] = self.safe_mode
        if self.safe_prompt:
            _request_params["safe_prompt"] = self.safe_prompt
        if tools:
            _request_params["tools"] = tools
            if tool_choice is None:
                _request_params["tool_choice"] = "auto"
            else:
                _request_params["tool_choice"] = tool_choice
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        _dict = super().to_dict()
        _dict.update(
            {
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "random_seed": self.random_seed,
                "safe_mode": self.safe_mode,
                "safe_prompt": self.safe_prompt,
            }
        )
        cleaned_dict = {k: v for k, v in _dict.items() if v is not None}
        return cleaned_dict

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Union[ChatCompletionResponse, ParsedChatCompletionResponse]:
        """
        Send a chat completion request to the Mistral model.
        """
        mistral_messages = format_messages(messages)
        try:
            response: Union[ChatCompletionResponse, ParsedChatCompletionResponse]
            if (
                response_format is not None
                and isinstance(response_format, type)
                and issubclass(response_format, BaseModel)
            ):
                response = self.get_client().chat.complete(
                    model=self.id,
                    messages=mistral_messages,
                    response_format=response_format_from_pydantic_model(response_format),
                    **self.get_request_kwargs(tools=tools, tool_choice=tool_choice),
                )
            else:
                response = self.get_client().chat.complete(
                    model=self.id,
                    messages=mistral_messages,
                    **self.get_request_kwargs(tools=tools, tool_choice=tool_choice),
                )
            return response

        except HTTPValidationError as e:
            log_error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            log_error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Iterator[Any]:
        """
        Stream the response from the Mistral model.
        """
        mistral_messages = format_messages(messages)
        try:
            stream = self.get_client().chat.stream(
                model=self.id,
                messages=mistral_messages,
                **self.get_request_kwargs(tools=tools, tool_choice=tool_choice),
            )
            return stream
        except HTTPValidationError as e:
            log_error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            log_error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Union[ChatCompletionResponse, ParsedChatCompletionResponse]:
        """
        Send an asynchronous chat completion request to the Mistral API.
        """
        mistral_messages = format_messages(messages)
        try:
            response: Union[ChatCompletionResponse, ParsedChatCompletionResponse]
            if (
                response_format is not None
                and isinstance(response_format, type)
                and issubclass(response_format, BaseModel)
            ):
                response = await self.get_client().chat.complete_async(
                    model=self.id,
                    messages=mistral_messages,
                    response_format=response_format_from_pydantic_model(response_format),
                    **self.get_request_kwargs(tools=tools, tool_choice=tool_choice),
                )
            else:
                response = await self.get_client().chat.complete_async(
                    model=self.id,
                    messages=mistral_messages,
                    **self.get_request_kwargs(tools=tools, tool_choice=tool_choice),
                )
            return response
        except HTTPValidationError as e:
            log_error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            log_error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Any:
        """
        Stream an asynchronous response from the Mistral API.
        """
        mistral_messages = format_messages(messages)
        try:
            stream = await self.get_client().chat.stream_async(
                model=self.id,
                messages=mistral_messages,
                **self.get_request_kwargs(tools=tools, tool_choice=tool_choice),
            )
            if stream is None:
                raise ValueError("Chat stream returned None")
            async for chunk in stream:
                yield chunk
        except HTTPValidationError as e:
            log_error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            log_error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def parse_provider_response(self, response: ChatCompletionResponse, **kwargs) -> ModelResponse:
        """
        Parse the response from the Mistral model.

        Args:
            response (ChatCompletionResponse): The response from the model.
        """
        model_response = ModelResponse()
        if response.choices is not None and len(response.choices) > 0:
            response_message: AssistantMessage = response.choices[0].message

            # -*- Set content
            model_response.content = response_message.content  # type: ignore

            # -*- Set role
            model_response.role = response_message.role

            # -*- Set tool calls
            if isinstance(response_message.tool_calls, list) and len(response_message.tool_calls) > 0:
                model_response.tool_calls = []
                for tool_call in response_message.tool_calls:
                    model_response.tool_calls.append(
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": tool_call.function.model_dump(),
                        }
                    )

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(self, response_delta: CompletionEvent) -> Optional[ModelResponse]:
        """
        Parse the response delta from the Mistral model.
        """
        model_response = ModelResponse()

        delta_message: DeltaMessage = response_delta.data.choices[0].delta
        if delta_message.role is not None and not isinstance(delta_message.role, Unset):
            model_response.role = delta_message.role  # type: ignore

        if (
            delta_message.content is not None
            and not isinstance(delta_message.content, Unset)
            and isinstance(delta_message.content, str)
        ):
            model_response.content = delta_message.content

        if delta_message.tool_calls is not None:
            model_response.tool_calls = []
            for tool_call in delta_message.tool_calls:
                model_response.tool_calls.append(
                    {
                        "id": tool_call.id,  # type: ignore
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,  # type: ignore
                            "arguments": tool_call.function.arguments,  # type: ignore
                        },
                    }
                )

        if response_delta.data.usage is not None:
            model_response.response_usage = response_delta.data.usage

        return model_response
