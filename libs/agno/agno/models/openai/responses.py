import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Type, Union

import httpx
from pydantic import BaseModel
from typing_extensions import Literal

from agno.exceptions import ContextWindowExceededError, ModelAuthenticationError, ModelProviderError
from agno.media import File
from agno.models.base import Model
from agno.models.message import Citations, Message, UrlCitation
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.tools.function import Function
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.models.openai_responses import images_to_message
from agno.utils.models.schema_utils import get_response_schema_for_provider
from agno.utils.tokens import count_schema_tokens

try:
    from openai import APIConnectionError, APIStatusError, AsyncOpenAI, OpenAI, RateLimitError
    from openai.types.responses import Response, ResponseReasoningItem, ResponseStreamEvent, ResponseUsage
except ImportError as e:
    raise ImportError("`openai` not installed. Please install using `pip install openai -U`") from e


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
    max_tool_calls: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    parallel_tool_calls: Optional[bool] = None
    reasoning: Optional[Dict[str, Any]] = None
    verbosity: Optional[Literal["low", "medium", "high"]] = None
    reasoning_effort: Optional[Literal["minimal", "low", "medium", "high"]] = None
    reasoning_summary: Optional[Literal["auto", "concise", "detailed"]] = None
    store: Optional[bool] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    truncation: Optional[Literal["auto", "disabled"]] = None
    user: Optional[str] = None
    service_tier: Optional[Literal["auto", "default", "flex", "priority"]] = None
    strict_output: bool = True  # When True, guarantees schema adherence for structured outputs. When False, attempts to follow schema as a guide but may occasionally deviate
    background: Optional[bool] = (
        None  # When True, enables background mode for long-running tasks. The API returns immediately and the response is polled until completion. Not supported for streaming.
    )
    background_poll_interval: float = (
        2.0  # Interval in seconds between polling attempts when background mode is enabled.
    )
    background_max_wait: float = 600.0  # Maximum time in seconds to wait for a background response before cancelling it and raising an error. Defaults to 10 minutes, matching OpenAI's storage window.
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    extra_body: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Dict[str, str]] = None
    default_query: Optional[Dict[str, str]] = None
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
    client_params: Optional[Dict[str, Any]] = None

    # Parameters affecting built-in tools
    vector_store_name: str = "knowledge_base"

    # OpenAI clients
    client: Optional[OpenAI] = None
    async_client: Optional[AsyncOpenAI] = None

    # The role to map the message role to.
    role_map: Dict[str, str] = field(
        default_factory=lambda: {
            "system": "developer",
            "user": "user",
            "assistant": "assistant",
            "tool": "tool",
        }
    )

    def get_provider(self) -> str:
        return f"{super().get_provider()} Responses"

    def _using_reasoning_model(self) -> bool:
        """Return True if the contextual used model is a known reasoning model."""
        return self.id.startswith("o3") or self.id.startswith("o4-mini") or self.id.startswith("gpt-5")

    def _set_reasoning_request_param(self, base_params: Dict[str, Any]) -> Dict[str, Any]:
        """Set the reasoning request parameter."""
        base_params["reasoning"] = self.reasoning or {}

        if self.reasoning_effort is not None:
            base_params["reasoning"]["effort"] = self.reasoning_effort

        if self.reasoning_summary is not None:
            base_params["reasoning"]["summary"] = self.reasoning_summary

        return base_params

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
                raise ModelAuthenticationError(
                    message="OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.",
                    model_name=self.name,
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
        Returns an OpenAI client. Caches the client to avoid recreating it on every request.

        Returns:
            OpenAI: An instance of the OpenAI client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        # When no custom http_client is provided, let the OpenAI SDK use its own default client.
        # The SDK defaults to HTTP/1.1 which avoids transient 400 errors caused by HTTP/2
        # protocol edge cases with OpenAI's infrastructure.

        self.client = OpenAI(**client_params)
        return self.client

    def get_async_client(self) -> AsyncOpenAI:
        """
        Returns an asynchronous OpenAI client. Caches the client to avoid recreating it on every request.

        Returns:
            AsyncOpenAI: An instance of the asynchronous OpenAI client.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        client_params: Dict[str, Any] = self._get_client_params()
        if self.http_client and isinstance(self.http_client, httpx.AsyncClient):
            client_params["http_client"] = self.http_client
        # When no custom http_client is provided, let the OpenAI SDK use its own default client.
        # The SDK defaults to HTTP/1.1 which avoids transient 400 errors caused by HTTP/2
        # protocol edge cases with OpenAI's infrastructure.

        self.async_client = AsyncOpenAI(**client_params)
        return self.async_client

    def _poll_background_response(self, response_id: str) -> "Response":
        """Poll for a background response until it reaches a terminal state.

        If background_max_wait is exceeded, cancels the response and raises ModelProviderError.
        """
        client = self.get_client()
        deadline = time.monotonic() + self.background_max_wait
        while True:
            response = client.responses.retrieve(response_id)
            log_debug(f"Background response {response_id} status: {response.status}")
            if response.status in ("completed", "failed", "incomplete", "cancelled"):
                return response
            if time.monotonic() >= deadline:
                log_warning(
                    f"Background response {response_id} exceeded max wait of {self.background_max_wait}s, cancelling."
                )
                try:
                    client.responses.cancel(response_id)
                except Exception as cancel_exc:
                    log_warning(f"Failed to cancel background response {response_id}: {cancel_exc}")
                raise ModelProviderError(
                    message=f"Background response {response_id} exceeded max wait of {self.background_max_wait}s",
                    model_name=self.name,
                    model_id=self.id,
                )
            time.sleep(self.background_poll_interval)

    async def _apoll_background_response(self, response_id: str) -> "Response":
        """Async poll for a background response until it reaches a terminal state.

        If background_max_wait is exceeded, cancels the response and raises ModelProviderError.
        """
        client = self.get_async_client()
        deadline = time.monotonic() + self.background_max_wait
        while True:
            response = await client.responses.retrieve(response_id)
            log_debug(f"Background response {response_id} status: {response.status}")
            if response.status in ("completed", "failed", "incomplete", "cancelled"):
                return response
            if time.monotonic() >= deadline:
                log_warning(
                    f"Background response {response_id} exceeded max wait of {self.background_max_wait}s, cancelling."
                )
                try:
                    await client.responses.cancel(response_id)
                except Exception as cancel_exc:
                    log_warning(f"Failed to cancel background response {response_id}: {cancel_exc}")
                raise ModelProviderError(
                    message=f"Background response {response_id} exceeded max wait of {self.background_max_wait}s",
                    model_name=self.name,
                    model_id=self.id,
                )
            await asyncio.sleep(self.background_poll_interval)

    def get_request_params(
        self,
        messages: Optional[List[Message]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Returns keyword arguments for API requests.

        Returns:
            Dict[str, Any]: A dictionary of keyword arguments for API requests.
        """
        # Background mode requires store=True
        store = self.store
        if self.background:
            store = True

        # Define base request parameters
        base_params: Dict[str, Any] = {
            "background": self.background,
            "include": self.include,
            "max_output_tokens": self.max_output_tokens,
            "max_tool_calls": self.max_tool_calls,
            "metadata": self.metadata,
            "parallel_tool_calls": self.parallel_tool_calls,
            "store": store,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "truncation": self.truncation,
            "user": self.user,
            "service_tier": self.service_tier,
            "extra_headers": self.extra_headers,
            "extra_query": self.extra_query,
            "extra_body": self.extra_body,
        }
        # Populate the reasoning parameter
        base_params = self._set_reasoning_request_param(base_params)

        # Build text parameter
        text_params: Dict[str, Any] = {}

        # Add verbosity if specified
        if self.verbosity is not None:
            text_params["verbosity"] = self.verbosity

        # Set the response format
        if response_format is not None:
            if isinstance(response_format, type) and issubclass(response_format, BaseModel):
                schema = get_response_schema_for_provider(response_format, "openai")
                text_params["format"] = {
                    "type": "json_schema",
                    "name": response_format.__name__,
                    "schema": schema,
                    "strict": self.strict_output,
                }
            else:
                # Pass through directly, user handles everything
                text_params["format"] = response_format

        # Add text parameter if there are any text-level params
        if text_params:
            base_params["text"] = text_params

        # Filter out None values
        request_params: Dict[str, Any] = {k: v for k, v in base_params.items() if v is not None}

        # Deep research models require web_search_preview tool or MCP tool
        if "deep-research" in self.id:
            if tools is None:
                tools = []

            # Check if web_search_preview tool is already present
            has_web_search = any(tool.get("type") == "web_search_preview" for tool in tools)

            # Add web_search_preview if not present - this enables the model to search
            # the web for current information and provide citations
            if not has_web_search:
                web_search_tool = {"type": "web_search_preview"}
                tools.insert(0, web_search_tool)
                log_debug(f"Added web_search_preview tool for deep research model: {self.id}")

        if tools:
            request_params["tools"] = self._format_tool_params(messages=messages, tools=tools)  # type: ignore

        if tool_choice is not None:
            request_params["tool_choice"] = tool_choice

        # Handle reasoning tools for o3 and o4-mini models
        if self._using_reasoning_model() and messages is not None:
            if store is False:
                request_params["store"] = False

                # Add encrypted reasoning content to include if not already present
                include_list = request_params.get("include", []) or []
                if "reasoning.encrypted_content" not in include_list:
                    include_list.append("reasoning.encrypted_content")
                    if request_params.get("include") is None:
                        request_params["include"] = include_list
                    elif isinstance(request_params["include"], list):
                        request_params["include"].extend(include_list)

            else:
                request_params["store"] = True

                # Check if the last assistant message has a previous_response_id to continue from
                previous_response_id = None
                for msg in reversed(messages):
                    if (
                        msg.role == "assistant"
                        and hasattr(msg, "provider_data")
                        and msg.provider_data
                        and "response_id" in msg.provider_data
                    ):
                        previous_response_id = msg.provider_data["response_id"]
                        log_debug(f"Using previous_response_id: {previous_response_id}")
                        break

                if previous_response_id:
                    request_params["previous_response_id"] = previous_response_id

        # Add additional request params if provided
        if self.request_params:
            request_params.update(self.request_params)

        if request_params:
            log_debug(f"Calling {self.provider} with request parameters: {request_params}", log_level=2)
        return request_params

    @staticmethod
    def _has_file_search_tool(tools: Optional[List[Union[Function, Dict[str, Any]]]] = None) -> bool:
        """Check if any tool in the list is a file_search tool."""
        if not tools:
            return False
        return any(isinstance(tool, dict) and tool.get("type") == "file_search" for tool in tools)

    @staticmethod
    def _format_file_for_input(file: File) -> Optional[Dict[str, Any]]:
        """Format a File object as an input_file content block for the Responses API.

        Routes to the correct variant:
        - file_url: when the file has a URL (most efficient, OpenAI fetches server-side)
        - file_data: when the file has local content or filepath (base64 encoded)
        - file_id: when the file has an OpenAI file ID (starts with "file-")
        """
        import base64
        import mimetypes
        import os

        # Determine filename
        filename = file.filename or file.name
        if not filename and file.filepath:
            filename = os.path.basename(str(file.filepath))
        if not filename:
            filename = "document"

        # URL passthrough — let OpenAI fetch it server-side
        if file.url:
            return {
                "type": "input_file",
                "file_url": file.url,
            }

        # Local file or raw bytes — base64 encode as data URI
        if file.filepath or file.content:
            content_bytes = file.get_content_bytes()
            if content_bytes is None:
                log_warning(f"Could not read content from file: {file.filepath or file.filename or 'unknown'}")
                return None

            # Resolve MIME type
            mime_type = file.mime_type
            if not mime_type:
                source_path = str(file.filepath) if file.filepath else filename
                mime_type = mimetypes.guess_type(source_path)[0] or "application/octet-stream"

            encoded = base64.b64encode(content_bytes).decode("utf-8")
            file_data = f"data:{mime_type};base64,{encoded}"

            return {
                "type": "input_file",
                "filename": filename,
                "file_data": file_data,
            }

        # OpenAI file ID reference
        if file.id and isinstance(file.id, str) and file.id.startswith("file-"):
            return {
                "type": "input_file",
                "file_id": file.id,
            }

        return None

    def _upload_file(self, file: File) -> Optional[str]:
        """Upload a file to the OpenAI vector database."""
        from pathlib import Path
        from urllib.parse import urlparse

        if file.url is not None:
            file_content_tuple = file.file_url_content
            if file_content_tuple is not None:
                file_content = file_content_tuple[0]
            else:
                return None
            file_name = Path(urlparse(file.url).path).name or "file"
            file_tuple = (file_name, file_content)
            result = self.get_client().files.create(file=file_tuple, purpose="assistants")
            return result.id
        elif file.filepath is not None:
            import mimetypes

            file_path = file.filepath if isinstance(file.filepath, Path) else Path(file.filepath)
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
            result = self.get_client().files.create(file=file.content, purpose="assistants")
            return result.id

        return None

    def _create_vector_store(self, file_ids: List[str]) -> str:
        """Create a vector store for the files."""
        vector_store = self.get_client().vector_stores.create(name=self.vector_store_name)
        for file_id in file_ids:
            self.get_client().vector_stores.files.create(vector_store_id=vector_store.id, file_id=file_id)
        while True:
            uploaded_files = list(self.get_client().vector_stores.files.list(vector_store_id=vector_store.id))
            # Wait until all files appear in the list (eventual consistency)
            if len(uploaded_files) < len(file_ids):
                time.sleep(1)
                continue
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

    def _format_tool_params(
        self, messages: List[Message], tools: Optional[List[Union[Function, Dict[str, Any]]]] = None
    ) -> List[Dict[str, Any]]:
        """Format the tool parameters for the OpenAI Responses API."""
        formatted_tools = []
        if tools:
            for _tool in tools:
                if isinstance(_tool, Function):
                    _tool_dict = _tool.to_dict()
                    _tool_dict["type"] = "function"
                    for prop in _tool_dict.get("parameters", {}).get("properties", {}).values():
                        if isinstance(prop.get("type", ""), list):
                            prop["type"] = prop["type"][0]
                    formatted_tools.append(_tool_dict)
                elif _tool.get("type") == "function":
                    _tool_dict = _tool.get("function", {})
                    _tool_dict["type"] = "function"
                    for prop in _tool_dict.get("parameters", {}).get("properties", {}).values():
                        if isinstance(prop.get("type", ""), list):
                            prop["type"] = prop["type"][0]
                    formatted_tools.append(_tool_dict)
                else:
                    formatted_tools.append(_tool)

        # Only upload files to vector store when file_search tool is present.
        # Otherwise, files will be embedded inline via _format_messages().
        file_ids = []
        if self._has_file_search_tool(tools):
            for message in messages:
                if message.files is not None and len(message.files) > 0:
                    for file in message.files:
                        file_id = self._upload_file(file)
                        if file_id is not None:
                            file_ids.append(file_id)

        vector_store_id = self._create_vector_store(file_ids) if file_ids else None

        # Add the file IDs to the tool parameters
        for _tool in formatted_tools:
            if _tool.get("type", "") == "file_search" and vector_store_id is not None:
                _tool["vector_store_ids"] = [vector_store_id]

        return formatted_tools

    def _build_fc_id_to_call_id_map(self, messages: List[Message]) -> Dict[str, str]:
        """Build a mapping from function_call id (fc_*) to call_id (call_*) from assistant tool_calls.

        The OpenAI Responses API uses two ID systems:
        - `id` (e.g. "fc_xxx"): internal function call identifier
        - `call_id` (e.g. "call_xxx"): the ID expected by the API for function_call_output

        This mapping is needed to translate between the two when formatting tool results.
        """
        fc_id_to_call_id: Dict[str, str] = {}
        for msg in messages:
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    fc_id = tc.get("id")
                    call_id = tc.get("call_id") or fc_id
                    if isinstance(fc_id, str) and isinstance(call_id, str):
                        fc_id_to_call_id[fc_id] = call_id
        return fc_id_to_call_id

    def _format_messages(
        self,
        messages: List[Message],
        compress_tool_results: bool = False,
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
    ) -> List[Union[Dict[str, Any], ResponseReasoningItem]]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            messages (List[Message]): The message to format.
            compress_tool_results: Whether to compress tool results.
            tools: The tools list, used to detect if file_search is present.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        from agno.utils.message import normalize_tool_messages, reformat_tool_call_ids

        # Backwards compat: expand old Gemini combined tool messages into individual canonical messages
        messages = normalize_tool_messages(messages)
        # Remap foreign tool call IDs (e.g. call_*, toolu_*) to fc_* prefix for Responses API
        messages = reformat_tool_call_ids(messages, provider="openai_responses")

        formatted_messages: List[Union[Dict[str, Any], ResponseReasoningItem]] = []

        messages_to_format = messages
        previous_response_id: Optional[str] = None

        if self._using_reasoning_model() and self.store is not False:
            # Detect whether we're chaining via previous_response_id. If so, we should NOT
            # re-send prior function_call items; the Responses API already has the state and
            # expects only the corresponding function_call_output items.

            for msg in reversed(messages):
                if (
                    msg.role == "assistant"
                    and hasattr(msg, "provider_data")
                    and msg.provider_data
                    and "response_id" in msg.provider_data
                ):
                    previous_response_id = msg.provider_data["response_id"]
                    msg_index = messages.index(msg)

                    # Include messages after this assistant message
                    messages_to_format = messages[msg_index + 1 :]

                    break

        fc_id_to_call_id = self._build_fc_id_to_call_id_map(messages)

        for message in messages_to_format:
            if message.role in ["user", "system"]:
                message_dict: Dict[str, Any] = {
                    "role": self.role_map[message.role],
                    "content": message.get_content(use_compressed_content=compress_tool_results),
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

                if message.audio is not None and len(message.audio) > 0:
                    log_warning("Audio input is currently unsupported.")

                if message.videos is not None and len(message.videos) > 0:
                    log_warning("Video input is currently unsupported.")

                # Embed files inline as input_file blocks when file_search is not present
                if message.files and not self._has_file_search_tool(tools):
                    if not isinstance(message_dict.get("content"), list):
                        message_dict["content"] = [{"type": "input_text", "text": message_dict.get("content") or ""}]
                    for file in message.files:
                        file_block = self._format_file_for_input(file)
                        if file_block:
                            message_dict["content"].append(file_block)

                formatted_messages.append(message_dict)

            # Tool call result
            elif message.role == "tool":
                tool_result = message.get_content(use_compressed_content=compress_tool_results)

                if message.tool_call_id and tool_result is not None:
                    function_call_id = message.tool_call_id
                    # Normalize: if a fc_* id was provided, translate to its corresponding call_* id
                    if isinstance(function_call_id, str) and function_call_id in fc_id_to_call_id:
                        call_id_value = fc_id_to_call_id[function_call_id]
                    else:
                        call_id_value = function_call_id
                    formatted_messages.append(
                        {"type": "function_call_output", "call_id": call_id_value, "output": tool_result}
                    )
            # Tool Calls
            elif message.tool_calls is not None and len(message.tool_calls) > 0:
                # Only skip re-sending prior function_call items when we have a previous_response_id
                # (reasoning models). For non-reasoning models, we must include the prior function_call
                # so the API can associate the subsequent function_call_output by call_id.
                if self._using_reasoning_model() and previous_response_id is not None:
                    continue

                for tool_call in message.tool_calls:
                    formatted_messages.append(
                        {
                            "type": "function_call",
                            "id": tool_call.get("id"),
                            "call_id": tool_call.get("call_id", tool_call.get("id")),
                            "name": tool_call["function"]["name"],
                            "arguments": tool_call["function"]["arguments"],
                            "status": "completed",
                        }
                    )
            elif message.role == "assistant":
                # Handle null content by converting to empty string
                content = message.content if message.content is not None else ""
                formatted_messages.append({"role": self.role_map[message.role], "content": content})

                if self.store is False and hasattr(message, "provider_data") and message.provider_data is not None:
                    if message.provider_data.get("reasoning_output") is not None:
                        reasoning_output = ResponseReasoningItem.model_validate(
                            message.provider_data["reasoning_output"]
                        )
                        formatted_messages.append(reasoning_output)
        return formatted_messages

    def count_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        output_schema: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        try:
            formatted_input = self._format_messages(messages, compress_tool_results=True, tools=tools)
            formatted_tools = self._format_tool_params(messages, tools) if tools is not None else None

            response = self.get_client().responses.input_tokens.count(
                model=self.id,
                input=formatted_input,  # type: ignore
                instructions=self.instructions,  # type: ignore
                tools=formatted_tools,  # type: ignore
            )
            return response.input_tokens + count_schema_tokens(output_schema, self.id)
        except Exception as e:
            log_warning(f"Failed to count tokens via API: {str(e)}")
            return super().count_tokens(messages, tools, output_schema)

    async def acount_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        output_schema: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        """Async version of count_tokens using the async client."""
        try:
            formatted_input = self._format_messages(messages, compress_tool_results=True, tools=tools)
            formatted_tools = self._format_tool_params(messages, tools) if tools else None

            response = await self.get_async_client().responses.input_tokens.count(
                model=self.id,
                input=formatted_input,  # type: ignore
                instructions=self.instructions,  # type: ignore
                tools=formatted_tools,  # type: ignore
            )
            return response.input_tokens + count_schema_tokens(output_schema, self.id)
        except Exception as e:
            log_warning(f"Failed to count tokens via API: {str(e)}")
            return await super().acount_tokens(messages, tools, output_schema)

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
        """
        Send a request to the OpenAI Responses API.
        """
        try:
            request_params = self.get_request_params(
                messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
            )

            assistant_message.metrics.start_timer()

            provider_response = self.get_client().responses.create(
                model=self.id,
                input=self._format_messages(messages, compress_tool_results, tools=tools),  # type: ignore
                **request_params,
            )

            # Stop the timer before polling so wall-clock polling wait is not counted as inference time.
            # For background mode, the initial create() measures submission latency; the polling loop
            # is then allowed to run without inflating time_to_first_token / total time metrics.
            assistant_message.metrics.stop_timer()

            # Poll for completion if background mode is enabled
            if self.background and provider_response.status in ("queued", "in_progress"):
                log_debug(f"Background response submitted: {provider_response.id}, polling for completion...")
                provider_response = self._poll_background_response(provider_response.id)

            if provider_response.status == "failed":
                error_msg = provider_response.error.message if provider_response.error else "Background response failed"
                raise ModelProviderError(message=error_msg, model_name=self.name, model_id=self.id)
            if provider_response.status == "cancelled":
                raise ModelProviderError(
                    message=f"Background response {provider_response.id} was cancelled",
                    model_name=self.name,
                    model_id=self.id,
                )
            if provider_response.status == "incomplete":
                log_warning(
                    f"Background response {provider_response.id} completed with status 'incomplete': "
                    f"{provider_response.incomplete_details}"
                )

            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except RateLimitError as exc:
            log_error(f"Rate limit error from OpenAI API: {exc}")
            try:
                error_message = exc.response.json().get("error", {})
            except Exception:
                error_message = exc.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except APIConnectionError as exc:
            log_error(f"API connection error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc
        except APIStatusError as exc:
            log_error(f"API status error from OpenAI API: {exc}")
            try:
                error_body = exc.response.json().get("error", {})
            except Exception:
                error_body = exc.response.text
            error_code = error_body.get("code") if isinstance(error_body, dict) else None
            error_message = (
                error_body.get("message", "Unknown model error") if isinstance(error_body, dict) else error_body
            )
            if error_code == "context_length_exceeded":
                raise ContextWindowExceededError(
                    message=error_message,
                    status_code=exc.response.status_code,
                    model_name=self.name,
                    model_id=self.id,
                ) from exc
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except ModelAuthenticationError as exc:
            log_error(f"Model authentication error from OpenAI API: {exc}")
            raise exc
        except Exception as exc:
            log_error(f"Error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc

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
        """
        Sends an asynchronous request to the OpenAI Responses API.
        """
        try:
            request_params = self.get_request_params(
                messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
            )

            assistant_message.metrics.start_timer()

            provider_response = await self.get_async_client().responses.create(
                model=self.id,
                input=self._format_messages(messages, compress_tool_results, tools=tools),  # type: ignore
                **request_params,
            )

            # Stop the timer before polling so wall-clock polling wait is not counted as inference time.
            # For background mode, the initial create() measures submission latency; the polling loop
            # is then allowed to run without inflating time_to_first_token / total time metrics.
            assistant_message.metrics.stop_timer()

            # Poll for completion if background mode is enabled
            if self.background and provider_response.status in ("queued", "in_progress"):
                log_debug(f"Background response submitted: {provider_response.id}, polling for completion...")
                provider_response = await self._apoll_background_response(provider_response.id)

            if provider_response.status == "failed":
                error_msg = provider_response.error.message if provider_response.error else "Background response failed"
                raise ModelProviderError(message=error_msg, model_name=self.name, model_id=self.id)
            if provider_response.status == "cancelled":
                raise ModelProviderError(
                    message=f"Background response {provider_response.id} was cancelled",
                    model_name=self.name,
                    model_id=self.id,
                )
            if provider_response.status == "incomplete":
                log_warning(
                    f"Background response {provider_response.id} completed with status 'incomplete': "
                    f"{provider_response.incomplete_details}"
                )

            model_response = self._parse_provider_response(provider_response, response_format=response_format)

            return model_response

        except RateLimitError as exc:
            log_error(f"Rate limit error from OpenAI API: {exc}")
            try:
                error_message = exc.response.json().get("error", {})
            except Exception:
                error_message = exc.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except APIConnectionError as exc:
            log_error(f"API connection error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc
        except APIStatusError as exc:
            log_error(f"API status error from OpenAI API: {exc}")
            try:
                error_body = exc.response.json().get("error", {})
            except Exception:
                error_body = exc.response.text
            error_code = error_body.get("code") if isinstance(error_body, dict) else None
            error_message = (
                error_body.get("message", "Unknown model error") if isinstance(error_body, dict) else error_body
            )
            if error_code == "context_length_exceeded":
                raise ContextWindowExceededError(
                    message=error_message,
                    status_code=exc.response.status_code,
                    model_name=self.name,
                    model_id=self.id,
                ) from exc
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except ModelAuthenticationError as exc:
            log_error(f"Model authentication error from OpenAI API: {exc}")
            raise exc
        except Exception as exc:
            log_error(f"Error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc

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
        """
        Send a streaming request to the OpenAI Responses API.
        """
        try:
            request_params = self.get_request_params(
                messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
            )
            # Background mode is not supported for streaming. Strip the flag and warn.
            if request_params.pop("background", None):
                log_warning("Background mode is not supported for streaming requests. Ignoring `background=True`.")
            tool_use: Dict[str, Any] = {}

            assistant_message.metrics.start_timer()

            for chunk in self.get_client().responses.create(
                model=self.id,
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

        except RateLimitError as exc:
            log_error(f"Rate limit error from OpenAI API: {exc}")
            try:
                error_message = exc.response.json().get("error", {})
            except Exception:
                error_message = exc.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except APIConnectionError as exc:
            log_error(f"API connection error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc
        except APIStatusError as exc:
            log_error(f"API status error from OpenAI API: {exc}")
            try:
                error_body = exc.response.json().get("error", {})
            except Exception:
                error_body = exc.response.text
            error_code = error_body.get("code") if isinstance(error_body, dict) else None
            error_message = (
                error_body.get("message", "Unknown model error") if isinstance(error_body, dict) else error_body
            )
            if error_code == "context_length_exceeded":
                raise ContextWindowExceededError(
                    message=error_message,
                    status_code=exc.response.status_code,
                    model_name=self.name,
                    model_id=self.id,
                ) from exc
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except ModelAuthenticationError as exc:
            log_error(f"Model authentication error from OpenAI API: {exc}")
            raise exc
        except Exception as exc:
            log_error(f"Error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc

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
        """
        Sends an asynchronous streaming request to the OpenAI Responses API.
        """
        try:
            request_params = self.get_request_params(
                messages=messages, response_format=response_format, tools=tools, tool_choice=tool_choice
            )
            # Background mode is not supported for streaming. Strip the flag and warn.
            if request_params.pop("background", None):
                log_warning("Background mode is not supported for streaming requests. Ignoring `background=True`.")
            tool_use: Dict[str, Any] = {}

            assistant_message.metrics.start_timer()

            async_stream = await self.get_async_client().responses.create(
                model=self.id,
                input=self._format_messages(messages, compress_tool_results, tools=tools),  # type: ignore
                stream=True,
                **request_params,
            )
            async for chunk in async_stream:  # type: ignore
                model_response, tool_use = self._parse_provider_response_delta(chunk, assistant_message, tool_use)  # type: ignore
                yield model_response

            assistant_message.metrics.stop_timer()

        except RateLimitError as exc:
            log_error(f"Rate limit error from OpenAI API: {exc}")
            try:
                error_message = exc.response.json().get("error", {})
            except Exception:
                error_message = exc.response.text
            error_message = (
                error_message.get("message", "Unknown model error")
                if isinstance(error_message, dict)
                else error_message
            )
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except APIConnectionError as exc:
            log_error(f"API connection error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc
        except APIStatusError as exc:
            log_error(f"API status error from OpenAI API: {exc}")
            try:
                error_body = exc.response.json().get("error", {})
            except Exception:
                error_body = exc.response.text
            error_code = error_body.get("code") if isinstance(error_body, dict) else None
            error_message = (
                error_body.get("message", "Unknown model error") if isinstance(error_body, dict) else error_body
            )
            if error_code == "context_length_exceeded":
                raise ContextWindowExceededError(
                    message=error_message,
                    status_code=exc.response.status_code,
                    model_name=self.name,
                    model_id=self.id,
                ) from exc
            raise ModelProviderError(
                message=error_message,
                status_code=exc.response.status_code,
                model_name=self.name,
                model_id=self.id,
            ) from exc
        except ModelAuthenticationError as exc:
            log_error(f"Model authentication error from OpenAI API: {exc}")
            raise exc
        except Exception as exc:
            log_error(f"Error from OpenAI API: {exc}")
            raise ModelProviderError(message=str(exc), model_name=self.name, model_id=self.id) from exc

    def format_function_call_results(
        self,
        messages: List[Message],
        function_call_results: List[Message],
        compress_tool_results: bool = False,
        **kwargs,
    ) -> None:
        """
        Format function call results for Responses API.

        Stores tool results with the canonical fc_* tool_call_id (matching the assistant's
        tool_calls[].id). The fc_* to call_* translation needed by the API happens at
        runtime in _format_messages via _build_fc_id_to_call_id_map.
        """
        if len(function_call_results) > 0:
            messages.extend(function_call_results)

    def _parse_provider_response(self, response: Response, **kwargs) -> ModelResponse:
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

        # Store the response ID for continuity
        if response.id:
            if model_response.provider_data is None:
                model_response.provider_data = {}
            model_response.provider_data["response_id"] = response.id

        # Add role
        model_response.role = "assistant"
        reasoning_summary: Optional[str] = None

        for output in response.output:
            # Add content
            if output.type == "message":
                model_response.content = response.output_text

                # Add citations
                citations = Citations()
                for content in output.content:
                    if content.type == "output_text" and content.annotations:
                        citations.raw = [annotation.model_dump() for annotation in content.annotations]
                        for annotation in content.annotations:
                            if annotation.type == "url_citation":
                                if citations.urls is None:
                                    citations.urls = []
                                citations.urls.append(UrlCitation(url=annotation.url, title=annotation.title))
                        if citations.urls or citations.documents:
                            model_response.citations = citations

            # Add tool calls
            elif output.type == "function_call":
                if model_response.tool_calls is None:
                    model_response.tool_calls = []
                model_response.tool_calls.append(
                    {
                        "id": output.id,
                        # Store additional call_id from OpenAI responses
                        "call_id": output.call_id or output.id,
                        "type": "function",
                        "function": {
                            "name": output.name,
                            "arguments": output.arguments,
                        },
                    }
                )

                model_response.extra = model_response.extra or {}
                model_response.extra.setdefault("tool_call_ids", []).append(output.call_id)

            # Handle reasoning output items
            elif output.type == "reasoning":
                # Save encrypted reasoning content for ZDR mode
                if self.store is False:
                    if model_response.provider_data is None:
                        model_response.provider_data = {}
                    model_response.provider_data["reasoning_output"] = output.model_dump(exclude_none=True)

                if reasoning_summaries := getattr(output, "summary", None):
                    for summary in reasoning_summaries:
                        if isinstance(summary, dict):
                            summary_text = summary.get("text")
                        else:
                            summary_text = getattr(summary, "text", None)
                        if summary_text:
                            reasoning_summary = (reasoning_summary or "") + summary_text

        # Add reasoning content
        if reasoning_summary is not None:
            model_response.reasoning_content = reasoning_summary
        elif self.reasoning is not None:
            model_response.reasoning_content = response.output_text

        # Add metrics
        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)

        return model_response

    def _parse_provider_response_delta(
        self, stream_event: ResponseStreamEvent, assistant_message: Message, tool_use: Dict[str, Any]
    ) -> Tuple[ModelResponse, Dict[str, Any]]:
        """
        Parse the streaming response from the model provider into a ModelResponse object.

        Args:
            response: Raw response chunk from the model provider

        Returns:
            ModelResponse: Parsed response delta
        """
        model_response = ModelResponse()

        # 1. Add response ID
        if stream_event.type == "response.created":
            if stream_event.response.id:
                if model_response.provider_data is None:
                    model_response.provider_data = {}
                model_response.provider_data["response_id"] = stream_event.response.id
            if assistant_message.metrics is not None and not assistant_message.metrics.time_to_first_token:
                assistant_message.metrics.set_time_to_first_token()

        # 2. Add citations
        elif stream_event.type == "response.output_text.annotation.added":
            if model_response.citations is None:
                model_response.citations = Citations(raw=[stream_event.annotation])
            else:
                model_response.citations.raw.append(stream_event.annotation)  # type: ignore

            if isinstance(stream_event.annotation, dict):
                if stream_event.annotation.get("type") == "url_citation":
                    if model_response.citations.urls is None:
                        model_response.citations.urls = []
                    model_response.citations.urls.append(
                        UrlCitation(url=stream_event.annotation.get("url"), title=stream_event.annotation.get("title"))
                    )
            else:
                if stream_event.annotation.type == "url_citation":  # type: ignore
                    if model_response.citations.urls is None:
                        model_response.citations.urls = []
                    model_response.citations.urls.append(
                        UrlCitation(url=stream_event.annotation.url, title=stream_event.annotation.title)  # type: ignore
                    )

        # 3. Add content
        elif stream_event.type == "response.output_text.delta":
            model_response.content = stream_event.delta

            # Treat the output_text deltas as reasoning content if the reasoning summary is not requested.
            if self.reasoning is not None and self.reasoning_summary is None:
                model_response.reasoning_content = stream_event.delta

        # 4. Add tool calls information

        # 4.1 Add starting tool call
        elif stream_event.type == "response.output_item.added":
            item = stream_event.item
            if item.type == "function_call":
                tool_use = {
                    "id": getattr(item, "id", None),
                    "call_id": getattr(item, "call_id", None) or getattr(item, "id", None),
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "arguments": item.arguments,
                    },
                }

        # 4.2 Add tool call arguments
        elif stream_event.type == "response.function_call_arguments.delta":
            tool_use["function"]["arguments"] += stream_event.delta

        # 4.3 Add tool call completion data
        elif stream_event.type == "response.output_item.done" and tool_use:
            model_response.tool_calls = [tool_use]
            if assistant_message.tool_calls is None:
                assistant_message.tool_calls = []
            assistant_message.tool_calls.append(tool_use)

            model_response.extra = model_response.extra or {}
            model_response.extra.setdefault("tool_call_ids", []).append(tool_use["call_id"])
            tool_use = {}

        # 5. Add metrics
        elif stream_event.type == "response.completed":
            model_response = ModelResponse()

            # Handle reasoning output items
            if self.reasoning_summary is not None or self.store is False:
                summary_text: str = ""
                for out in getattr(stream_event.response, "output", []) or []:
                    if getattr(out, "type", None) == "reasoning":
                        # In ZDR mode (store=False), store reasoning data for next request
                        if self.store is False and hasattr(out, "encrypted_content"):
                            if model_response.provider_data is None:
                                model_response.provider_data = {}
                            # Store the complete output item
                            model_response.provider_data["reasoning_output"] = out.model_dump(exclude_none=True)
                        if self.reasoning_summary is not None:
                            summaries = getattr(out, "summary", None)
                            if summaries:
                                for s in summaries:
                                    text_val = s.get("text") if isinstance(s, dict) else getattr(s, "text", None)
                                    if text_val:
                                        if summary_text:
                                            summary_text += "\n\n"
                                        summary_text += text_val

                if summary_text:
                    model_response.reasoning_content = summary_text

            # Add metrics
            if stream_event.response.usage is not None:
                model_response.response_usage = self._get_metrics(stream_event.response.usage)

        return model_response, tool_use

    def _get_metrics(self, response_usage: ResponseUsage) -> MessageMetrics:
        """
        Parse the given OpenAI-specific usage into an Agno MessageMetrics object.

        Args:
            response: The response from the provider.

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        metrics.input_tokens = response_usage.input_tokens or 0
        metrics.output_tokens = response_usage.output_tokens or 0
        metrics.total_tokens = response_usage.total_tokens or 0

        if input_tokens_details := response_usage.input_tokens_details:
            metrics.cache_read_tokens = input_tokens_details.cached_tokens

        if output_tokens_details := response_usage.output_tokens_details:
            metrics.reasoning_tokens = output_tokens_details.reasoning_tokens

        return metrics
