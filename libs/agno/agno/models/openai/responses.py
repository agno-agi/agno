import time
from dataclasses import dataclass
from typing import (Any, AsyncIterator, Dict, Iterable, Iterator, List,
                    Optional, Tuple, Union, cast)

import httpx
from openai import APIConnectionError  # Import APIConnectionError
from openai import APIStatusError  # Import APIStatusError
from openai import RateLimitError  # Import RateLimitError
from openai import AsyncOpenAI, OpenAI
from openai.types.chat import \
    ChatCompletionMessageParam  # Keep only the union type
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import File
from agno.models.base import MessageData, Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning
from agno.utils.models.openai_responses import (images_to_message,
                                                sanitize_response_schema)

# Define Response and ResponseStreamEvent types for clarity
Response = ChatCompletion
ResponseStreamEvent = ChatCompletionChunk


@dataclass
class OpenAIResponses(Model):
    """
    A class for interacting with OpenAI models using the Responses API.

    For more information, see: https://platform.openai.com/docs/api-reference/responses
    """

    id: str = "gpt-4o"
    name: str = "OpenAIResponses"
    provider: str = "OpenAI"
    supports_native_structured_outputs: bool = True

    # Request parameters
    include: Optional[List[str]] = None
    max_output_tokens: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    parallel_tool_calls: Optional[bool] = None
    reasoning: Optional[Dict[str, Any]] = None
    store: Optional[bool] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    truncation: Optional[str] = None
    user: Optional[str] = None
    response_format: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Dict[str, str]] = None
    default_query: Optional[Dict[str, str]] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # Parameters affecting built-in tools
    vector_store_name: str = "knowledge_base"

    # OpenAI clients
    client: Optional[OpenAI] = None
    async_client: Optional[AsyncOpenAI] = None

    # Internal parameters. Not used for API requests
    # Whether to use the structured outputs with this Model.
    structured_outputs: bool = False

    # The role to map the message role to.
    role_map = {
        "system": "developer",
        "user": "user",
        "assistant": "assistant",
        "tool": "tool",
    }

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
                log_error(
                    "OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable."
                )

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

    def get_request_params(self) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Define base request parameters
        base_params: Dict[str, Any] = {
            "include": self.include,
            "max_output_tokens": self.max_output_tokens,
            "metadata": self.metadata,
            "parallel_tool_calls": self.parallel_tool_calls,
            "reasoning": self.reasoning,
            "store": self.store,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "truncation": self.truncation,
            "user": self.user,
        }

        # Set the response format
        if self.response_format is not None:
            if self.structured_outputs and issubclass(self.response_format, BaseModel):
                schema = self.response_format.model_json_schema()
                # Sanitize the schema to ensure it complies with OpenAI's requirements
                sanitize_response_schema(schema)
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
        request_params: Dict[str, Any] = {
            k: v for k, v in base_params.items() if v is not None
        }

        if self.tool_choice is not None:
            request_params["tool_choice"] = self.tool_choice

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)
        return request_params

    def _upload_file(self, file: File) -> Optional[str]:
        """Upload a file to the OpenAI vector database."""

        if file.url is not None:
            file_content_tuple = file.file_url_content
            if file_content_tuple is not None:
                file_content = file_content_tuple[0]
            else:
                return None
            file_name = file.url.split("/")[-1]
            file_tuple = (file_name, file_content)
            result = self.get_client().files.create(
                file=file_tuple, purpose="assistants"
            )
            return result.id
        elif file.filepath is not None:
            import mimetypes
            from pathlib import Path

            file_path = (
                file.filepath
                if isinstance(file.filepath, Path)
                else Path(file.filepath)
            )
            if file_path.exists() and file_path.is_file():
                file_name = file_path.name
                file_content = file_path.read_bytes()  # type: ignore
                content_type = mimetypes.guess_type(file_path)[0]
                result = self.get_client().files.create(
                    file=(file_name, file_content, content_type),
                    purpose="assistants",  # type: ignore
                )
                return result.id
            else:
                raise ValueError(f"File not found: {file_path}")
        elif file.content is not None:
            result = self.get_client().files.create(
                file=file.content, purpose="assistants"
            )
            return result.id

        return None

    def _create_vector_store(self, file_ids: List[str]) -> str:
        """Create a vector store for the files."""
        # Corrected: Use client.beta.vector_stores
        vector_store = self.get_client().beta.vector_stores.create(
            name=self.vector_store_name
        )
        for file_id in file_ids:
            # Corrected: Use client.beta.vector_stores
            self.get_client().beta.vector_stores.files.create(
                vector_store_id=vector_store.id, file_id=file_id
            )
        while True:
            # Corrected: Use client.beta.vector_stores
            uploaded_files = self.get_client().beta.vector_stores.files.list(
                vector_store_id=vector_store.id
            )
            all_completed = True
            failed = False
            for file in uploaded_files:
                if file.status == "failed":
                    log_error(f"File {file.id} failed to upload.")
                    failed = True
                    break
                if file.status != "completed":
                    all_completed = False
            if all_completed or failed:
                break
            time.sleep(1)
        return vector_store.id

    def _format_tool_params(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Format the tool parameters for the OpenAI Responses API."""
        formatted_tools = []
        if self._tools:
            for _tool in self._tools:
                if _tool["type"] == "function":
                    _tool_dict = _tool["function"]
                    _tool_dict["type"] = "function"
                    for prop in _tool_dict["parameters"]["properties"].values():
                        if isinstance(prop["type"], list):
                            prop["type"] = prop["type"][0]

                    formatted_tools.append(_tool_dict)
                else:
                    formatted_tools.append(_tool)

        # Find files to upload to the OpenAI vector database
        file_ids = []
        for message in messages:
            # Upload any attached files to the OpenAI vector database
            if message.files is not None and len(message.files) > 0:
                for file in message.files:
                    file_id = self._upload_file(file)
                    if file_id is not None:
                        file_ids.append(file_id)

        vector_store_id = self._create_vector_store(file_ids) if file_ids else None

        # Add the file IDs to the tool parameters
        for _tool in formatted_tools:
            if _tool["type"] == "file_search" and vector_store_id is not None:
                _tool["vector_store_ids"] = [vector_store_id]

        return formatted_tools

    def _format_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            messages (List[Message]): The message to format.

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
                        message_dict["content"] = [
                            {"type": "input_text", "text": message.content}
                        ]
                        if message.images is not None:
                            message_dict["content"].extend(
                                images_to_message(images=message.images)
                            )

                if message.audio is not None and len(message.audio) > 0:
                    log_warning("Audio input is currently unsupported.")

                if message.videos is not None and len(message.videos) > 0:
                    log_warning("Video input is currently unsupported.")

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
                        {
                            "type": "function_call_output",
                            "call_id": message.tool_call_id,
                            "output": message.content,
                        }
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
            request_params = self.get_request_params()
            if self._tools:
                request_params["tools"] = self._format_tool_params(messages=messages)

            # Corrected: Use client.chat.completions.create and cast messages
            return self.get_client().chat.completions.create(
                model=self.id,
                messages=cast(
                    Iterable[ChatCompletionMessageParam],
                    self._format_messages(messages),
                ),
                **request_params,
            )
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
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
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
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
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e

    async def ainvoke(self, messages: List[Message]) -> Response:
        """
        Sends an asynchronous request to the OpenAI Responses API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Response: The response from the API.
        """
        try:
            request_params = self.get_request_params()
            if self._tools:
                request_params["tools"] = self._format_tool_params(messages=messages)
            # Corrected: Use client.chat.completions.create and cast messages
            return await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=cast(
                    Iterable[ChatCompletionMessageParam],
                    self._format_messages(messages),
                ),
                **request_params,
            )
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
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
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
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
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e

    def invoke_stream(self, messages: List[Message]) -> Iterator[ResponseStreamEvent]:
        """
        Send a streaming request to the OpenAI Responses API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Iterator[ResponseStreamEvent]: An iterator of response stream events.
        """
        try:
            request_params = self.get_request_params()
            if self._tools:
                request_params["tools"] = self._format_tool_params(messages=messages)
            # Corrected: Use client.chat.completions.create and cast messages
            yield from self.get_client().chat.completions.create(
                model=self.id,
                messages=cast(
                    Iterable[ChatCompletionMessageParam],
                    self._format_messages(messages),
                ),
                stream=True,
                **request_params,
            )  # type: ignore
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
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
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
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
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e

    async def ainvoke_stream(
        self, messages: List[Message]
    ) -> AsyncIterator[ResponseStreamEvent]:
        """
        Sends an asynchronous streaming request to the OpenAI Responses API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: An asynchronous iterator of chat completion chunks.
        """
        try:
            request_params = self.get_request_params()
            if self._tools:
                request_params["tools"] = self._format_tool_params(messages=messages)
            # Corrected: Use client.chat.completions.create and cast messages
            async_stream = await self.get_async_client().chat.completions.create(
                model=self.id,
                messages=cast(
                    Iterable[ChatCompletionMessageParam],
                    self._format_messages(messages),
                ),
                stream=True,
                **request_params,
            )
            async for chunk in async_stream:  # type: ignore
                yield chunk
        except RateLimitError as e:
            log_error(f"Rate limit error from OpenAI API: {e}")
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
            log_error(f"API connection error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e
        except APIStatusError as e:
            log_error(f"API status error from OpenAI API: {e}")
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
            log_error(f"Error from OpenAI API: {e}")
            raise ModelProviderError(
                message=str(e), model_name=self.name, model_id=self.id
            ) from e

    def format_function_call_results(
        self,
        messages: List[Message],
        function_call_results: List[Message],
        tool_call_ids: List[str],
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

        # Check if there are choices and a message in the first choice
        if not response.choices or not response.choices[0].message:
            # Handle cases where the response might be empty or malformed
            log_warning("OpenAI response does not contain expected choices or message.")
            # You might want to raise an error or return an empty/error ModelResponse
            # For now, returning the default empty response
            return model_response

        message = response.choices[0].message

        # Add role
        model_response.role = (
            message.role or "assistant"
        )  # Default to assistant if role is missing

        # Add content
        model_response.content = message.content

        # Add tool calls
        if message.tool_calls:
            model_response.tool_calls = []
            tool_call_ids = []
            for tool_call in message.tool_calls:
                if tool_call.type == "function":
                    model_response.tool_calls.append(
                        {
                            "id": tool_call.id,
                            # "call_id": tool_call.id, # OpenAI uses 'id' for tool calls
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                    )
                    tool_call_ids.append(tool_call.id)  # Use the tool_call.id

            if tool_call_ids:
                model_response.extra = model_response.extra or {}
                model_response.extra["tool_call_ids"] = tool_call_ids

        # Citations are not directly supported in the standard ChatCompletion response structure
        # If using specific features like file search that might add annotations,
        # this part would need custom handling based on how those annotations appear.
        # For now, removing the citation logic based on the old structure.

        # Reasoning content is not standard; removing related logic
        # if self.reasoning is not None:
        #     model_response.reasoning_content = response.output_text # Incorrect attribute

        # Add usage
        if response.usage:
            # Assuming response.usage matches the structure expected by ModelResponse.response_usage
            # If not, mapping might be needed. Example:
            model_response.response_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            # Add usage metrics to the assistant message (if applicable, might need adjustment)
            # self._add_usage_metrics_to_assistant_message(
            #     assistant_message=assistant_message, # assistant_message is not available here
            #     response_usage=model_response.response_usage,
            # )

        return model_response

    def _process_stream_response(
        self,
        stream_event: ResponseStreamEvent,  # This is ChatCompletionChunk
        assistant_message: Message,
        stream_data: MessageData,
        tool_use_accumulator: Dict[
            int, Dict[str, Any]
        ],  # Accumulator for tool calls by index
    ) -> Tuple[Optional[ModelResponse], Dict[int, Dict[str, Any]]]:
        """
        Common handler for processing stream responses from OpenAI.

        Args:
            stream_event: The streamed response chunk from OpenAI (ChatCompletionChunk)
            assistant_message: The assistant message being built
            stream_data: Data accumulated during streaming
            tool_use_accumulator: Accumulator for partial tool call data, keyed by index.

        Returns:
            Tuple containing the ModelResponse to yield (if any) and updated tool_use_accumulator
        """
        model_response = None

        if not stream_event.choices:
            return model_response, tool_use_accumulator

        delta = stream_event.choices[0].delta
        finish_reason = stream_event.choices[0].finish_reason

        # --- Handle Role --- (Usually only in the first chunk)
        if delta.role:
            assistant_message.role = delta.role
            # Update metrics on first actual response part (role or content)
            if not assistant_message.metrics.time_to_first_token:
                assistant_message.metrics.set_time_to_first_token()

        # --- Handle Content Delta ---
        if delta.content:
            model_response = ModelResponse(content=delta.content)
            stream_data.response_content += delta.content
            # Update metrics on first content token
            if not assistant_message.metrics.time_to_first_token:
                assistant_message.metrics.set_time_to_first_token()
            # Reasoning content is not standard, removing related logic
            # if self.reasoning is not None:
            #     model_response.reasoning_content = delta.content
            #     stream_data.response_thinking += delta.content

        # --- Handle Tool Call Deltas ---
        if delta.tool_calls:
            model_response = (
                ModelResponse()
            )  # Create response even if only tool calls change
            if assistant_message.tool_calls is None:
                assistant_message.tool_calls = []
            if model_response.tool_calls is None:
                model_response.tool_calls = []

            for tool_call_chunk in delta.tool_calls:
                index = tool_call_chunk.index
                if index not in tool_use_accumulator:
                    # First time seeing this index, initialize
                    tool_use_accumulator[index] = {
                        "id": tool_call_chunk.id or "",
                        "type": "function",  # Assuming function for now
                        "function": {"name": "", "arguments": ""},
                    }
                    # Add a placeholder to the main assistant message tool_calls list
                    # We will update this placeholder object directly later
                    if len(assistant_message.tool_calls) <= index:
                        assistant_message.tool_calls.extend(
                            [{}] * (index - len(assistant_message.tool_calls) + 1)
                        )
                    assistant_message.tool_calls[index] = tool_use_accumulator[index]

                # Accumulate data for the specific tool call index
                current_tool_call = tool_use_accumulator[index]
                if tool_call_chunk.id:
                    current_tool_call["id"] = tool_call_chunk.id
                if tool_call_chunk.function:
                    if tool_call_chunk.function.name:
                        current_tool_call["function"][
                            "name"
                        ] = tool_call_chunk.function.name
                    if tool_call_chunk.function.arguments:
                        current_tool_call["function"][
                            "arguments"
                        ] += tool_call_chunk.function.arguments

                # Add the *current state* of the tool call to the yielded response
                # This ensures the receiver gets updates as they happen
                # Ensure the list is long enough
                if len(model_response.tool_calls) <= index:
                    model_response.tool_calls.extend(
                        [{}] * (index - len(model_response.tool_calls) + 1)
                    )
                model_response.tool_calls[index] = (
                    current_tool_call.copy()
                )  # Yield a copy

        # --- Handle Finish Reason and Final Usage --- (In the last chunk)
        # Note: Usage info might be in stream_event.usage for some models/APIs, but typically
        # it's more reliable to get it from the final non-streaming response or handle it
        # after the stream completes if the API guarantees a final chunk with usage.
        # The standard ChatCompletionChunk doesn't guarantee usage in the delta.
        # Let's check stream_event.usage directly if available.
        if finish_reason:
            if (
                model_response is None
            ):  # Ensure we yield a final response if only finish_reason is set
                model_response = ModelResponse()
            # Add usage if available in the final chunk
            if hasattr(stream_event, "usage") and stream_event.usage:
                model_response.response_usage = {
                    "prompt_tokens": stream_event.usage.prompt_tokens,
                    "completion_tokens": stream_event.usage.completion_tokens,
                    "total_tokens": stream_event.usage.total_tokens,
                }
                self._add_usage_metrics_to_assistant_message(
                    assistant_message=assistant_message,
                    response_usage=model_response.response_usage,
                )
            # Clear the accumulator as the stream is ending for this request
            tool_use_accumulator.clear()

        return model_response, tool_use_accumulator

    def process_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
    ) -> Iterator[ModelResponse]:
        """Process the synchronous response stream."""
        tool_use_accumulator: Dict[int, Dict[str, Any]] = (
            {}
        )  # Changed from tool_use dict

        for stream_event in self.invoke_stream(messages=messages):
            model_response, tool_use_accumulator = self._process_stream_response(
                stream_event=stream_event,
                assistant_message=assistant_message,
                stream_data=stream_data,
                tool_use_accumulator=tool_use_accumulator,  # Pass accumulator
            )
            if model_response is not None:
                yield model_response

    async def aprocess_response_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        stream_data: MessageData,
    ) -> AsyncIterator[ModelResponse]:
        """Process the asynchronous response stream."""
        tool_use_accumulator: Dict[int, Dict[str, Any]] = (
            {}
        )  # Changed from tool_use dict

        async for stream_event in self.ainvoke_stream(messages=messages):
            model_response, tool_use_accumulator = self._process_stream_response(
                stream_event=stream_event,
                assistant_message=assistant_message,
                stream_data=stream_data,
                tool_use_accumulator=tool_use_accumulator,  # Pass accumulator
            )
            if model_response is not None:
                yield model_response
