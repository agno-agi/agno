from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Mapping, Optional

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning

try:
    import litellm
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
                log_warning("LITELLM_API_KEY not set. Please set the LITELLM_API_KEY environment variable.")

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

            formatted_messages.append(msg)

        return formatted_messages

    @property
    def request_kwargs(self) -> Dict[str, Any]:
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
        if self._tools:
            base_params["tools"] = self._tools
            base_params["tool_choice"] = "auto"

        # Add additional request params if provided
        request_params: Dict[str, Any] = {k: v for k, v in base_params.items() if v is not None}
        if self.request_params:
            request_params.update(self.request_params)

        return request_params

    def invoke(self, messages: List[Message]) -> Mapping[str, Any]:
        """Sends a chat completion request to the LiteLLM API."""
        completion_kwargs = self.request_kwargs
        completion_kwargs["messages"] = self._format_messages(messages)
        return self.get_client().completion(**completion_kwargs)

    def invoke_stream(self, messages: List[Message]) -> Iterator[Mapping[str, Any]]:
        """Sends a streaming chat completion request to the LiteLLM API."""
        completion_kwargs = self.request_kwargs
        completion_kwargs["messages"] = self._format_messages(messages)
        completion_kwargs["stream"] = True
        
        try:
            iterator = self.get_client().completion(**completion_kwargs)
            tool_call_buffer = None
            
            for chunk in iterator:
                chunk, tool_call_buffer = self._process_tool_call_chunk(chunk, tool_call_buffer)
                yield chunk
        except Exception as e:
            log_error(f"Error in streaming response: {e}")
            raise

    async def ainvoke(self, messages: List[Message]) -> Mapping[str, Any]:
        """Sends an asynchronous chat completion request to the LiteLLM API."""
        completion_kwargs = self.request_kwargs
        completion_kwargs["messages"] = self._format_messages(messages)
        return await self.get_client().acompletion(**completion_kwargs)

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[Any]:
        """Sends an asynchronous streaming chat request to the LiteLLM API and handles tool calls."""
        completion_kwargs = self.request_kwargs
        completion_kwargs["messages"] = self._format_messages(messages)
        completion_kwargs["stream"] = True

        try:
            # Get the async iterator from the LiteLLM client
            async_stream = await self.get_client().acompletion(**completion_kwargs)
            
            # Buffer to accumulate tool call fragments
            tool_call_buffer = None
            
            async for chunk in async_stream:
                chunk, tool_call_buffer = self._process_tool_call_chunk(chunk, tool_call_buffer)
                yield chunk
                
        except Exception as e:
            log_error(f"Error in streaming response: {e}")
            raise

    def parse_provider_response(self, response: Any) -> ModelResponse:
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

        if hasattr(response, "usage"):
            model_response.response_usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return model_response

    def parse_provider_response_delta(self, response_delta: Any) -> ModelResponse:
        """Parse the provider response delta for streaming responses."""
        model_response = ModelResponse()

        if hasattr(response_delta, "choices") and len(response_delta.choices) > 0:
            delta = response_delta.choices[0].delta

            if hasattr(delta, "content") and delta.content is not None:
                model_response.content = delta.content

            if hasattr(delta, "tool_calls") and delta.tool_calls:
                model_response.tool_calls = []
                for tool_call in delta.tool_calls:
                    if tool_call.type == "function":
                        model_response.tool_calls.append(
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments,
                                },
                            }
                        )

        return model_response
    
    def _process_tool_call_chunk(self, chunk: Any, tool_call_buffer: Any) -> tuple[Any, Any]:
        """Process a chunk with tool calls and manage the tool call buffer.
        
        Args:
            chunk: The current response chunk
            tool_call_buffer: The current tool call buffer
            
        Returns:
            tuple: (processed_chunk, updated_tool_call_buffer)
        """
        delta = chunk.choices[0].delta
        
        # Handle case with no tool calls or stream is finished
        if delta.tool_calls is None or chunk.choices[0].finish_reason is not None:
            # If there's a pending tool call, send it
            if tool_call_buffer is not None:
                chunk.choices[0].delta.tool_calls = [tool_call_buffer]
                tool_call_buffer = None
            return chunk, tool_call_buffer
            
        # Handle exception case: multiple tool calls
        if len(delta.tool_calls) > 1:
            log_error(f"Multiple tool calls detected in the chunk: {chunk}")
            return chunk, tool_call_buffer
            
        # Handle single tool call
        current_tool_call = delta.tool_calls[0]
        # Clean up the tool call in current chunk to prevent duplication
        delta.tool_calls = None
        
        # Handle start of a new tool call (has ID)
        if current_tool_call.id is not None and current_tool_call.id != '':
            # If there's a previous tool call buffer, include it in this chunk
            if tool_call_buffer is not None:
                chunk.choices[0].delta.tool_calls = [tool_call_buffer]
                tool_call_buffer = None
            
            # Start a new tool call buffer
            tool_call_buffer = current_tool_call
        # Handle streaming of tool call arguments (no ID)
        elif tool_call_buffer is not None:
            # Accumulate arguments
            tool_call_buffer.function.arguments += current_tool_call.function.arguments
        
        return chunk, tool_call_buffer
