import json
from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Mapping, Optional, Type, Union

from pydantic import BaseModel

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning

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
    request_params: Optional[Dict[str, Any]] = None

    client: Optional[Any] = None

    def __post_init__(self):
        """Initialize the model after the dataclass initialization."""
        super().__post_init__()

        # Set up API key from environment variable if not already set
        if not self.api_key:
            self.api_key = getenv("LITELLM_API_KEY")
            if not self.api_key:
                # Check for other present valid keys, e.g. OPENAI_API_KEY if self.id is an OpenAI model
                env_validation = validate_environment(model=self.id, api_base=self.api_base)
                if not env_validation.get("keys_in_environment"):
                    log_warning(
                        "Missing required key. Please set the LITELLM_API_KEY or other valid environment variables."
                    )

    def get_client(self) -> Any:
        """
        Returns a LiteLLM client.

        Returns:
            Any: An instance of the LiteLLM client.
        """
        if self.client is not None:
            return self.client

        self.client = litellm
        return self.client

    def _format_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Format messages for LiteLLM API."""
        formatted_messages = []
        for m in messages:
            msg = {"role": m.role, "content": m.content if m.content is not None else ""}

            # Handle tool calls in assistant messages
            if m.role == "assistant" and m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id", f"call_{i}"),
                        "type": "function",
                        "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                    }
                    for i, tc in enumerate(m.tool_calls)
                ]

            # Handle tool responses
            if m.role == "tool":
                msg["tool_call_id"] = m.tool_call_id or ""
                msg["name"] = m.name or ""

                if m.audio is not None and len(m.audio) > 0:
                    log_warning("Audio input is currently unsupported.")

                if m.images is not None and len(m.images) > 0:
                    log_warning("Image input is currently unsupported.")

                if m.files is not None and len(m.files) > 0:
                    log_warning("File input is currently unsupported.")

                if m.videos is not None and len(m.videos) > 0:
                    log_warning("Video input is currently unsupported.")

            formatted_messages.append(msg)

        return formatted_messages

    def get_request_kwargs(self, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
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
        if tools:
            base_params["tools"] = tools
            base_params["tool_choice"] = "auto"

        # Add additional request params if provided
        request_params: Dict[str, Any] = {k: v for k, v in base_params.items() if v is not None}
        if self.request_params:
            request_params.update(self.request_params)

        return request_params

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Mapping[str, Any]:
        """Sends a chat completion request to the LiteLLM API."""
        completion_kwargs = self.get_request_kwargs(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages)
        return self.get_client().completion(**completion_kwargs)

    def invoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Iterator[Mapping[str, Any]]:
        """Sends a streaming chat completion request to the LiteLLM API."""
        completion_kwargs = self.get_request_kwargs(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages)
        completion_kwargs["stream"] = True
        return self.get_client().completion(**completion_kwargs)

    async def ainvoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Mapping[str, Any]:
        """Sends an asynchronous chat completion request to the LiteLLM API."""
        completion_kwargs = self.get_request_kwargs(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages)
        return await self.get_client().acompletion(**completion_kwargs)

    async def ainvoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncIterator[Any]:
        """Sends an asynchronous streaming chat request to the LiteLLM API."""
        completion_kwargs = self.get_request_kwargs(tools=tools)
        completion_kwargs["messages"] = self._format_messages(messages)
        completion_kwargs["stream"] = True

        try:
            # litellm.acompletion returns a coroutine that resolves to an async iterator
            # We need to await it first to get the actual async iterator
            async_stream = await self.get_client().acompletion(**completion_kwargs)
            async for chunk in async_stream:
                yield chunk
        except Exception as e:
            log_error(f"Error in streaming response: {e}")
            raise

    def parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        """Parse the provider response."""
        model_response = ModelResponse()

        response_message = response.choices[0].message

        if response_message.content is not None:
            model_response.content = response_message.content

        if hasattr(response_message, "tool_calls") and response_message.tool_calls:
            model_response.tool_calls = []
            for tool_call in response_message.tool_calls:
                model_response.tool_calls.append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments},
                    }
                )

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """Parse the provider response delta for streaming responses."""
        model_response = ModelResponse()

        if hasattr(response_delta, "choices") and len(response_delta.choices) > 0:
            delta = response_delta.choices[0].delta

            if hasattr(delta, "content") and delta.content is not None:
                model_response.content = delta.content

            if hasattr(delta, "tool_calls") and delta.tool_calls:
                processed_tool_calls = []
                for i, tool_call in enumerate(delta.tool_calls):
                    # Create a basic structure with index
                    tool_call_dict = {"index": i, "type": "function"}

                    # Extract ID if available
                    if hasattr(tool_call, "id") and tool_call.id is not None:
                        tool_call_dict["id"] = tool_call.id

                    # Extract function data
                    function_data = {}
                    if hasattr(tool_call, "function"):
                        if hasattr(tool_call.function, "name") and tool_call.function.name is not None:
                            function_data["name"] = tool_call.function.name
                        if hasattr(tool_call.function, "arguments") and tool_call.function.arguments is not None:
                            function_data["arguments"] = tool_call.function.arguments

                    tool_call_dict["function"] = function_data
                    processed_tool_calls.append(tool_call_dict)

                model_response.tool_calls = processed_tool_calls

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
