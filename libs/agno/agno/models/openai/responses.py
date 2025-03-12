from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union
import asyncio
from agno.media import AudioResponse
from agno.models.response import ModelResponse
from agno.utils.openai_responses import images_to_message
import httpx

from agno.exceptions import ModelProviderError
from agno.models.base import MessageData, Model
from agno.models.message import Message
from agno.utils.log import logger


try:
    import importlib.metadata as metadata

    from openai import AsyncOpenAI, OpenAI
    from openai import APIConnectionError, APIStatusError, RateLimitError
    from openai.resources.responses.responses import Response, ResponseStreamEvent

    from packaging import version

    # Get installed OpenAI version
    openai_version = metadata.version("openai")

    # Check version compatibility
    parsed_version = version.parse(openai_version)
    if parsed_version.major == 0 and parsed_version.minor < 66:
        import warnings
        warnings.warn("OpenAI v1.66.0 or higher is recommended for the Responses API", UserWarning)

except ImportError as e:
    # Handle different import error scenarios
    if "openai" in str(e):
        raise ImportError("OpenAI not installed. Install with `pip install openai`") from e
    else:
        raise ImportError("Missing dependencies. Install with `pip install packaging importlib-metadata`") from e


@dataclass
class OpenAIResponses(Model):
    """
    Implementation for the OpenAI Responses API using direct chat completions.

    For more information, see: https://platform.openai.com/docs/api-reference/chat
    """

    id: str = "gpt-4o"
    name: str = "OpenAIResponses"
    provider: str = "OpenAI"
    supports_structured_outputs: bool = True

    # API configuration
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Dict[str, str]] = None
    default_query: Optional[Dict[str, str]] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # Response parameters
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_output_tokens: Optional[int] = None
    response_format: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None
    store: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    reasoning_summary: Optional[str] = None

    # Built-in tools
    web_search: bool = False


    # The role to map the message role to.
    role_map = {
        "system": "developer",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }


    # OpenAI clients
    client: Optional[OpenAI] = None
    async_client: Optional[AsyncOpenAI] = None

    # Internal parameters. Not used for API requests
    # Whether to use the structured outputs with this Model.
    structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Get client parameters for API requests.

        Returns:
            Dict[str, Any]: Client parameters
        """
        import os

        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                logger.error("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        # Define base client params
        base_params = {
            "api_key": self.api_key,
            "organization": self.organization,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Create client_params dict with non-None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def get_client(self) -> OpenAI:
        """
        Returns an OpenAI client.

        Returns:
            OpenAI: An instance of the OpenAI client.
        """
        if self.client:
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client

        self.client = OpenAI(**client_params)
        return self.client

    def get_async_client(self) -> AsyncOpenAI:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncOpenAI: An instance of the asynchronous OpenAI client.
        """
        if self.async_client:
            return self.async_client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client:
            client_params["http_client"] = self.http_client
        else:
            # Create a new async HTTP client with custom limits
            client_params["http_client"] = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=1000, max_keepalive_connections=100)
            )

        self.async_client = AsyncOpenAI(**client_params)
        return self.async_client


    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params = {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "metadata": self.metadata,
            "store": self.store,
        }
        if self.reasoning_effort is not None or self.reasoning_summary is not None:
            base_params["reasoning"] = {
                "effort": self.reasoning_effort,
                "summary": self.reasoning_summary,
            }

        if self.response_format is not None:
            if self.structured_outputs:
                base_params["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": self.response_model.__name__,
                        "schema": self.response_model.model_json_schema(),
                        "strict": True,
                    }
                }
            else:
                # JSON mode
                base_params["text"] = {"format": { "type": "json_object" }}

        # Filter out None values
        request_params = {k: v for k, v in base_params.items() if v is not None}

        if self.web_search:
            request_params.setdefault("tools", [])
            request_params["tools"].append({"type": "web_search_preview"})

        # Add tools
        if self._tools is not None and len(self._tools) > 0:
            request_params.setdefault("tools", [])
            request_params["tools"].extend(self._tools)

        if self.tool_choice is not None:
            request_params["tool_choice"] = self.tool_choice

        return request_params

    def _format_message(self, message: Message) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        message_dict: Dict[str, Any] = {
            "role": self.role_map[message.role],
            "content": message.content,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if message.images is not None and len(message.images) > 0:
            # Ignore non-string message content
            # because we assume that the images/audio are already added to the message
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "input_text", "text": message.content}]
                if message.images is not None:
                    message_dict["content"].extend(images_to_message(images=message.images))

        # TODO: File support

        if message.audio is not None:
            logger.warning("Audio input is currently unsupported.")

        if message.videos is not None:
            logger.warning("Video input is currently unsupported.")

        # OpenAI expects the tool_calls to be None if empty, not an empty list
        if message.tool_calls is not None and len(message.tool_calls) == 0:
            message_dict["tool_calls"] = None

        return message_dict

    def invoke(self, messages: List[Message]) -> Response:
        """
        Send a request to the OpenAI Responses API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Response: The response from the API.
        """
        try:

            return self.get_client().responses.create(
                model=self.id,
                input=[self._format_message(m) for m in messages],  # type: ignore
                **self.request_kwargs,
            )
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(self, messages: List[Message]) -> Response:
        """
        Sends an asynchronous request to the OpenAI Responses API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Response: The response from the API.
        """
        try:

            return await self.get_async_client().responses.create(
                model=self.id,
                input=[self._format_message(m) for m in messages],  # type: ignore
                **self.request_kwargs,
            )
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[ResponseStreamEvent]:
        """
        Send a streaming request to the OpenAI Responses API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ResponseStreamEvent]: An iterator of response stream events.
        """
        try:
            yield from self.get_client().responses.create(
                model=self.id,
                input=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                **self.request_kwargs,
            )  # type: ignore
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[ResponseStreamEvent]:
        """
        Sends an asynchronous streaming request to the OpenAI Responses API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chat completion chunks.
        """
        try:
            async_stream = await self.get_async_client().responses.create(
                model=self.id,
                input=[self._format_message(m) for m in messages],  # type: ignore
                stream=True,
                **self.request_kwargs,
            )
            async for chunk in async_stream:
                yield chunk
        except RateLimitError as e:
            logger.error(f"Rate limit error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except APIConnectionError as e:
            logger.error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            logger.error(f"API status error from OpenAI API: {e}")
            error_message = e.response.json().get("error", {})
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=e.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from e
        except Exception as e:
            logger.error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def parse_provider_response(self, response: Response) -> ModelResponse:
        """
        Parse the OpenAI response into a ModelResponse.

        Args:
            response: Response from invoke() method

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        if response.error:
            raise ModelProviderError(
                message=response.error.get("message", "Unknown model error"),
                model_name=self.name,
                model_id=self.id,
            )
        
        # Add role
        model_response.role = "assistant"

        for output in response.output:
            if output.type == "message":
                if model_response.content is None:
                    model_response.content = ""
                # TODO: Support citations/annotations
                for content in output.content:
                    if content.type == "output_text":
                        model_response.content += content.text
            elif output.type == "function_call":
                if model_response.tool_calls is None:
                    model_response.tool_calls = []
                model_response.tool_calls.append(
                    {
                        "id": output.id,
                        "name": output.name,
                        "arguments": output.arguments,
                    }
                )

        # i.e. we asked for reasoning, so we need to add the reasoning content
        if self.reasoning_effort:
            model_response.reasoning_content = response.output_text

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response



    # Override base method
    @staticmethod
    def parse_tool_calls(tool_calls_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build tool calls from streamed tool call data.

        Args:
            tool_calls_data (List[Dict[str, Any]]): The tool call data to build from.

        Returns:
            List[Dict[str, Any]]: The built tool calls.
        """
        tool_calls: List[Dict[str, Any]] = []
        for _tool_call in tool_calls_data:
            _index = _tool_call.index or 0
            _tool_call_id = _tool_call.id
            _tool_call_type = _tool_call.type
            _function_name = _tool_call.function.name if _tool_call.function else None
            _function_arguments = _tool_call.function.arguments if _tool_call.function else None

            if len(tool_calls) <= _index:
                tool_calls.extend([{}] * (_index - len(tool_calls) + 1))
            tool_call_entry = tool_calls[_index]
            if not tool_call_entry:
                tool_call_entry["id"] = _tool_call_id
                tool_call_entry["type"] = _tool_call_type
                tool_call_entry["function"] = {
                    "name": _function_name or "",
                    "arguments": _function_arguments or "",
                }
            else:
                if _function_name:
                    tool_call_entry["function"]["name"] += _function_name
                if _function_arguments:
                    tool_call_entry["function"]["arguments"] += _function_arguments
                if _tool_call_id:
                    tool_call_entry["id"] = _tool_call_id
                if _tool_call_type:
                    tool_call_entry["type"] = _tool_call_type
        return tool_calls
    

    def _process_stream_response(
        self,
        stream_event: ResponseStreamEvent,
        assistant_message: Message,
        stream_data: MessageData,
        tool_use: Dict[str, Any],
    ) -> Tuple[Optional[ModelResponse], Dict[str, Any]]:
        """
        Common handler for processing stream responses from Cohere.

        Args:
            response: The streamed response from Cohere
            assistant_message: The assistant message being built
            stream_data: Data accumulated during streaming
            tool_use: Current tool use data being built

        Returns:
            Tuple containing the ModelResponse to yield and updated tool_use dict
        """
        model_response = ModelResponse()

        if stream_event.type == "response.created":
            # Update metrics
            if not assistant_message.metrics.time_to_first_token:
                assistant_message.metrics.set_time_to_first_token()

        elif stream_event.type == "response.output_text.delta":

            # Add content
            model_response.content = stream_event.delta
            stream_data.response_content += stream_event.delta

        elif stream_event.type == "response.output_item.added":
            item = stream_event.item
            if item.type == "function_call":
                tool_use = {
                    "id": item.id,
                    "name": item.name,
                    "arguments": item.arguments,
                }

        elif stream_event.type == "response.function_call_arguments.delta":
            tool_use["arguments"] += stream_event.delta

        elif stream_event.type == "response.output_item.done":
            if assistant_message.tool_calls is None:
                assistant_message.tool_calls = []
            assistant_message.tool_calls.append(tool_use)
            tool_use = {}

        elif stream_event.type == "response.completed":
            # Add usage metrics if present
            if stream_event.response.usage is not None:
                model_response.response_usage = stream_event.response.usage

            self._add_usage_metrics_to_assistant_message(
                assistant_message=assistant_message,
                response_usage=model_response.response_usage,
            )

        return model_response, tool_use

    def process_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data: MessageData
    ) -> Iterator[ModelResponse]:
        """Process the synchronous response stream."""
        tool_use: Dict[str, Any] = {}

        for stream_event in self.invoke_stream(messages=messages):
            model_response, tool_use = self._process_stream_response(
                stream_event=stream_event, assistant_message=assistant_message, stream_data=stream_data, tool_use=tool_use
            )
            if model_response is not None:
                yield model_response

    async def aprocess_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data: MessageData
    ) -> AsyncIterator[ModelResponse]:
        """Process the asynchronous response stream."""
        tool_use: Dict[str, Any] = {}

        async for stream_event in self.ainvoke_stream(messages=messages):
            model_response, tool_use = self._process_stream_response(
                stream_event=stream_event, assistant_message=assistant_message, stream_data=stream_data, tool_use=tool_use
            )
            if model_response is not None:
                yield model_response

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:  # type: ignore
        pass