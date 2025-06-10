import asyncio
import collections.abc
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import AsyncGeneratorType, GeneratorType
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    Union,
    get_args,
)
from uuid import uuid4

from pydantic import BaseModel

from agno.exceptions import AgentRunException
from agno.media import AudioResponse, ImageArtifact
from agno.models.message import Citations, Message, MessageMetrics
from agno.models.response import ModelResponse, ModelResponseEvent, ToolExecution
from agno.run.response import RunResponseContentEvent, RunResponseEvent
from agno.run.team import RunResponseContentEvent as TeamRunResponseContentEvent
from agno.run.team import TeamRunResponseEvent
from agno.tools.function import Function, FunctionCall, FunctionExecutionResult, UserInputField
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.timer import Timer
from agno.utils.tools import get_function_call_for_tool_call, get_function_call_for_tool_execution


@dataclass
class MessageData:
    response_role: Optional[Literal["system", "user", "assistant", "tool"]] = None
    response_content: Any = ""
    response_thinking: Any = ""
    response_redacted_thinking: Any = ""
    response_citations: Optional[Citations] = None
    response_tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    response_audio: Optional[AudioResponse] = None
    response_image: Optional[ImageArtifact] = None

    # Data from the provider that we might need on subsequent messages
    response_provider_data: Optional[Dict[str, Any]] = None

    extra: Optional[Dict[str, Any]] = None


def _log_messages(messages: List[Message]) -> None:
    """
    Log messages for debugging.
    """
    for m in messages:
        # Don't log metrics for input messages
        m.log(metrics=False)


def _add_usage_metrics_to_assistant_message(assistant_message: Message, response_usage: Any) -> None:
    """
    Add usage metrics from the model provider to the assistant message.

    Args:
        assistant_message: Message to update with metrics
        response_usage: Usage data from model provider
    """

    # Standard token metrics
    if isinstance(response_usage, dict):
        if "input_tokens" in response_usage and response_usage.get("input_tokens") is not None:
            assistant_message.metrics.input_tokens = response_usage.get("input_tokens", 0)
        if "output_tokens" in response_usage and response_usage.get("output_tokens") is not None:
            assistant_message.metrics.output_tokens = response_usage.get("output_tokens", 0)
        if "prompt_tokens" in response_usage and response_usage.get("prompt_tokens") is not None:
            assistant_message.metrics.input_tokens = response_usage.get("prompt_tokens", 0)
        if "completion_tokens" in response_usage and response_usage.get("completion_tokens") is not None:
            assistant_message.metrics.output_tokens = response_usage.get("completion_tokens", 0)
        if "cached_tokens" in response_usage and response_usage.get("cached_tokens") is not None:
            assistant_message.metrics.cached_tokens = response_usage.get("cached_tokens", 0)
        if "cache_write_tokens" in response_usage and response_usage.get("cache_write_tokens") is not None:
            assistant_message.metrics.cache_write_tokens = response_usage.get("cache_write_tokens", 0)
        if "total_tokens" in response_usage and response_usage.get("total_tokens") is not None:
            assistant_message.metrics.total_tokens = response_usage.get("total_tokens", 0)
        else:
            assistant_message.metrics.total_tokens = (
                assistant_message.metrics.input_tokens + assistant_message.metrics.output_tokens
            )
    else:
        if hasattr(response_usage, "input_tokens") and response_usage.input_tokens:
            assistant_message.metrics.input_tokens = response_usage.input_tokens
        if hasattr(response_usage, "output_tokens") and response_usage.output_tokens:
            assistant_message.metrics.output_tokens = response_usage.output_tokens
        if hasattr(response_usage, "prompt_tokens") and response_usage.prompt_tokens is not None:
            assistant_message.metrics.input_tokens = response_usage.prompt_tokens
            assistant_message.metrics.prompt_tokens = response_usage.prompt_tokens
        if hasattr(response_usage, "completion_tokens") and response_usage.completion_tokens is not None:
            assistant_message.metrics.output_tokens = response_usage.completion_tokens
            assistant_message.metrics.completion_tokens = response_usage.completion_tokens
        if hasattr(response_usage, "total_tokens") and response_usage.total_tokens is not None:
            assistant_message.metrics.total_tokens = response_usage.total_tokens
        if hasattr(response_usage, "cached_tokens") and response_usage.cached_tokens is not None:
            assistant_message.metrics.cached_tokens = response_usage.cached_tokens
        if hasattr(response_usage, "cache_write_tokens") and response_usage.cache_write_tokens is not None:
            assistant_message.metrics.cache_write_tokens = response_usage.cache_write_tokens

    # If you didn't capture any total tokens
    if not assistant_message.metrics.total_tokens:
        if assistant_message.metrics.input_tokens is None:
            assistant_message.metrics.input_tokens = 0
        if assistant_message.metrics.output_tokens is None:
            assistant_message.metrics.output_tokens = 0

        assistant_message.metrics.total_tokens = (
            assistant_message.metrics.input_tokens + assistant_message.metrics.output_tokens
        )

    # Additional metrics (e.g., from Groq, Ollama)
    if isinstance(response_usage, dict) and "additional_metrics" in response_usage:
        assistant_message.metrics.additional_metrics = response_usage["additional_metrics"]

    # Token details (e.g., from OpenAI)
    if hasattr(response_usage, "prompt_tokens_details"):
        if isinstance(response_usage.prompt_tokens_details, dict):
            assistant_message.metrics.prompt_tokens_details = response_usage.prompt_tokens_details
            if (
                "audio_tokens" in response_usage.prompt_tokens_details
                and response_usage.prompt_tokens_details["audio_tokens"] is not None
            ):
                assistant_message.metrics.input_audio_tokens = response_usage.prompt_tokens_details["audio_tokens"]
            if (
                "cached_tokens" in response_usage.prompt_tokens_details
                and response_usage.prompt_tokens_details["cached_tokens"] is not None
            ):
                assistant_message.metrics.cached_tokens = response_usage.prompt_tokens_details["cached_tokens"]
        elif hasattr(response_usage.prompt_tokens_details, "model_dump"):
            assistant_message.metrics.prompt_tokens_details = response_usage.prompt_tokens_details.model_dump(
                exclude_none=True
            )
            if (
                hasattr(response_usage.prompt_tokens_details, "audio_tokens")
                and response_usage.prompt_tokens_details.audio_tokens is not None
            ):
                assistant_message.metrics.input_audio_tokens = response_usage.prompt_tokens_details.audio_tokens
            if (
                hasattr(response_usage.prompt_tokens_details, "cached_tokens")
                and response_usage.prompt_tokens_details.cached_tokens is not None
            ):
                assistant_message.metrics.cached_tokens = response_usage.prompt_tokens_details.cached_tokens

    if hasattr(response_usage, "completion_tokens_details"):
        if isinstance(response_usage.completion_tokens_details, dict):
            assistant_message.metrics.completion_tokens_details = response_usage.completion_tokens_details
            if (
                "audio_tokens" in response_usage.completion_tokens_details
                and response_usage.completion_tokens_details["audio_tokens"] is not None
            ):
                assistant_message.metrics.output_audio_tokens = response_usage.completion_tokens_details["audio_tokens"]
            if (
                "reasoning_tokens" in response_usage.completion_tokens_details
                and response_usage.completion_tokens_details["reasoning_tokens"] is not None
            ):
                assistant_message.metrics.reasoning_tokens = response_usage.completion_tokens_details[
                    "reasoning_tokens"
                ]
        elif hasattr(response_usage.completion_tokens_details, "model_dump"):
            assistant_message.metrics.completion_tokens_details = response_usage.completion_tokens_details.model_dump(
                exclude_none=True
            )
            if (
                hasattr(response_usage.completion_tokens_details, "audio_tokens")
                and response_usage.completion_tokens_details.audio_tokens is not None
            ):
                assistant_message.metrics.output_audio_tokens = response_usage.completion_tokens_details.audio_tokens
            if (
                hasattr(response_usage.completion_tokens_details, "reasoning_tokens")
                and response_usage.completion_tokens_details.reasoning_tokens is not None
            ):
                assistant_message.metrics.reasoning_tokens = response_usage.completion_tokens_details.reasoning_tokens

    assistant_message.metrics.audio_tokens = (
        assistant_message.metrics.input_audio_tokens + assistant_message.metrics.output_audio_tokens
    )


