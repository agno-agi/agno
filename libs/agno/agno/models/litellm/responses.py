import copy
from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.models.openai import OpenResponses
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.log import log_debug, log_error, log_warning

try:
    import litellm
    from litellm import validate_environment
except ImportError:
    raise ImportError("`litellm` not installed. Please install it via `pip install litellm`")


@dataclass
class LiteLLMResponses(OpenResponses):
    """
    A class for interacting with LiteLLM Python SDK, using the Responses API

    LiteLLM allows you to use a unified interface for various LLM providers.
    For more information, see: https://docs.litellm.ai/docs/
    """

    id: str = "gpt-4o"
    name: str = "LiteLLM"
    provider: str = "LiteLLM"

    client: Optional[Any] = None

    # Store the original client to preserve it across copies (e.g., for Router instances)
    _original_client: Optional[Any] = None

    # Remove non-standard fields like `requires_confirmation` by default
    def _supports_internal_tool_fields(self) -> bool:
        return False

    def __post_init__(self):
        """Initialize the model after the dataclass initialization."""
        super().__post_init__()

        # Store the original client if provided (e.g., Router instance)
        # This ensures the client is preserved when the model is copied for background tasks
        if self.client is not None and self._original_client is None:
            self._original_client = self.client

        # Set up API key from environment variable if not already set
        if not self.client and not self.api_key:
            self.api_key = getenv("LITELLM_API_KEY")
            if not self.api_key:
                # Check for other present valid keys, e.g. OPENAI_API_KEY if self.id is an OpenAI model
                env_validation = validate_environment(model=self.id, api_base=self.api_base)
                if not env_validation.get("keys_in_environment"):
                    log_error(
                        "LITELLM_API_KEY not set. Please set the LITELLM_API_KEY or other valid environment variables."
                    )

    def get_client(self) -> Any:
        """
        Returns a LiteLLM client.

        Returns:
            Any: An instance of the LiteLLM client.
        """
        # First check if we have a current client
        if self.client is not None:
            return self.client

        # Check if we have an original client (e.g., Router) that was preserved
        # This handles the case where the model was copied for background tasks
        if self._original_client is not None:
            self.client = self._original_client
            return self.client

        self.client = litellm
        return self.client

    def __deepcopy__(self, memo: Dict[int, Any]) -> "LiteLLMResponses":
        """
        Custom deepcopy to preserve the client (e.g., Router) across copies.

        This is needed because when the model is copied for background tasks
        (memory, summarization), the client reference needs to be preserved.
        """
        # Create a shallow copy first
        cls = self.__class__
        result = cls.__new__(cls)
        memo[id(self)] = result

        # Copy all attributes, but keep the same client reference
        for k, v in self.__dict__.items():
            if k in ("client", "_original_client"):
                # Keep the same client reference (don't deepcopy Router instances)
                setattr(result, k, v)
            else:
                setattr(result, k, copy.deepcopy(v, memo))

        return result

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
        """Sends a chat completion request to the LiteLLM API."""

        request_params = self.get_request_params(
            messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        assistant_message.metrics.start_timer()

        provider_response = self.get_client().responses(
            model=self.id,
            api_key=self.api_key,
            base_url=self.base_url,
            input=self._format_messages(messages, compress_tool_results, tools=tools),  # type: ignore
            **request_params,
        )

        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response, response_format=response_format)

        return model_response

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
        """Sends a streaming chat completion request to the LiteLLM API."""
        request_params = self.get_request_params(messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice)
        tool_use: Dict[str, Any] = {}

        assistant_message.metrics.start_timer()

        for chunk in self.get_client().responses(
            model=self.id,
            api_key=self.api_key,
            base_url=self.base_url,
            input=self._format_messages(messages, compress_tool_results, tools=tools),  # type: ignore
            stream=True,
            **request_params,
        ):
            model_response, tool_use = self._parse_provider_response_delta(
                stream_event=chunk,  # type: ignore
                assistant_message=assistant_message,
                tool_use=tool_use,  # type: ignore
            )
            yield model_response

        assistant_message.metrics.stop_timer()

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
        """Sends an asynchronous chat completion request to the LiteLLM API."""
        request_params = self.get_request_params(
            messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
        )

        assistant_message.metrics.start_timer()

        provider_response = await self.get_client().aresponses(
            model=self.id,
            api_key=self.api_key,
            base_url=self.base_url,
            input=self._format_messages(messages, compress_tool_results, tools=tools),  # type: ignore
            **request_params,
        )

        assistant_message.metrics.stop_timer()

        model_response = self._parse_provider_response(provider_response, response_format=response_format)

        return model_response

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
        """Sends an asynchronous streaming chat request to the LiteLLM API."""
        request_params = self.get_request_params(
            messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
        )
        tool_use: Dict[str, Any] = {}

        assistant_message.metrics.start_timer()

        try:
            # litellm.acompletion returns a coroutine that resolves to an async iterator
            # We need to await it first to get the actual async iterator
            async_stream = await self.get_client().aresponses(
                model=self.id,
                api_key=self.api_key,
                base_url=self.base_url,
                input=self._format_messages(messages, compress_tool_results, tools=tools),  # type: ignore
                stream=True,
                **request_params,
            )
            async for chunk in async_stream:  # type: ignore
                model_response, tool_use = self._parse_provider_response_delta(chunk, assistant_message,
                                                                               tool_use)  # type: ignore
                yield model_response

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error in streaming response: {e}")
            raise
