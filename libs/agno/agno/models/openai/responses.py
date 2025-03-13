from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.models.base import MessageData, Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger
from agno.utils.openai_responses import images_to_message

try:
    import importlib.metadata as metadata

    from openai import APIConnectionError, APIStatusError, AsyncOpenAI, OpenAI, RateLimitError
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
        raise ImportError("OpenAI not installed. Install with `pip install openai -U`") from e
    else:
        raise ImportError("Missing dependencies. Install with `pip install packaging importlib-metadata`") from e


@dataclass
class OpenAIResponses(Model):
    """
    Implementation for the OpenAI Responses API using direct chat completions.

    For more information, see: https://platform.openai.com/docs/api-reference/responses
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
        from os import getenv

        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("OPENAI_API_KEY")
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
        if self.reasoning_effort is not None:
            base_params["reasoning"] = {
                "effort": self.reasoning_effort,
            }

        if self.response_format is not None:
            if self.structured_outputs and isinstance(self.response_format, BaseModel):
                schema = self.response_format.model_json_schema()
                schema["additionalProperties"] = False
                base_params["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": self.response_format.__name__,
                        "schema": schema,
                        "strict": True,
                    }
                }
            else:
                # JSON mode
                base_params["text"] = {"format": {"type": "json_object"}}

        # Filter out None values
        request_params: Dict[str, Any] = {k: v for k, v in base_params.items() if v is not None}

        if self.web_search:
            request_params.setdefault("tools", [])  # type: ignore
            request_params["tools"].append({"type": "web_search_preview"})

        # Add tools
        if self._functions is not None and len(self._functions) > 0:
            request_params.setdefault("tools", [])  # type: ignore
            for function in self._functions.values():
                function_dict = function.to_dict()
                for prop in function_dict["parameters"]["properties"].values():
                    if isinstance(prop["type"], list):
                        prop["type"] = prop["type"][0]
                request_params["tools"].append({"type": "function", **function_dict})
        if self.tool_choice is not None:
            request_params["tool_choice"] = self.tool_choice

        return request_params

    def _format_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        formatted_messages: List[Dict[str, Any]] = []
        for message in messages:
            if message.role in ["user", "system"]:
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

                formatted_messages.append(message_dict)

            else:
                # OpenAI expects the tool_calls to be None if empty, not an empty list
                if message.tool_calls is not None and len(message.tool_calls) > 0:
                    for tool_call in message.tool_calls:
                        formatted_messages.append(
                            {
                                "type": "function_call",
                                "id": tool_call["id"],
                                "call_id": tool_call["call_id"],
                                "name": tool_call["function"]["name"],
                                "arguments": tool_call["function"]["arguments"],
                                "status": "completed",
                            }
                        )

                if message.role == "tool":
                    formatted_messages.append(
                        {"type": "function_call_output", "call_id": message.tool_call_id, "output": message.content}
                    )
        return formatted_messages

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
                input=self._format_messages(messages),  # type: ignore
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
                input=self._format_messages(messages),  # type: ignore
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
                input=self._format_messages(messages),  # type: ignore
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
                input=self._format_messages(messages),  # type: ignore
                stream=True,
                **self.request_kwargs,
            )
            async for chunk in async_stream:  # type: ignore
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

    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], tool_call_ids: List[str]
    ) -> None:
        """
        Handle the results of function calls.

        Args:
            messages (List[Message]): The list of conversation messages.
            function_call_results (List[Message]): The results of the function calls.
            tool_ids (List[str]): The tool ids.
        """
        if len(function_call_results) > 0:
            for _fc_message_index, _fc_message in enumerate(function_call_results):
                _fc_message.tool_call_id = tool_call_ids[_fc_message_index]
                messages.append(_fc_message)

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
                message=response.error.message,
                model_name=self.name,
                model_id=self.id,
            )

        # Add role
        model_response.role = "assistant"
        for output in response.output:
            if output.type == "message":
                # TODO: Support citations/annotations
                model_response.content = response.output_text
            elif output.type == "function_call":
                if model_response.tool_calls is None:
                    model_response.tool_calls = []
                model_response.tool_calls.append(
                    {
                        "id": output.id,
                        "call_id": output.call_id,
                        "type": "function",
                        "function": {
                            "name": output.name,
                            "arguments": output.arguments,
                        },
                    }
                )

                model_response.extra = model_response.extra or {}
                model_response.extra.setdefault("tool_call_ids", []).append(output.call_id)

        # i.e. we asked for reasoning, so we need to add the reasoning content
        if self.reasoning_effort:
            model_response.reasoning_content = response.output_text

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

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
        model_response = None

        if stream_event.type == "response.created":
            # Update metrics
            if not assistant_message.metrics.time_to_first_token:
                assistant_message.metrics.set_time_to_first_token()

        elif stream_event.type == "response.output_text.delta":
            model_response = ModelResponse()
            # Add content
            model_response.content = stream_event.delta
            stream_data.response_content += stream_event.delta

            if self.reasoning_effort:
                model_response.reasoning_content = stream_event.delta
                stream_data.response_thinking += stream_event.delta

        elif stream_event.type == "response.output_item.added":
            item = stream_event.item
            if item.type == "function_call":
                tool_use = {
                    "id": item.id,
                    "call_id": item.call_id,
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": item.arguments,
                    },
                }

        elif stream_event.type == "response.function_call_arguments.delta":
            tool_use["function"]["arguments"] += stream_event.delta

        elif stream_event.type == "response.output_item.done" and tool_use:
            model_response = ModelResponse()
            model_response.tool_calls = [tool_use]
            if assistant_message.tool_calls is None:
                assistant_message.tool_calls = []
            assistant_message.tool_calls.append(tool_use)

            stream_data.extra = stream_data.extra or {}
            stream_data.extra.setdefault("tool_call_ids", []).append(tool_use["call_id"])
            tool_use = {}

        elif stream_event.type == "response.completed":
            model_response = ModelResponse()
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
                stream_event=stream_event,
                assistant_message=assistant_message,
                stream_data=stream_data,
                tool_use=tool_use,
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
                stream_event=stream_event,
                assistant_message=assistant_message,
                stream_data=stream_data,
                tool_use=tool_use,
            )
            if model_response is not None:
                yield model_response

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:  # type: ignore
        pass
