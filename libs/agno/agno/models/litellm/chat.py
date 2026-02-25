import copy
import json
from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message
from agno.utils.tokens import count_schema_tokens

try:
    import litellm
    from litellm import validate_environment
except ImportError:
    raise ImportError("`litellm` not installed. Please install it via `pip install litellm`")


@dataclass
class LiteLLM(Model):
    """
    A class for interacting with LiteLLM Python SDK.

    LiteLLM allows you to use a unified interface for various LLM providers.
    For more information, see: https://docs.litellm.ai/docs/
    """

    id: str = "gpt-4o"
    name: str = "LiteLLM"
    provider: str = "LiteLLM"

    api_key: Optional[str] = None
    api_base: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: float = 0.7
    top_p: float = 1.0
    metadata: Optional[Dict[str, Any]] = None
    extra_headers: Optional[Dict[str, Any]] = None
    extra_query: Optional[Dict[str, Any]] = None
    extra_body: Optional[Dict[str, Any]] = None
    request_params: Optional[Dict[str, Any]] = None

    client: Optional[Any] = None

    # Store the original client to preserve it across copies (e.g., for Router instances)
    _original_client: Optional[Any] = None

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

    def __deepcopy__(self, memo: Dict[int, Any]) -> "LiteLLM":
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

    def _format_messages(self, messages: List[Message], compress_tool_results: bool = False) -> List[Dict[str, Any]]:
        """Format messages for LiteLLM API.

        Ensures that tool result messages always carry a tool_call_id that matches
        the id emitted in the preceding assistant message's tool_calls list.  This is
        critical for backends like AWS Bedrock where each toolResult must reference the
        exact toolUseId of the corresponding toolUse block.
        """
        formatted_messages: List[Dict[str, Any]] = []

        # Track the tool-call IDs produced by the most recent assistant message so
        # that subsequent tool-result messages can be matched by position when their
        # own tool_call_id is missing or was never set.
        last_tool_call_ids: List[str] = []
        tool_result_index: int = 0

        for m in messages:
            # Use compressed content for tool messages if compression is active
            if m.role == "tool":
                content = m.get_content(use_compressed_content=compress_tool_results)
            else:
                content = m.content if m.content is not None else ""

            msg: Dict[str, Any] = {"role": m.role, "content": content}

            # Handle media
            if (m.images is not None and len(m.images) > 0) or (m.audio is not None and len(m.audio) > 0):
                if isinstance(m.content, str):
                    content_list = [{"type": "text", "text": m.content}]
                    if m.images is not None:
                        content_list.extend(images_to_message(images=m.images))
                    if m.audio is not None:
                        content_list.extend(audio_to_message(audio=m.audio))
                    msg["content"] = content_list

            if m.videos is not None and len(m.videos) > 0:
                log_warning("Video input is currently unsupported by LLM providers.")

            # Handle files
            if m.files is not None:
                if isinstance(msg["content"], str):
                    content_list = [{"type": "text", "text": msg["content"]}]
                else:
                    content_list = msg["content"] if isinstance(msg["content"], list) else []
                for file in m.files:
                    file_part = _format_file_for_message(file)
                    if file_part:
                        content_list.append(file_part)
                msg["content"] = content_list

            # Handle tool calls in assistant messages
            if m.role == "assistant" and m.tool_calls:
                built_tool_calls = []
                last_tool_call_ids = []
                for i, tc in enumerate(m.tool_calls):
                    tc_id = tc.get("id") or f"call_{i}"
                    built_tool_calls.append(
                        {
                            "id": tc_id,
                            "type": "function",
                            "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                        }
                    )
                    last_tool_call_ids.append(tc_id)
                msg["tool_calls"] = built_tool_calls
                # Reset the positional counter for the upcoming tool-result messages
                tool_result_index = 0

            # Handle tool responses
            if m.role == "tool":
                # Determine the correct tool_call_id.
                # 1. Use the message's own tool_call_id if it is non-empty.
                # 2. Otherwise fall back to the positional ID from the preceding
                #    assistant message's tool_calls list.
                resolved_tool_call_id = m.tool_call_id or ""
                if not resolved_tool_call_id and tool_result_index < len(last_tool_call_ids):
                    resolved_tool_call_id = last_tool_call_ids[tool_result_index]
                tool_result_index += 1

                msg["tool_call_id"] = resolved_tool_call_id
                msg["name"] = m.name or ""

                if m.audio is not None and len(m.audio) > 0:
                    log_warning("Audio input is currently unsupported.")

                if m.images is not None and len(m.images) > 0:
                    log_warning("Image input is currently unsupported.")

                if m.videos is not None and len(m.videos) > 0:
                    log_warning("Video input is currently unsupported.")
            formatted_messages.append(msg)

        return formatted_messages

    def format_function_call_results(
        self,
        messages: List[Message],
        function_call_results: List[Message],
        compress_tool_results: bool = False,
        **kwargs,
    ) -> None:
        """Format function call results, ensuring each result carries the correct tool_call_id.

        When LiteLLM routes to Bedrock-style backends the provider requires every
        toolResult to reference the exact toolUseId of its corresponding toolUse
        block.  This override mirrors the approach used by the AwsBedrock model:
        it fills in missing tool_call_id values from the ``tool_ids`` list that the
        model response may provide via ``extra``.

        Args:
            messages: The conversation message list to append results to.
            function_call_results: Tool result messages produced by function execution.
            compress_tool_results: Whether to use compressed content.
            **kwargs: May contain ``tool_ids`` — a list of IDs in the same order as
                the tool calls in the assistant message.
        """
        if function_call_results:
            tool_ids: List[str] = kwargs.get("tool_ids", [])
            for idx, fc_message in enumerate(function_call_results):
                if not fc_message.tool_call_id:
                    if idx < len(tool_ids):
                        fc_message.tool_call_id = tool_ids[idx]
                messages.append(fc_message)

    def get_request_params(self, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The API kwargs for the model.
        """
        base_params: Dict[str, Any] = {
            "model": self.id,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        if self.max_tokens:
            base_params["max_tokens"] = self.max_tokens
        if self.api_key:
            base_params["api_key"] = self.api_key
        if self.api_base:
            base_params["api_base"] = self.api_base
        if self.extra_headers:
            base_params["extra_headers"] = self.extra_headers
        if self.extra_query:
            base_params["extra_query"] = self.extra_query
        if tools:
            base_params["tools"] = tools
            base_params["tool_choice"] = "auto"

        # Handle metadata via extra_body as per LiteLLM docs
        if self.metadata:
            if self.extra_body:
                base_params["extra_body"] = {**self.extra_body, "metadata": self.metadata}
            else:
                base_params["extra_body"] = {"metadata": self.metadata}
        elif self.extra_body:
            base_params["extra_body"] = self.extra_body

        # Add additional request params if provided
        request_params: Dict[str, Any] = {k: v for k, v in base_params.items() if v is not None}
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
        return request_params

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
        completion_kwargs = self.get_request_params(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages, compress_tool_results)

        assistant_message.metrics.start_timer()

        provider_response = self.get_client().completion(**completion_kwargs)

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
        completion_kwargs = self.get_request_params(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages, compress_tool_results)
        completion_kwargs["stream"] = True
        completion_kwargs["stream_options"] = {"include_usage": True}

        assistant_message.metrics.start_timer()

        for chunk in self.get_client().completion(**completion_kwargs):
            yield self._parse_provider_response_delta(chunk)

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
        completion_kwargs = self.get_request_params(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages, compress_tool_results)

        assistant_message.metrics.start_timer()

        provider_response = await self.get_client().acompletion(**completion_kwargs)

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
        completion_kwargs = self.get_request_params(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages, compress_tool_results)
        completion_kwargs["stream"] = True
        completion_kwargs["stream_options"] = {"include_usage": True}

        assistant_message.metrics.start_timer()

        try:
            # litellm.acompletion returns a coroutine that resolves to an async iterator
            # We need to await it first to get the actual async iterator
            async_stream = await self.get_client().acompletion(**completion_kwargs)
            async for chunk in async_stream:
                yield self._parse_provider_response_delta(chunk)

            assistant_message.metrics.stop_timer()

        except Exception as e:
            log_error(f"Error in streaming response: {e}")
            raise

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        """Parse the provider response."""
        model_response = ModelResponse()

        response_message = response.choices[0].message

        if response_message.content is not None:
            model_response.content = response_message.content

        if hasattr(response_message, "reasoning_content") and response_message.reasoning_content is not None:
            model_response.reasoning_content = response_message.reasoning_content

        if hasattr(response_message, "tool_calls") and response_message.tool_calls:
            model_response.tool_calls = []
            tool_ids: List[str] = []
            for tool_call in response_message.tool_calls:
                tc_id = tool_call.id
                model_response.tool_calls.append(
                    {
                        "id": tc_id,
                        "type": "function",
                        "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments},
                    }
                )
                tool_ids.append(tc_id)
            model_response.extra = model_response.extra or {}
            model_response.extra["tool_ids"] = tool_ids

        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def _parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """Parse the provider response delta for streaming responses."""
        model_response = ModelResponse()

        if hasattr(response_delta, "choices") and len(response_delta.choices) > 0:
            choice_delta = response_delta.choices[0].delta

            if choice_delta:
                if hasattr(choice_delta, "content") and choice_delta.content is not None:
                    model_response.content = choice_delta.content

                if hasattr(choice_delta, "reasoning_content") and choice_delta.reasoning_content is not None:
                    model_response.reasoning_content = choice_delta.reasoning_content

                if hasattr(choice_delta, "tool_calls") and choice_delta.tool_calls:
                    processed_tool_calls = []
                    delta_tool_ids: List[str] = []
                    for tool_call in choice_delta.tool_calls:
                        # Get the actual index from the tool call, defaulting to 0 if not available
                        actual_index = getattr(tool_call, "index", 0) if hasattr(tool_call, "index") else 0

                        # Create a basic structure with the correct index
                        tool_call_dict: Dict[str, Any] = {"index": actual_index, "type": "function"}

                        # Extract ID if available
                        if hasattr(tool_call, "id") and tool_call.id is not None:
                            tool_call_dict["id"] = tool_call.id
                            delta_tool_ids.append(tool_call.id)

                        # Extract function data
                        function_data: Dict[str, Any] = {}
                        if hasattr(tool_call, "function"):
                            if hasattr(tool_call.function, "name") and tool_call.function.name is not None:
                                function_data["name"] = tool_call.function.name
                            if hasattr(tool_call.function, "arguments") and tool_call.function.arguments is not None:
                                function_data["arguments"] = tool_call.function.arguments

                        tool_call_dict["function"] = function_data
                        processed_tool_calls.append(tool_call_dict)

                    model_response.tool_calls = processed_tool_calls

                    # Propagate tool_ids through extra so that
                    # format_function_call_results can use them as a fallback.
                    if delta_tool_ids:
                        model_response.extra = model_response.extra or {}
                        model_response.extra["tool_ids"] = delta_tool_ids

        # Add usage metrics if present in streaming response
        if hasattr(response_delta, "usage") and response_delta.usage is not None:
            model_response.response_usage = self._get_metrics(response_delta.usage)

        return model_response

    @staticmethod
    def parse_tool_calls(tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data (List[Dict[str, Any]]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        # Early return for empty list
        if not tool_calls_data:
            return []

        # Group tool calls by index
        tool_calls_by_index: Dict[int, Dict[str, Any]] = {}

        for tc in tool_calls_data:
            # Get index (default to 0)
            index = tc.get("index", 0)
            if not isinstance(index, int):
                index = 0

            # Initialize if first time seeing this index
            if index not in tool_calls_by_index:
                tool_calls_by_index[index] = {"id": None, "type": "function", "function": {"name": "", "arguments": ""}}

            # Update with new information
            if tc.get("id") is not None:
                tool_calls_by_index[index]["id"] = tc["id"]

            if tc.get("type") is not None:
                tool_calls_by_index[index]["type"] = tc["type"]

            # Update function information
            function_data = tc.get("function", {})
            if not isinstance(function_data, dict):
                function_data = {}

            # Update function name if provided
            if function_data.get("name") is not None:
                name = function_data.get("name", "")
                if isinstance(tool_calls_by_index[index]["function"], dict):
                    # type: ignore
                    tool_calls_by_index[index]["function"]["name"] = name

            # Update function arguments if provided
            if function_data.get("arguments") is not None:
                args = function_data.get("arguments", "")
                if isinstance(tool_calls_by_index[index]["function"], dict):
                    current_args = tool_calls_by_index[index]["function"].get("arguments", "")  # type: ignore
                    if isinstance(current_args, str) and isinstance(args, str):
                        # type: ignore
                        tool_calls_by_index[index]["function"]["arguments"] = current_args + args

        # Process arguments - Ensure they're valid JSON for the Message.log() method
        result = []
        for tc in tool_calls_by_index.values():
            # Make a safe copy to avoid modifying the original
            tc_copy = {
                "id": tc.get("id"),
                "type": tc.get("type", "function"),
                "function": {"name": "", "arguments": ""},
            }

            # Safely copy function data
            if isinstance(tc.get("function"), dict):
                func_dict = tc.get("function", {})
                tc_copy["function"]["name"] = func_dict.get("name", "")

                # Process arguments
                args = func_dict.get("arguments", "")
                if args and isinstance(args, str):
                    try:
                        # Check if arguments are already valid JSON
                        parsed = json.loads(args)
                        # If it's not a dict, convert to a JSON string of a dict
                        if not isinstance(parsed, dict):
                            tc_copy["function"]["arguments"] = json.dumps({"value": parsed})
                        else:
                            tc_copy["function"]["arguments"] = args
                    except json.JSONDecodeError:
                        # If not valid JSON, make it a JSON dict
                        tc_copy["function"]["arguments"] = json.dumps({"text": args})

            result.append(tc_copy)

        return result

    def _get_metrics(self, response_usage: Any) -> MessageMetrics:
        """
        Parse the given LiteLLM usage into an Agno MessageMetrics object.

        Args:
            response_usage: Usage data from LiteLLM

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        if isinstance(response_usage, dict):
            metrics.input_tokens = response_usage.get("prompt_tokens") or 0
            metrics.output_tokens = response_usage.get("completion_tokens") or 0
            if (prompt_details := response_usage.get("prompt_tokens_details")) and isinstance(prompt_details, dict):
                metrics.cache_read_tokens = prompt_details.get("cached_tokens", 0) or 0
                metrics.audio_input_tokens = prompt_details.get("audio_tokens", 0) or 0
            if (completion_details := response_usage.get("completion_tokens_details")) and isinstance(
                completion_details, dict
            ):
                metrics.reasoning_tokens = completion_details.get("reasoning_tokens", 0) or 0
                metrics.audio_output_tokens = completion_details.get("audio_tokens", 0) or 0
        else:
            metrics.input_tokens = response_usage.prompt_tokens or 0
            metrics.output_tokens = response_usage.completion_tokens or 0
            if prompt_details := getattr(response_usage, "prompt_tokens_details", None):
                metrics.cache_read_tokens = getattr(prompt_details, "cached_tokens", 0) or 0
                metrics.audio_input_tokens = getattr(prompt_details, "audio_tokens", 0) or 0
            if completion_details := getattr(response_usage, "completion_tokens_details", None):
                metrics.reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0) or 0
                metrics.audio_output_tokens = getattr(completion_details, "audio_tokens", 0) or 0

        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

        return metrics

    def count_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        formatted_messages = self._format_messages(messages, compress_tool_results=True)
        formatted_tools = self._format_tools(tools) if tools else None
        tokens = litellm.token_counter(
            model=self.id,
            messages=formatted_messages,
            tools=formatted_tools,  # type: ignore
        )
        return tokens + count_schema_tokens(response_format, self.id)

    async def acount_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        return self.count_tokens(messages, tools, response_format)
