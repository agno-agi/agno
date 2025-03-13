from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

from agno.exceptions import ModelProviderError
from agno.media import Image
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger

try:
    from mistralai import CompletionEvent
    from mistralai import Mistral as MistralClient
    from mistralai.extra.struct_chat import ParsedChatCompletionResponse
    from mistralai.models import (
        AssistantMessage,
        HTTPValidationError,
        ImageURLChunk,
        SDKError,
        SystemMessage,
        TextChunk,
        ToolMessage,
        UserMessage,
    )
    from mistralai.models.chatcompletionresponse import ChatCompletionResponse
    from mistralai.models.deltamessage import DeltaMessage
    from mistralai.types.basemodel import Unset

    MistralMessage = Union[UserMessage, AssistantMessage, SystemMessage, ToolMessage]

except (ModuleNotFoundError, ImportError):
    raise ImportError("`mistralai` not installed. Please install using `pip install mistralai`")


def _format_image_for_message(image: Image) -> Optional[ImageURLChunk]:
    # Case 1: Image is a URL
    if image.url is not None:
        return ImageURLChunk(image_url=image.url)
    # Case 2: Image is a local file path
    elif image.filepath is not None:
        import base64
        from pathlib import Path

        path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
        if not path.exists() or not path.is_file():
            logger.error(f"Image file not found: {image}")
            raise FileNotFoundError(f"Image file not found: {image}")

        with open(image.filepath, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
            return ImageURLChunk(image_url=f"data:image/jpeg;base64,{base64_image}")

    # Case 3: Image is a bytes object
    elif image.content is not None:
        import base64

        base64_image = base64.b64encode(image.content).decode("utf-8")
        return ImageURLChunk(image_url=f"data:image/jpeg;base64,{base64_image}")
    return None


def _format_messages(messages: List[Message]) -> List[MistralMessage]:
    mistral_messages: List[MistralMessage] = []

    for message in messages:
        mistral_message: MistralMessage
        if message.role == "user":
            if message.images is not None:
                content: List[Any] = [TextChunk(type="text", text=message.content)]
                for image in message.images:
                    image_content = _format_image_for_message(image)
                    if image_content:
                        content.append(image_content)
                mistral_message = UserMessage(role="user", content=content)
            else:
                mistral_message = UserMessage(role="user", content=message.content)
        elif message.role == "assistant":
            if message.reasoning_content is not None:
                message.role = "user"
                mistral_message = UserMessage(role="user", content=message.content)
            elif message.tool_calls is not None:
                mistral_message = AssistantMessage(
                    role="assistant", content=message.content, tool_calls=message.tool_calls
                )
            else:
                mistral_message = AssistantMessage(role=message.role, content=message.content)
        elif message.role == "system":
            mistral_message = SystemMessage(role="system", content=message.content)
        elif message.role == "tool":
            mistral_message = ToolMessage(name="tool", content=message.content, tool_call_id=message.tool_call_id)
        else:
            raise ValueError(f"Unknown role: {message.role}")

        mistral_messages.append(mistral_message)
    return mistral_messages


@dataclass
class MistralChat(Model):
    """
    MistralChat is a model that uses the Mistral API to generate responses to messages.

    Args:
        id (str): The ID of the model.
        name (str): The name of the model.
        provider (str): The provider of the model.
        temperature (Optional[float]): The temperature of the model.
        max_tokens (Optional[int]): The maximum number of tokens to generate.
        top_p (Optional[float]): The top p of the model.
        random_seed (Optional[int]): The random seed of the model.
        safe_mode (bool): The safe mode of the model.
        safe_prompt (bool): The safe prompt of the model.
        response_format (Optional[Union[Dict[str, Any], ChatCompletionResponse]]): The response format of the model.
        request_params (Optional[Dict[str, Any]]): The request parameters of the model.
        api_key (Optional[str]): The API key of the model.
        endpoint (Optional[str]): The endpoint of the model.
        max_retries (Optional[int]): The maximum number of retries of the model.
        timeout (Optional[int]): The timeout of the model.
        client_params (Optional[Dict[str, Any]]): The client parameters of the model.
        mistral_client (Optional[Mistral]): The Mistral client of the model.
    """

    id: str = "mistral-large-latest"
    name: str = "MistralChat"
    provider: str = "Mistral"

    supports_structured_outputs: bool = True

    # -*- Request parameters
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    random_seed: Optional[int] = None
    safe_mode: bool = False
    safe_prompt: bool = False
    response_format: Optional[Union[Dict[str, Any], ChatCompletionResponse]] = None
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
            logger.error("MISTRAL_API_KEY not set. Please set the MISTRAL_API_KEY environment variable.")

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

    @property
    def request_kwargs(self) -> Dict[str, Any]:
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
        if self._tools:
            _request_params["tools"] = self._tools
            if self.tool_choice is None:
                _request_params["tool_choice"] = "auto"
            else:
                _request_params["tool_choice"] = self.tool_choice
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
                "response_format": self.response_format,
            }
        )
        cleaned_dict = {k: v for k, v in _dict.items() if v is not None}
        return cleaned_dict

    def invoke(self, messages: List[Message]) -> Union[ChatCompletionResponse, ParsedChatCompletionResponse]:
        """
        Send a chat completion request to the Mistral model.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            ChatCompletionResponse: The response from the model.
        """
        mistral_messages = _format_messages(messages)
        try:
            response: Union[ChatCompletionResponse, ParsedChatCompletionResponse]
            if self.response_format is not None and self.structured_outputs:
                response = self.get_client().chat.parse(
                    model=self.id,
                    messages=mistral_messages,
                    response_format=self.response_format,  # type: ignore
                    **self.request_kwargs,
                )
            else:
                response = self.get_client().chat.complete(
                    model=self.id,
                    messages=mistral_messages,
                    **self.request_kwargs,
                )
            return response

        except HTTPValidationError as e:
            logger.error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            logger.error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[Any]:
        """
        Stream the response from the Mistral model.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            Iterator[Any]: The streamed response.
        """
        mistral_messages = _format_messages(messages)
        try:
            stream = self.get_client().chat.stream(
                model=self.id,
                messages=mistral_messages,
                **self.request_kwargs,
            )
            return stream
        except HTTPValidationError as e:
            logger.error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            logger.error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(self, messages: List[Message]) -> Union[ChatCompletionResponse, ParsedChatCompletionResponse]:
        """
        Send an asynchronous chat completion request to the Mistral API.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            ChatCompletionResponse: The response from the model.
        """
        mistral_messages = _format_messages(messages)
        try:
            response: Union[ChatCompletionResponse, ParsedChatCompletionResponse]
            if self.response_format is not None and self.structured_outputs:
                response = await self.get_client().chat.parse_async(
                    model=self.id,
                    messages=mistral_messages,
                    response_format=self.response_format,  # type: ignore
                    **self.request_kwargs,
                )
            else:
                response = await self.get_client().chat.complete_async(
                    model=self.id,
                    messages=mistral_messages,
                    **self.request_kwargs,
                )
            return response
        except HTTPValidationError as e:
            logger.error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            logger.error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> Any:
        """
        Stream an asynchronous response from the Mistral API.

        Args:
            messages (List[Message]): The messages to send to the model.

        Returns:
            Any: The streamed response.
        """
        mistral_messages = _format_messages(messages)
        try:
            stream = await self.get_client().chat.stream_async(
                model=self.id,
                messages=mistral_messages,
                **self.request_kwargs,
            )
            if stream is None:
                raise ValueError("Chat stream returned None")
            async for chunk in stream:
                yield chunk
        except HTTPValidationError as e:
            logger.error(f"HTTPValidationError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except SDKError as e:
            logger.error(f"SDKError from Mistral: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def parse_provider_response(self, response: ChatCompletionResponse) -> ModelResponse:
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