def _handle_agent_exception(a_exc: AgentRunException, additional_messages: Optional[List[Message]] = None) -> None:
    """Handle AgentRunException and collect additional messages."""
    if additional_messages is None:
        additional_messages = []
    if a_exc.user_message is not None:
        msg = (
            Message(role="user", content=a_exc.user_message)
            if isinstance(a_exc.user_message, str)
            else a_exc.user_message
        )
        additional_messages.append(msg)

    if a_exc.agent_message is not None:
        msg = (
            Message(role="assistant", content=a_exc.agent_message)
            if isinstance(a_exc.agent_message, str)
            else a_exc.agent_message
        )
        additional_messages.append(msg)

    if a_exc.messages:
        for m in a_exc.messages:
            if isinstance(m, Message):
                additional_messages.append(m)
            elif isinstance(m, dict):
                try:
                    additional_messages.append(Message(**m))
                except Exception as e:
                    log_warning(f"Failed to convert dict to Message: {e}")

    if a_exc.stop_execution:
        for m in additional_messages:
            m.stop_after_tool_call = True


@dataclass
class Model(ABC):
    # ID of the model to use.
    id: str
    # Name for this Model. This is not sent to the Model API.
    name: Optional[str] = None
    # Provider for this Model. This is not sent to the Model API.
    provider: Optional[str] = None

    # -*- Do not set the following attributes directly -*-
    # -*- Set them on the Agent instead -*-

    # True if the Model supports structured outputs natively (e.g. OpenAI)
    supports_native_structured_outputs: bool = False
    # True if the Model requires a json_schema for structured outputs (e.g. LMStudio)
    supports_json_schema_outputs: bool = False

    # Controls which (if any) function is called by the model.
    # "none" means the model will not call a function and instead generates a message.
    # "auto" means the model can pick between generating a message or calling a function.
    # Specifying a particular function via {"type: "function", "function": {"name": "my_function"}}
    #   forces the model to call that function.
    # "none" is the default when no functions are present. "auto" is the default if functions are present.
    _tool_choice: Optional[Union[str, Dict[str, Any]]] = None

    # System prompt from the model added to the Agent.
    system_prompt: Optional[str] = None
    # Instructions from the model added to the Agent.
    instructions: Optional[List[str]] = None

    # The role of the tool message.
    tool_message_role: str = "tool"
    # The role of the assistant message.
    assistant_message_role: str = "assistant"

    def __post_init__(self):
        if self.provider is None and self.name is not None:
            self.provider = f"{self.name} ({self.id})"

    def to_dict(self) -> Dict[str, Any]:
        fields = {"name", "id", "provider"}
        _dict = {field: getattr(self, field) for field in fields if getattr(self, field) is not None}
        return _dict

    def get_provider(self) -> str:
        return self.provider or self.name or self.__class__.__name__

    @abstractmethod
    def invoke(self, *args, **kwargs) -> Any:
        pass

    @abstractmethod
    async def ainvoke(self, *args, **kwargs) -> Any:
        pass

    @abstractmethod
    def invoke_stream(self, *args, **kwargs) -> Iterator[Any]:
        pass

    @abstractmethod
    async def ainvoke_stream(self, *args, **kwargs) -> AsyncGenerator[Any, None]:
        pass

    @abstractmethod
    def parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        """
        Parse the raw response from the model provider into a ModelResponse.

        Args:
            response: Raw response from the model provider

        Returns:
            ModelResponse: Parsed response data
        """
        pass

    @abstractmethod
    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        """
        Parse the streaming response from the model provider into ModelResponse objects.

        Args:
            response: Raw response chunk from the model provider

        Returns:
            ModelResponse: Parsed response delta
        """
        pass

    def response(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        functions: Optional[Dict[str, Function]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
    ) -> ModelResponse:
        """
        Generate a response from the model.
        """

        log_debug(f"{self.get_provider()} Response Start", center=True, symbol="-")
        log_debug(f"Model: {self.id}", center=True, symbol="-")

        _log_messages(messages)
        model_response = ModelResponse()

        function_call_count = 0

        while True:
            # Get response from model
            assistant_message, has_tool_calls = self._process_model_response(
                messages=messages,
                model_response=model_response,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice or self._tool_choice,
            )

            # Handle tool calls if present
            if has_tool_calls:
                # Prepare function calls
                function_calls_to_run = self._prepare_function_calls(
                    assistant_message=assistant_message,
                    messages=messages,
                    model_response=model_response,
                    functions=functions,
                )
                function_call_results: List[Message] = []

                # Execute function calls
                for function_call_response in self.run_function_calls(
                    function_calls=function_calls_to_run,
                    function_call_results=function_call_results,
                    current_function_call_count=function_call_count,
                    function_call_limit=tool_call_limit,
                ):
                    if isinstance(function_call_response, ModelResponse):
                        if (
                            function_call_response.event
                            in [
                                ModelResponseEvent.tool_call_completed.value,
                                ModelResponseEvent.tool_call_paused.value,
                            ]
                            and function_call_response.tool_executions is not None
                        ):
                            if model_response.tool_executions is None:
                                model_response.tool_executions = []
                            model_response.tool_executions.extend(function_call_response.tool_executions)

                        elif function_call_response.event not in [
                            ModelResponseEvent.tool_call_started.value,
                            ModelResponseEvent.tool_call_completed.value,
                        ]:
                            if function_call_response.content:
                                model_response.content += function_call_response.content  # type: ignore

                # Add a function call for each successful execution
                function_call_count += len(function_call_results)

                # Format and add results to messages
                self.format_function_call_results(
                    messages=messages, function_call_results=function_call_results, **model_response.extra or {}
                )
                for function_call_result in function_call_results:
                    function_call_result.log(metrics=True)

                # Check if we should stop after tool calls
                if any(m.stop_after_tool_call for m in function_call_results):
                    break

                # If we have any tool calls that require confirmation, break the loop
                if any(tc.requires_confirmation for tc in model_response.tool_executions or []):
                    break

                # If we have any tool calls that require external execution, break the loop
                if any(tc.external_execution_required for tc in model_response.tool_executions or []):
                    break

                # If we have any tool calls that require user input, break the loop
                if any(tc.requires_user_input for tc in model_response.tool_executions or []):
                    break

                # Continue loop to get next response
                continue

            # No tool calls or finished processing them
            break

        log_debug(f"{self.get_provider()} Response End", center=True, symbol="-")
        return model_response

    async def aresponse(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        functions: Optional[Dict[str, Function]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
    ) -> ModelResponse:
        """
        Generate an asynchronous response from the model.
        """

        log_debug(f"{self.get_provider()} Async Response Start", center=True, symbol="-")
        log_debug(f"Model: {self.id}", center=True, symbol="-")
        _log_messages(messages)
        model_response = ModelResponse()

        function_call_count = 0

        while True:
            # Get response from model
            assistant_message, has_tool_calls = await self._aprocess_model_response(
                messages=messages,
                model_response=model_response,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice or self._tool_choice,
            )

            # Handle tool calls if present
            if has_tool_calls:
                # Prepare function calls
                function_calls_to_run = self._prepare_function_calls(
                    assistant_message=assistant_message,
                    messages=messages,
                    model_response=model_response,
                    functions=functions,
                )
                function_call_results: List[Message] = []

                # Execute function calls
                async for function_call_response in self.arun_function_calls(
                    function_calls=function_calls_to_run,
                    function_call_results=function_call_results,
                    current_function_call_count=function_call_count,
                    function_call_limit=tool_call_limit,
                ):
                    if isinstance(function_call_response, ModelResponse):
                        if (
                            function_call_response.event
                            in [
                                ModelResponseEvent.tool_call_completed.value,
                                ModelResponseEvent.tool_call_paused.value,
                            ]
                            and function_call_response.tool_executions is not None
                        ):
                            if model_response.tool_executions is None:
                                model_response.tool_executions = []
                            model_response.tool_executions.extend(function_call_response.tool_executions)
                        elif function_call_response.event not in [
                            ModelResponseEvent.tool_call_started.value,
                            ModelResponseEvent.tool_call_completed.value,
                        ]:
                            if function_call_response.content:
                                model_response.content += function_call_response.content  # type: ignore

                # Add a function call for each successful execution
                function_call_count += len(function_call_results)

                # Format and add results to messages
                self.format_function_call_results(
                    messages=messages, function_call_results=function_call_results, **model_response.extra or {}
                )
                for function_call_result in function_call_results:
                    function_call_result.log(metrics=True)

                # Check if we should stop after tool calls
                if any(m.stop_after_tool_call for m in function_call_results):
                    break

                # If we have any tool calls that require confirmation, break the loop
                if any(tc.requires_confirmation for tc in model_response.tool_executions or []):
                    break

                # If we have any tool calls that require external execution, break the loop
                if any(tc.external_execution_required for tc in model_response.tool_executions or []):
                    break

                # If we have any tool calls that require user input, break the loop
                if any(tc.requires_user_input for tc in model_response.tool_executions or []):
                    break

                # Continue loop to get next response
                continue

            # No tool calls or finished processing them
            break

        log_debug(f"{self.get_provider()} Async Response End", center=True, symbol="-")
        return model_response

    def _process_model_response(
        self,
        messages: List[Message],
        model_response: ModelResponse,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Tuple[Message, bool]:
        """
        Process a single model response and return the assistant message and whether to continue.

        Returns:
            Tuple[Message, bool]: (assistant_message, should_continue)
        """
        # Create assistant message
        assistant_message = Message(role=self.assistant_message_role)

        # Generate response
        assistant_message.metrics.start_timer()
        response = self.invoke(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice or self._tool_choice,
        )
        assistant_message.metrics.stop_timer()

        # Parse provider response
        provider_response: ModelResponse = self.parse_provider_response(response, response_format=response_format)

        # Add parsed data to model response
        if provider_response.parsed is not None:
            model_response.parsed = provider_response.parsed

        # Populate the assistant message
        self._populate_assistant_message(assistant_message=assistant_message, provider_response=provider_response)

        # Add assistant message to messages
        messages.append(assistant_message)

        # Log response and metrics
        assistant_message.log(metrics=True)

        # Update model response with assistant message content and audio
        if assistant_message.content is not None:
            if model_response.content is None:
                model_response.content = assistant_message.get_content_string()
            else:
                model_response.content += assistant_message.get_content_string()
        if assistant_message.thinking is not None:
            model_response.thinking = assistant_message.thinking
        if assistant_message.redacted_thinking is not None:
            model_response.redacted_thinking = assistant_message.redacted_thinking
        if assistant_message.citations is not None:
            model_response.citations = assistant_message.citations
        if assistant_message.audio_output is not None:
            model_response.audio = assistant_message.audio_output
        if assistant_message.image_output is not None:
            model_response.image = assistant_message.image_output
        if provider_response.extra is not None:
            if model_response.extra is None:
                model_response.extra = {}
            model_response.extra.update(provider_response.extra)

        return assistant_message, bool(assistant_message.tool_calls)

    async def _aprocess_model_response(
        self,
        messages: List[Message],
        model_response: ModelResponse,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Tuple[Message, bool]:
        """
        Process a single async model response and return the assistant message and whether to continue.

        Returns:
            Tuple[Message, bool]: (assistant_message, should_continue)
        """
        # Create assistant message
        assistant_message = Message(role=self.assistant_message_role)

        # Generate response
        assistant_message.metrics.start_timer()
        response = await self.ainvoke(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice or self._tool_choice,
        )
        assistant_message.metrics.stop_timer()

        # Parse provider response
        provider_response: ModelResponse = self.parse_provider_response(response, response_format=response_format)

        # Add parsed data to model response
        if provider_response.parsed is not None:
            model_response.parsed = provider_response.parsed

        # Populate the assistant message
        self._populate_assistant_message(assistant_message=assistant_message, provider_response=provider_response)

        # Add assistant message to messages
        messages.append(assistant_message)

        # Log response and metrics
        assistant_message.log(metrics=True)

        # Update model response with assistant message content and audio
        if assistant_message.content is not None:
            if model_response.content is None:
                model_response.content = assistant_message.get_content_string()
            else:
                model_response.content += assistant_message.get_content_string()
        if assistant_message.thinking is not None:
            model_response.thinking = assistant_message.thinking
        if assistant_message.redacted_thinking is not None:
            model_response.redacted_thinking = assistant_message.redacted_thinking
        if assistant_message.citations is not None:
            model_response.citations = assistant_message.citations
        if assistant_message.audio_output is not None:
            model_response.audio = assistant_message.audio_output
        if assistant_message.image_output is not None:
            model_response.image = assistant_message.image_output
        if provider_response.extra is not None:
            if model_response.extra is None:
                model_response.extra = {}
            model_response.extra.update(provider_response.extra)

        return assistant_message, bool(assistant_message.tool_calls)

    def _populate_assistant_message(
        self,
        assistant_message: Message,
        provider_response: ModelResponse,
    ) -> Message:
        """
        Populate an assistant message with the provider response data.

        Args:
            assistant_message: The assistant message to populate
            provider_response: Parsed response from the model provider

        Returns:
            Message: The populated assistant message
        """
        # Add role to assistant message
        if provider_response.role is not None:
            assistant_message.role = provider_response.role

        # Add content to assistant message
        if provider_response.content is not None:
            assistant_message.content = provider_response.content

        # Add tool calls to assistant message
        if provider_response.tool_calls is not None and len(provider_response.tool_calls) > 0:
            assistant_message.tool_calls = provider_response.tool_calls

        # Add audio to assistant message
        if provider_response.audio is not None:
            assistant_message.audio_output = provider_response.audio

        # Add image to assistant message
        if provider_response.image is not None:
            assistant_message.image_output = provider_response.image

        # Add thinking content to assistant message
        if provider_response.thinking is not None:
            assistant_message.thinking = provider_response.thinking

        # Add redacted thinking content to assistant message
        if provider_response.redacted_thinking is not None:
            assistant_message.redacted_thinking = provider_response.redacted_thinking

        # Add reasoning content to assistant message
        if provider_response.reasoning_content is not None:
            assistant_message.reasoning_content = provider_response.reasoning_content

        # Add provider data to assistant message
        if provider_response.provider_data is not None:
            assistant_message.provider_data = provider_response.provider_data

        # Add citations to assistant message
        if provider_response.citations is not None:
            assistant_message.citations = provider_response.citations

        # Add usage metrics if provided
        if provider_response.response_usage is not None:
            _add_usage_metrics_to_assistant_message(
                assistant_message=assistant_message, response_usage=provider_response.response_usage
            )

        return assistant_message

    def process_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Iterator[ModelResponse]:
        """
        Process a streaming response from the model.
        """
        for response_delta in self.invoke_stream(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice or self._tool_choice,
        ):
            model_response_delta = self.parse_provider_response_delta(response_delta)
            yield from self._populate_stream_data_and_assistant_message(
                stream_data=stream_data, assistant_message=assistant_message, model_response_delta=model_response_delta
            )

    def response_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        functions: Optional[Dict[str, Function]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
    ) -> Iterator[Union[ModelResponse, RunResponseEvent, TeamRunResponseEvent]]:
        """
        Generate a streaming response from the model.
        """

        log_debug(f"{self.get_provider()} Response Stream Start", center=True, symbol="-")
        log_debug(f"Model: {self.id}", center=True, symbol="-")
        _log_messages(messages)

        function_call_count = 0

        while True:
            # Create assistant message and stream data
            assistant_message = Message(role=self.assistant_message_role)
            stream_data = MessageData()

            # Generate response
            assistant_message.metrics.start_timer()
            yield from self.process_response_stream(
                messages=messages,
                assistant_message=assistant_message,
                stream_data=stream_data,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice or self._tool_choice,
            )
            assistant_message.metrics.stop_timer()

            # Populate assistant message from stream data
            if stream_data.response_content:
                assistant_message.content = stream_data.response_content
            if stream_data.response_thinking:
                assistant_message.thinking = stream_data.response_thinking
            if stream_data.response_redacted_thinking:
                assistant_message.redacted_thinking = stream_data.response_redacted_thinking
            if stream_data.response_provider_data:
                assistant_message.provider_data = stream_data.response_provider_data
            if stream_data.response_citations:
                assistant_message.citations = stream_data.response_citations
            if stream_data.response_audio:
                assistant_message.audio_output = stream_data.response_audio
            if stream_data.response_tool_calls and len(stream_data.response_tool_calls) > 0:
                assistant_message.tool_calls = self.parse_tool_calls(stream_data.response_tool_calls)

            # Add assistant message to messages
            messages.append(assistant_message)
            assistant_message.log(metrics=True)

            # Handle tool calls if present
            if assistant_message.tool_calls is not None:
                # Prepare function calls
                function_calls_to_run: List[FunctionCall] = self.get_function_calls_to_run(
                    assistant_message, messages, functions
                )
                function_call_results: List[Message] = []

                # Execute function calls
                for function_call_response in self.run_function_calls(
                    function_calls=function_calls_to_run,
                    function_call_results=function_call_results,
                    current_function_call_count=function_call_count,
                    function_call_limit=tool_call_limit,
                ):
                    yield function_call_response

                # Add a function call for each successful execution
                function_call_count += len(function_call_results)

                # Format and add results to messages
                if stream_data.extra is not None:
                    self.format_function_call_results(
                        messages=messages, function_call_results=function_call_results, **stream_data.extra
                    )
                else:
                    self.format_function_call_results(messages=messages, function_call_results=function_call_results)

                for function_call_result in function_call_results:
                    function_call_result.log(metrics=True)

                # Check if we should stop after tool calls
                if any(m.stop_after_tool_call for m in function_call_results):
                    break

                # If we have any tool calls that require confirmation, break the loop
                if any(fc.function.requires_confirmation for fc in function_calls_to_run):
                    break

                # If we have any tool calls that require external execution, break the loop
                if any(fc.function.external_execution for fc in function_calls_to_run):
                    break

                # If we have any tool calls that require user input, break the loop
                if any(fc.function.requires_user_input for fc in function_calls_to_run):
                    break

                # Continue loop to get next response
                continue

            # No tool calls or finished processing them
            break

        log_debug(f"{self.get_provider()} Response Stream End", center=True, symbol="-")

    async def aprocess_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncIterator[ModelResponse]:
        """
        Process a streaming response from the model.
        """
        async for response_delta in self.ainvoke_stream(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice or self._tool_choice,
        ):  # type: ignore
            model_response_delta = self.parse_provider_response_delta(response_delta)
            for model_response in self._populate_stream_data_and_assistant_message(
                stream_data=stream_data, assistant_message=assistant_message, model_response_delta=model_response_delta
            ):
                yield model_response

    async def aresponse_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        functions: Optional[Dict[str, Function]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
    ) -> AsyncIterator[Union[ModelResponse, RunResponseEvent, TeamRunResponseEvent]]:
        """
        Generate an asynchronous streaming response from the model.
        """

        log_debug(f"{self.get_provider()} Async Response Stream Start", center=True, symbol="-")
        log_debug(f"Model: {self.id}", center=True, symbol="-")
        _log_messages(messages)

        function_call_count = 0

        while True:
            # Create assistant message and stream data
            assistant_message = Message(role=self.assistant_message_role)
            stream_data = MessageData()

            # Generate response
            assistant_message.metrics.start_timer()
            async for response in self.aprocess_response_stream(
                messages=messages,
                assistant_message=assistant_message,
                stream_data=stream_data,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice or self._tool_choice,
            ):
                yield response
            assistant_message.metrics.stop_timer()

            # Populate assistant message from stream data
            if stream_data.response_content:
                assistant_message.content = stream_data.response_content
            if stream_data.response_thinking:
                assistant_message.thinking = stream_data.response_thinking
            if stream_data.response_redacted_thinking:
                assistant_message.redacted_thinking = stream_data.response_redacted_thinking
            if stream_data.response_provider_data:
                assistant_message.provider_data = stream_data.response_provider_data
            if stream_data.response_audio:
                assistant_message.audio_output = stream_data.response_audio
            if stream_data.response_tool_calls and len(stream_data.response_tool_calls) > 0:
                assistant_message.tool_calls = self.parse_tool_calls(stream_data.response_tool_calls)

            # Add assistant message to messages
            messages.append(assistant_message)
            assistant_message.log(metrics=True)

            # Handle tool calls if present
            if assistant_message.tool_calls is not None:
                # Prepare function calls
                function_calls_to_run: List[FunctionCall] = self.get_function_calls_to_run(
                    assistant_message, messages, functions
                )
                function_call_results: List[Message] = []

                # Execute function calls
                async for function_call_response in self.arun_function_calls(
                    function_calls=function_calls_to_run,
                    function_call_results=function_call_results,
                    current_function_call_count=function_call_count,
                    function_call_limit=tool_call_limit,
                ):
                    yield function_call_response

                # Add a function call for each successful execution
                function_call_count += len(function_call_results)

                # Format and add results to messages
                if stream_data.extra is not None:
                    self.format_function_call_results(
                        messages=messages, function_call_results=function_call_results, **stream_data.extra
                    )
                else:
                    self.format_function_call_results(messages=messages, function_call_results=function_call_results)

                for function_call_result in function_call_results:
                    function_call_result.log(metrics=True)

                # Check if we should stop after tool calls
                if any(m.stop_after_tool_call for m in function_call_results):
                    break

                # If we have any tool calls that require confirmation, break the loop
                if any(fc.function.requires_confirmation for fc in function_calls_to_run):
                    break

                # If we have any tool calls that require external execution, break the loop
                if any(fc.function.external_execution for fc in function_calls_to_run):
                    break

                # If we have any tool calls that require user input, break the loop
                if any(fc.function.requires_user_input for fc in function_calls_to_run):
                    break

                # Continue loop to get next response
                continue

            # No tool calls or finished processing them
            break

        log_debug(f"{self.get_provider()} Async Response Stream End", center=True, symbol="-")

    def _populate_stream_data_and_assistant_message(
        self, stream_data: MessageData, assistant_message: Message, model_response_delta: ModelResponse
    ) -> Iterator[ModelResponse]:
        """Update the stream data and assistant message with the model response."""

        # Update metrics
        if not assistant_message.metrics.time_to_first_token:
            assistant_message.metrics.set_time_to_first_token()

        # Add role to assistant message
        if model_response_delta.role is not None:
            assistant_message.role = model_response_delta.role

        should_yield = False
        # Update stream_data content
        if model_response_delta.content is not None:
            stream_data.response_content += model_response_delta.content
            should_yield = True

        if model_response_delta.thinking is not None:
            stream_data.response_thinking += model_response_delta.thinking
            should_yield = True

        if model_response_delta.redacted_thinking is not None:
            stream_data.response_redacted_thinking += model_response_delta.redacted_thinking
            should_yield = True

        if model_response_delta.citations is not None:
            stream_data.response_citations = model_response_delta.citations
            should_yield = True

        if model_response_delta.provider_data:
            if stream_data.response_provider_data is None:
                stream_data.response_provider_data = {}
            stream_data.response_provider_data.update(model_response_delta.provider_data)

        # Update stream_data tool calls
        if model_response_delta.tool_calls is not None:
            if stream_data.response_tool_calls is None:
                stream_data.response_tool_calls = []
            stream_data.response_tool_calls.extend(model_response_delta.tool_calls)
            should_yield = True

        if model_response_delta.audio is not None:
            if stream_data.response_audio is None:
                stream_data.response_audio = AudioResponse(id=str(uuid4()), content="", transcript="")

            # Update the stream data with audio information
            if model_response_delta.audio.id is not None:
                stream_data.response_audio.id = model_response_delta.audio.id  # type: ignore
            if model_response_delta.audio.content is not None:
                stream_data.response_audio.content += model_response_delta.audio.content  # type: ignore
            if model_response_delta.audio.transcript is not None:
                stream_data.response_audio.transcript += model_response_delta.audio.transcript  # type: ignore
            if model_response_delta.audio.expires_at is not None:
                stream_data.response_audio.expires_at = model_response_delta.audio.expires_at
            if model_response_delta.audio.mime_type is not None:
                stream_data.response_audio.mime_type = model_response_delta.audio.mime_type
            stream_data.response_audio.sample_rate = model_response_delta.audio.sample_rate
            stream_data.response_audio.channels = model_response_delta.audio.channels

            should_yield = True

        if model_response_delta.image:
            if stream_data.response_image is None:
                stream_data.response_image = model_response_delta.image

        if model_response_delta.extra is not None:
            if stream_data.extra is None:
                stream_data.extra = {}
            stream_data.extra.update(model_response_delta.extra)

        if model_response_delta.response_usage is not None:
            _add_usage_metrics_to_assistant_message(
                assistant_message=assistant_message, response_usage=model_response_delta.response_usage
            )

        if should_yield:
            yield model_response_delta

    def parse_tool_calls(self, tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Parse the tool calls from the model provider into a list of tool calls.
        """
        return tool_calls_data

    def get_function_call_to_run_from_tool_execution(
        self,
        tool_execution: ToolExecution,
        functions: Optional[Dict[str, Function]] = None,
    ) -> FunctionCall:
        function_call = get_function_call_for_tool_execution(
            tool_execution=tool_execution,
            functions=functions,
        )
        if function_call is None:
            raise ValueError("Function call not found")
        return function_call

    def get_function_calls_to_run(
        self,
        assistant_message: Message,
        messages: List[Message],
        functions: Optional[Dict[str, Function]] = None,
    ) -> List[FunctionCall]:
        """
        Prepare function calls for the assistant message.
        """
        function_calls_to_run: List[FunctionCall] = []
        if assistant_message.tool_calls is not None:
            for tool_call in assistant_message.tool_calls:
                _tool_call_id = tool_call.get("id")
                _function_call = get_function_call_for_tool_call(tool_call, functions)
                if _function_call is None:
                    messages.append(
                        Message(
                            role=self.tool_message_role,
                            tool_call_id=_tool_call_id,
                            content="Error: The requested tool does not exist or is not available.",
                        )
                    )
                    continue
                if _function_call.error is not None:
                    messages.append(
                        Message(role=self.tool_message_role, tool_call_id=_tool_call_id, content=_function_call.error)
                    )
                    continue
                function_calls_to_run.append(_function_call)
        return function_calls_to_run

    def create_function_call_result(
        self,
        function_call: FunctionCall,
        success: bool,
        output: Optional[Union[List[Any], str]] = None,
        timer: Optional[Timer] = None,
    ) -> Message:
        """Create a function call result message."""
        kwargs = {}
        if timer is not None:
            kwargs["metrics"] = MessageMetrics(time=timer.elapsed)
        return Message(
            role=self.tool_message_role,
            content=output if success else function_call.error,
            tool_call_id=function_call.call_id,
            tool_name=function_call.function.name,
            tool_args=function_call.arguments,
            tool_call_error=not success,
            stop_after_tool_call=function_call.function.stop_after_tool_call,
            **kwargs,
        )

    def create_tool_call_limit_error_result(self, function_call: FunctionCall) -> Message:
        return Message(
            role=self.tool_message_role,
            content=f"Tool call limit reached. Tool call {function_call.function.name} not executed. Don't try to execute it again.",
            tool_call_id=function_call.call_id,
            tool_name=function_call.function.name,
            tool_args=function_call.arguments,
            tool_call_error=True,
        )

    def run_function_call(
        self,
        function_call: FunctionCall,
        function_call_results: List[Message],
        additional_messages: Optional[List[Message]] = None,
    ) -> Iterator[Union[ModelResponse, RunResponseEvent, TeamRunResponseEvent]]:
        # Start function call
        function_call_timer = Timer()
        function_call_timer.start()
        # Yield a tool_call_started event
        yield ModelResponse(
            content=function_call.get_call_str(),
            tool_executions=[
                ToolExecution(
                    tool_call_id=function_call.call_id,
                    tool_name=function_call.function.name,
                    tool_args=function_call.arguments,
                )
            ],
            event=ModelResponseEvent.tool_call_started.value,
        )

        # Run function calls sequentially
        function_execution_result: FunctionExecutionResult = FunctionExecutionResult(status="failure")
        try:
            function_execution_result = function_call.execute()
        except AgentRunException as a_exc:
            # Update additional messages from function call
            _handle_agent_exception(a_exc, additional_messages)
            # Set function call success to False if an exception occurred
        except Exception as e:
            log_error(f"Error executing function {function_call.function.name}: {e}")
            raise e

        function_call_success = function_execution_result.status == "success"

        # Stop function call timer
        function_call_timer.stop()

        # Process function call output
        function_call_output: str = ""

        if isinstance(function_call.result, (GeneratorType, collections.abc.Iterator)):
            for item in function_call.result:
                # This function yields agent/team run events
                if isinstance(item, tuple(get_args(RunResponseEvent))) or isinstance(
                    item, tuple(get_args(TeamRunResponseEvent))
                ):
                    # We only capture content events
                    if isinstance(item, RunResponseContentEvent) or isinstance(item, TeamRunResponseContentEvent):
                        # Capture output
                        function_call_output += item.content or ""

                        if function_call.function.show_result:
                            yield ModelResponse(content=item.content)

                    # Yield the event itself to bubble it up
                    yield item

                else:
                    function_call_output += str(item)
                    if function_call.function.show_result:
                        yield ModelResponse(content=str(item))
        else:
            function_call_output = str(function_call.result)
            if function_call.function.show_result:
                yield ModelResponse(content=function_call_output)

        # Create and yield function call result
        function_call_result = self.create_function_call_result(
            function_call, success=function_call_success, output=function_call_output, timer=function_call_timer
        )
        yield ModelResponse(
            content=f"{function_call.get_call_str()} completed in {function_call_timer.elapsed:.4f}s.",
            tool_executions=[
                ToolExecution(
                    tool_call_id=function_call_result.tool_call_id,
                    tool_name=function_call_result.tool_name,
                    tool_args=function_call_result.tool_args,
                    tool_call_error=function_call_result.tool_call_error,
                    result=str(function_call_result.content),
                    stop_after_tool_call=function_call_result.stop_after_tool_call,
                    metrics=function_call_result.metrics,
                )
            ],
            event=ModelResponseEvent.tool_call_completed.value,
        )

        # Add function call to function call results
        function_call_results.append(function_call_result)

    def run_function_calls(
        self,
        function_calls: List[FunctionCall],
        function_call_results: List[Message],
        additional_messages: Optional[List[Message]] = None,
        current_function_call_count: int = 0,
        function_call_limit: Optional[int] = None,
    ) -> Iterator[Union[ModelResponse, RunResponseEvent, TeamRunResponseEvent]]:
        # Additional messages from function calls that will be added to the function call results
        if additional_messages is None:
            additional_messages = []

        for fc in function_calls:
            if function_call_limit is not None:
                current_function_call_count += 1
                # We have reached the function call limit, so we add an error result to the function call results
                if current_function_call_count > function_call_limit:
                    function_call_results.append(self.create_tool_call_limit_error_result(fc))
                    continue

            paused_tool_executions = []

            # The function cannot be executed without user confirmation
            if fc.function.requires_confirmation:
                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        requires_confirmation=True,
                    )
                )
            # If the function requires user input, we yield a message to the user
            if fc.function.requires_user_input:
                user_input_schema = fc.function.user_input_schema
                if fc.arguments and user_input_schema:
                    for name, value in fc.arguments.items():
                        for user_input_field in user_input_schema:
                            if user_input_field.name == name:
                                user_input_field.value = value

                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        requires_user_input=True,
                        user_input_schema=user_input_schema,
                    )
                )
            # If the function is from the user control flow tools, we handle it here
            if fc.function.name == "get_user_input" and fc.arguments and fc.arguments.get("user_input_fields"):
                user_input_schema = []
                for input_field in fc.arguments.get("user_input_fields", []):
                    field_type = input_field.get("field_type")
                    try:
                        python_type = eval(field_type) if isinstance(field_type, str) else field_type
                    except (NameError, SyntaxError):
                        python_type = str  # Default to str if type is invalid
                    user_input_schema.append(
                        UserInputField(
                            name=input_field.get("field_name"),
                            field_type=python_type,
                            description=input_field.get("field_description"),
                        )
                    )

                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        requires_user_input=True,
                        user_input_schema=user_input_schema,
                    )
                )
            # If the function requires external execution, we yield a message to the user
            if fc.function.external_execution:
                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        external_execution_required=True,
                    )
                )

            if paused_tool_executions:
                yield ModelResponse(
                    tool_executions=paused_tool_executions,
                    event=ModelResponseEvent.tool_call_paused.value,
                )
                # We don't execute the function calls here
                continue

            yield from self.run_function_call(
                function_call=fc, function_call_results=function_call_results, additional_messages=additional_messages
            )

        # Add any additional messages at the end
        if additional_messages:
            function_call_results.extend(additional_messages)

    async def arun_function_call(
        self,
        function_call: FunctionCall,
    ) -> Tuple[Union[bool, AgentRunException], Timer, FunctionCall]:
        """Run a single function call and return its success status, timer, and the FunctionCall object."""
        from inspect import isasyncgenfunction, iscoroutine, iscoroutinefunction

        function_call_timer = Timer()
        function_call_timer.start()
        success: Union[bool, AgentRunException] = False

        try:
            if (
                iscoroutinefunction(function_call.function.entrypoint)
                or isasyncgenfunction(function_call.function.entrypoint)
                or iscoroutine(function_call.function.entrypoint)
            ):
                result = await function_call.aexecute()
                success = result.status == "success"

            # If any of the hooks are async, we need to run the function call asynchronously
            elif function_call.function.tool_hooks is not None and any(
                iscoroutinefunction(f) for f in function_call.function.tool_hooks
            ):
                result = await function_call.aexecute()
                success = result.status == "success"
            else:
                result = await asyncio.to_thread(function_call.execute)
                success = result.status == "success"
        except AgentRunException as e:
            success = e
        except Exception as e:
            log_error(f"Error executing function {function_call.function.name}: {e}")
            success = False
            raise e

        function_call_timer.stop()
        return success, function_call_timer, function_call

    async def arun_function_calls(
        self,
        function_calls: List[FunctionCall],
        function_call_results: List[Message],
        additional_messages: Optional[List[Message]] = None,
        current_function_call_count: int = 0,
        function_call_limit: Optional[int] = None,
        skip_pause_check: bool = False,
    ) -> AsyncIterator[Union[ModelResponse, RunResponseEvent, TeamRunResponseEvent]]:
        # Additional messages from function calls that will be added to the function call results
        if additional_messages is None:
            additional_messages = []

        function_calls_to_run = []
        for fc in function_calls:
            if function_call_limit is not None:
                current_function_call_count += 1
                # We have reached the function call limit, so we add an error result to the function call results
                if current_function_call_count > function_call_limit:
                    function_call_results.append(self.create_tool_call_limit_error_result(fc))
                    # Skip this function call
                    continue
            function_calls_to_run.append(fc)

        # Yield tool_call_started events for all function calls or pause them
        for fc in function_calls_to_run:
            paused_tool_executions = []
            # The function cannot be executed without user confirmation
            if fc.function.requires_confirmation and not skip_pause_check:
                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        requires_confirmation=True,
                    )
                )
            # If the function requires user input, we yield a message to the user
            if fc.function.requires_user_input and not skip_pause_check:
                user_input_schema = fc.function.user_input_schema
                if fc.arguments and user_input_schema:
                    for name, value in fc.arguments.items():
                        for user_input_field in user_input_schema:
                            if user_input_field.name == name:
                                user_input_field.value = value

                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        requires_user_input=True,
                        user_input_schema=user_input_schema,
                    )
                )
            # If the function is from the user control flow tools, we handle it here
            if (
                fc.function.name == "get_user_input"
                and fc.arguments
                and fc.arguments.get("user_input_fields")
                and not skip_pause_check
            ):
                fc.function.requires_user_input = True
                user_input_schema = []
                for input_field in fc.arguments.get("user_input_fields", []):
                    field_type = input_field.get("field_type")
                    try:
                        python_type = eval(field_type) if isinstance(field_type, str) else field_type
                    except (NameError, SyntaxError):
                        python_type = str  # Default to str if type is invalid
                    user_input_schema.append(
                        UserInputField(
                            name=input_field.get("field_name"),
                            field_type=python_type,
                            description=input_field.get("field_description"),
                        )
                    )

                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        requires_user_input=True,
                        user_input_schema=user_input_schema,
                    )
                )
            # If the function requires external execution, we yield a message to the user
            if fc.function.external_execution and not skip_pause_check:
                paused_tool_executions.append(
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                        external_execution_required=True,
                    )
                )

            if paused_tool_executions:
                yield ModelResponse(
                    tool_executions=paused_tool_executions,
                    event=ModelResponseEvent.tool_call_paused.value,
                )
                # We don't execute the function calls here
                continue

            yield ModelResponse(
                content=fc.get_call_str(),
                tool_executions=[
                    ToolExecution(
                        tool_call_id=fc.call_id,
                        tool_name=fc.function.name,
                        tool_args=fc.arguments,
                    )
                ],
                event=ModelResponseEvent.tool_call_started.value,
            )

        # Create and run all function calls in parallel (skip ones that need confirmation)
        if skip_pause_check:
            function_calls_to_run = function_calls_to_run
        else:
            function_calls_to_run = [
                fc
                for fc in function_calls_to_run
                if not (
                    fc.function.requires_confirmation
                    or fc.function.external_execution
                    or fc.function.requires_user_input
                )
            ]

        results = await asyncio.gather(
            *(self.arun_function_call(fc) for fc in function_calls_to_run), return_exceptions=True
        )

        # Process results
        for result in results:
            # If result is an exception, skip processing it
            if isinstance(result, BaseException):
                log_error(f"Error during function call: {result}")
                raise result

            # Unpack result
            function_call_success, function_call_timer, fc = result

            # Handle AgentRunException
            if isinstance(function_call_success, AgentRunException):
                a_exc = function_call_success
                # Update additional messages from function call
                _handle_agent_exception(a_exc, additional_messages)
                # Set function call success to False if an exception occurred
                function_call_success = False

            # Process function call output
            function_call_output: str = ""
            if isinstance(fc.result, (GeneratorType, collections.abc.Iterator)):
                for item in fc.result:
                    # This function yields agent/team run events
                    if isinstance(item, tuple(get_args(RunResponseEvent))) or isinstance(
                        item, tuple(get_args(TeamRunResponseEvent))
                    ):
                        # We only capture content events
                        if isinstance(item, RunResponseContentEvent) or isinstance(item, TeamRunResponseContentEvent):
                            # Capture output
                            function_call_output += item.content or ""

                            if fc.function.show_result:
                                yield ModelResponse(content=item.content)

                        # Yield the event itself to bubble it up
                        yield item
                    else:
                        function_call_output += str(item)
                        if fc.function.show_result:
                            yield ModelResponse(content=str(item))
            elif isinstance(fc.result, (AsyncGeneratorType, collections.abc.AsyncIterator)):
                async for item in fc.result:
                    # This function yields agent/team run events
                    if isinstance(item, tuple(get_args(RunResponseEvent))) or isinstance(
                        item, tuple(get_args(TeamRunResponseEvent))
                    ):
                        # We only capture content events
                        if isinstance(item, RunResponseContentEvent) or isinstance(item, TeamRunResponseContentEvent):
                            # Capture output
                            function_call_output += item.content or ""

                            if fc.function.show_result:
                                yield ModelResponse(content=item.content)

                        # Yield the event itself to bubble it up
                        yield item
                    else:
                        function_call_output += str(item)
                        if fc.function.show_result:
                            yield ModelResponse(content=str(item))
            else:
                function_call_output = str(fc.result)
                if fc.function.show_result:
                    yield ModelResponse(content=function_call_output)

            # Create and yield function call result
            function_call_result = self.create_function_call_result(
                fc, success=function_call_success, output=function_call_output, timer=function_call_timer
            )
            yield ModelResponse(
                content=f"{fc.get_call_str()} completed in {function_call_timer.elapsed:.4f}s.",
                tool_executions=[
                    ToolExecution(
                        tool_call_id=function_call_result.tool_call_id,
                        tool_name=function_call_result.tool_name,
                        tool_args=function_call_result.tool_args,
                        tool_call_error=function_call_result.tool_call_error,
                        result=str(function_call_result.content),
                        stop_after_tool_call=function_call_result.stop_after_tool_call,
                        metrics=function_call_result.metrics,
                    )
                ],
                event=ModelResponseEvent.tool_call_completed.value,
            )

            # Add function call result to function call results
            function_call_results.append(function_call_result)

        # Add any additional messages at the end
        if additional_messages:
            function_call_results.extend(additional_messages)

    def _prepare_function_calls(
        self,
        assistant_message: Message,
        messages: List[Message],
        model_response: ModelResponse,
        functions: Optional[Dict[str, Function]] = None,
    ) -> List[FunctionCall]:
        """
        Prepare function calls from tool calls in the assistant message.
        """
        if model_response.content is None:
            model_response.content = ""
        if model_response.tool_calls is None:
            model_response.tool_calls = []

        function_calls_to_run: List[FunctionCall] = self.get_function_calls_to_run(
            assistant_message, messages, functions
        )
        return function_calls_to_run

    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], **kwargs
    ) -> None:
        """
        Format function call results.
        """
        if len(function_call_results) > 0:
            messages.extend(function_call_results)

    def get_system_message_for_model(self, tools: Optional[List[Any]] = None) -> Optional[str]:
        return self.system_prompt

    def get_instructions_for_model(self, tools: Optional[List[Any]] = None) -> Optional[List[str]]:
        return self.instructions

    def __deepcopy__(self, memo):
        """Create a deep copy of the Model instance.

        Args:
            memo (dict): Dictionary of objects already copied during the current copying pass.

        Returns:
            Model: A new Model instance with deeply copied attributes.
        """
        from copy import copy, deepcopy

        # Create a new instance without calling __init__
        cls = self.__class__
        new_model = cls.__new__(cls)
        memo[id(self)] = new_model

        # Deep copy all attributes
        for k, v in self.__dict__.items():
            if k in {"response_format", "_tools", "_functions"}:
                continue
            try:
                setattr(new_model, k, deepcopy(v, memo))
            except Exception:
                try:
                    setattr(new_model, k, copy(v))
                except Exception:
                    setattr(new_model, k, v)

        return new_model
