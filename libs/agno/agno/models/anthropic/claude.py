import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.message import Citations, DocumentCitation, Message, UrlCitation
from agno.models.response import ModelResponse
from agno.utils.log import log_error, log_warning
from agno.utils.models.claude import MCPServerConfiguration, format_messages

try:
    from anthropic import (
        Anthropic as AnthropicClient,
    )
    from anthropic import (
        APIConnectionError,
        APIStatusError,
        RateLimitError,
    )
    from anthropic import (
        AsyncAnthropic as AsyncAnthropicClient,
    )
    from anthropic.types import (
        CitationPageLocation,
        CitationsWebSearchResultLocation,
        ContentBlockDeltaEvent,
        ContentBlockStartEvent,
        ContentBlockStopEvent,
        # MessageDeltaEvent,  # Currently broken
        MessageStopEvent,
    )
    from anthropic.types import (
        Message as AnthropicMessage,
    )
except ImportError as e:
    raise ImportError("`anthropic` not installed. Please install it with `pip install anthropic`") from e

# Import Beta types
try:
    from anthropic.types.beta import (
        BetaMessage,
        BetaRawContentBlockDeltaEvent,
        BetaTextDelta,
    )
except ImportError as e:
    raise ImportError(
        "`anthropic` not installed or missing beta components. Please install with `pip install anthropic`"
    ) from e


@dataclass
class Claude(Model):
    """
    A class representing Anthropic Claude model.

    For more information, see: https://docs.anthropic.com/en/api/messages
    """

    id: str = "claude-3-5-sonnet-20241022"
    name: str = "Claude"
    provider: str = "Anthropic"

    # Request parameters
    max_tokens: Optional[int] = 4096
    thinking: Optional[Dict[str, Any]] = None
    temperature: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    cache_system_prompt: Optional[bool] = False
    extended_cache_time: Optional[bool] = False

    # Enhanced caching parameters
    enable_prompt_caching: Optional[bool] = False
    cache_tool_definitions: Optional[bool] = False
    cache_messages: Optional[Dict[str, Any]] = None
    cache_ttl: Optional[str] = "5m"

    request_params: Optional[Dict[str, Any]] = None
    mcp_servers: Optional[List[MCPServerConfiguration]] = None

    # Client parameters
    api_key: Optional[str] = None
    default_headers: Optional[Dict[str, Any]] = None
    client_params: Optional[Dict[str, Any]] = None

    # Anthropic clients
    client: Optional[AnthropicClient] = None
    async_client: Optional[AsyncAnthropicClient] = None

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            log_error("ANTHROPIC_API_KEY not set. Please set the ANTHROPIC_API_KEY environment variable.")

        client_params["api_key"] = self.api_key

        # Add beta headers for prompt caching
        if (
            self.cache_system_prompt
            or self.enable_prompt_caching
            or self.cache_tool_definitions
            or self.cache_messages
            or self.cache_ttl == "1h"
            or self.extended_cache_time
        ):
            if self.default_headers is None:
                self.default_headers = {}

            # Always add the prompt caching beta header
            if "anthropic-beta" not in self.default_headers:
                self.default_headers["anthropic-beta"] = "prompt-caching-2024-07-31"

            # Add extended cache TTL header if needed
            if self.cache_ttl == "1h" or self.extended_cache_time:
                existing_beta = self.default_headers.get("anthropic-beta", "")
                if "extended-cache-ttl" not in existing_beta:
                    if existing_beta:
                        self.default_headers["anthropic-beta"] = f"{existing_beta},extended-cache-ttl-2025-04-11"
                    else:
                        self.default_headers["anthropic-beta"] = "extended-cache-ttl-2025-04-11"

        if self.client_params is not None:
            client_params.update(self.client_params)
        if self.default_headers is not None:
            client_params["default_headers"] = self.default_headers
        return client_params

    def get_client(self) -> AnthropicClient:
        """
        Returns an instance of the Anthropic client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        _client_params = self._get_client_params()
        self.client = AnthropicClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAnthropicClient:
        """
        Returns an instance of the async Anthropic client.
        """
        if self.async_client:
            return self.async_client

        _client_params = self._get_client_params()
        self.async_client = AsyncAnthropicClient(**_client_params)
        return self.async_client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.
        """
        _request_params: Dict[str, Any] = {}
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.thinking:
            _request_params["thinking"] = self.thinking
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.mcp_servers:
            _request_params["mcp_servers"] = [
                {k: v for k, v in asdict(server).items() if v is not None} for server in self.mcp_servers
            ]
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def _create_cache_control(self, ttl: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a cache_control dictionary based on the model configuration.

        Args:
            ttl: Time-to-live for the cache (5m or 1h). If None, uses model default.

        Returns:
            Dict containing cache_control configuration
        """
        cache_ttl = ttl or self.cache_ttl or "5m"

        cache_control = {"type": "ephemeral"}

        # Add TTL if not default 5m or if extended_cache_time is enabled
        if cache_ttl == "1h" or self.extended_cache_time:
            cache_control["ttl"] = "1h"
        elif cache_ttl != "5m":
            cache_control["ttl"] = cache_ttl

        return cache_control

    def _prepare_request_kwargs(
        self,
        system_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Prepare the request keyword arguments for the API call.

        Args:
            system_message (str): The concatenated system messages.
            tools: Tool definitions to potentially cache
            messages: Message history to potentially cache

        Returns:
            Dict[str, Any]: The request keyword arguments.
        """
        request_kwargs = self.request_kwargs.copy()

        # Handle system message caching
        if system_message:
            if self.cache_system_prompt or self.enable_prompt_caching:
                cache_control = self._create_cache_control()
                request_kwargs["system"] = [{"text": system_message, "type": "text", "cache_control": cache_control}]
            else:
                request_kwargs["system"] = [{"text": system_message, "type": "text"}]

        # Handle tool caching
        if tools:
            formatted_tools = self._format_tools_for_model(tools)
            if self.cache_tool_definitions and formatted_tools:
                # Add cache_control to the last tool to cache all tools
                if len(formatted_tools) > 0:
                    formatted_tools[-1]["cache_control"] = self._create_cache_control()
            request_kwargs["tools"] = formatted_tools

        # Handle message caching
        if messages and self.cache_messages:
            # Note: messages are handled by the invoke methods, this is for reference
            pass

        return request_kwargs

    def _apply_message_caching(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply caching to messages based on cache_messages configuration.

        Args:
            messages: List of message dictionaries

        Returns:
            List of messages with cache_control applied where specified
        """
        if not self.cache_messages:
            return messages

        cached_messages = messages.copy()

        # Apply caching based on configuration
        if isinstance(self.cache_messages, dict):
            cache_indices = self.cache_messages.get("indices", [])
            cache_ttl = self.cache_messages.get("ttl")
            cache_last = self.cache_messages.get("cache_last", False)

            # Cache specific message indices
            for idx in cache_indices:
                if 0 <= idx < len(cached_messages):
                    if isinstance(cached_messages[idx].get("content"), list):
                        # Add cache_control to the last content block
                        content_blocks = cached_messages[idx]["content"]
                        if content_blocks:
                            content_blocks[-1]["cache_control"] = self._create_cache_control(cache_ttl)
                    elif isinstance(cached_messages[idx].get("content"), str):
                        # Convert string content to structured content with cache_control
                        content_text = cached_messages[idx]["content"]
                        cached_messages[idx]["content"] = [
                            {
                                "type": "text",
                                "text": content_text,
                                "cache_control": self._create_cache_control(cache_ttl),
                            }
                        ]

            # Cache the last message if requested
            if cache_last and cached_messages:
                last_msg = cached_messages[-1]
                if isinstance(last_msg.get("content"), list):
                    content_blocks = last_msg["content"]
                    if content_blocks:
                        content_blocks[-1]["cache_control"] = self._create_cache_control(cache_ttl)
                elif isinstance(last_msg.get("content"), str):
                    content_text = last_msg["content"]
                    cached_messages[-1]["content"] = [
                        {"type": "text", "text": content_text, "cache_control": self._create_cache_control(cache_ttl)}
                    ]

        return cached_messages

    def _format_tools_for_model(self, tools: Optional[List[Dict[str, Any]]] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Transforms function definitions into a format accepted by the Anthropic API.
        """
        if not tools:
            return None

        parsed_tools: List[Dict[str, Any]] = []
        for tool_def in tools:
            if tool_def.get("type", "") != "function":
                parsed_tools.append(tool_def)
                continue

            func_def = tool_def.get("function", {})
            parameters: Dict[str, Any] = func_def.get("parameters", {})
            properties: Dict[str, Any] = parameters.get("properties", {})
            required_params: List[str] = []

            for param_name, param_info in properties.items():
                param_type = param_info.get("type")
                param_type_list: List[str] = [param_type] if isinstance(param_type, str) else param_type or []

                if "null" not in param_type_list:
                    required_params.append(param_name)

            input_properties: Dict[str, Dict[str, Union[str, List[str]]]] = {}
            for param_name, param_info in properties.items():
                input_properties[param_name] = {
                    "description": param_info.get("description", ""),
                }
                if "type" not in param_info and "anyOf" in param_info:
                    input_properties[param_name]["anyOf"] = param_info["anyOf"]
                else:
                    input_properties[param_name]["type"] = param_info.get("type", "")

            tool = {
                "name": func_def.get("name") or "",
                "description": func_def.get("description") or "",
                "input_schema": {
                    "type": parameters.get("type", "object"),
                    "properties": input_properties,
                    "required": required_params,
                },
            }
            parsed_tools.append(tool)
        return parsed_tools

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Union[AnthropicMessage, BetaMessage]:
        """
        Send a request to the Anthropic API to generate a response.
        """
        try:
            chat_messages, system_message = format_messages(messages)

            # Apply message caching if enabled
            if self.cache_messages:
                chat_messages = self._apply_message_caching(chat_messages)

            request_kwargs = self._prepare_request_kwargs(system_message, tools, chat_messages)

            if self.mcp_servers is not None:
                return self.get_client().beta.messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **self.request_kwargs,
                )
            else:
                return self.get_client().messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                )
        except APIConnectionError as e:
            log_error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except RateLimitError as e:
            log_warning(f"Rate limit exceeded: {str(e)}")
            raise ModelRateLimitError(message=e.message, model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(
                message=e.message, status_code=e.status_code, model_name=self.name, model_id=self.id
            ) from e
        except Exception as e:
            log_error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def invoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Any:
        """
        Stream a response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.

        Raises:
            APIConnectionError: If there are network connectivity issues
            RateLimitError: If the API rate limit is exceeded
            APIStatusError: For other API-related errors
        """
        chat_messages, system_message = format_messages(messages)

        # Apply message caching if enabled
        if self.cache_messages:
            chat_messages = self._apply_message_caching(chat_messages)

        request_kwargs = self._prepare_request_kwargs(system_message, tools, chat_messages)

        try:
            if self.mcp_servers is not None:
                return (
                    self.get_client()
                    .beta.messages.stream(
                        model=self.id,
                        messages=chat_messages,  # type: ignore
                        **request_kwargs,
                    )
                    .__enter__()
                )
            else:
                return (
                    self.get_client()
                    .messages.stream(
                        model=self.id,
                        messages=chat_messages,  # type: ignore
                        **request_kwargs,
                    )
                    .__enter__()
                )
        except APIConnectionError as e:
            log_error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except RateLimitError as e:
            log_warning(f"Rate limit exceeded: {str(e)}")
            raise ModelRateLimitError(message=e.message, model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(
                message=e.message, status_code=e.status_code, model_name=self.name, model_id=self.id
            ) from e
        except Exception as e:
            log_error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Union[AnthropicMessage, BetaMessage]:
        """
        Send an asynchronous request to the Anthropic API to generate a response.
        """
        try:
            chat_messages, system_message = format_messages(messages)

            # Apply message caching if enabled
            if self.cache_messages:
                chat_messages = self._apply_message_caching(chat_messages)

            request_kwargs = self._prepare_request_kwargs(system_message, tools, chat_messages)

            if self.mcp_servers is not None:
                return await self.get_async_client().beta.messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **self.request_kwargs,
                )
            else:
                return await self.get_async_client().messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                )
        except APIConnectionError as e:
            log_error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except RateLimitError as e:
            log_warning(f"Rate limit exceeded: {str(e)}")
            raise ModelRateLimitError(message=e.message, model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(
                message=e.message, status_code=e.status_code, model_name=self.name, model_id=self.id
            ) from e
        except Exception as e:
            log_error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    async def ainvoke_stream(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncIterator[Any]:
        """
        Stream an asynchronous response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.

        Raises:
            APIConnectionError: If there are network connectivity issues
            RateLimitError: If the API rate limit is exceeded
            APIStatusError: For other API-related errors
        """
        try:
            chat_messages, system_message = format_messages(messages)

            # Apply message caching if enabled
            if self.cache_messages:
                chat_messages = self._apply_message_caching(chat_messages)

            request_kwargs = self._prepare_request_kwargs(system_message, tools, chat_messages)

            if self.mcp_servers is not None:
                async with self.get_async_client().beta.messages.stream(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                ) as stream:
                    async for chunk in stream:
                        yield chunk
            else:
                async with self.get_async_client().messages.stream(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                ) as stream:
                    async for chunk in stream:  # type: ignore
                        yield chunk
        except APIConnectionError as e:
            log_error(f"Connection error while calling Claude API: {str(e)}")
            raise ModelProviderError(message=e.message, model_name=self.name, model_id=self.id) from e
        except RateLimitError as e:
            log_warning(f"Rate limit exceeded: {str(e)}")
            raise ModelRateLimitError(message=e.message, model_name=self.name, model_id=self.id) from e
        except APIStatusError as e:
            log_error(f"Claude API error (status {e.status_code}): {str(e)}")
            raise ModelProviderError(
                message=e.message, status_code=e.status_code, model_name=self.name, model_id=self.id
            ) from e
        except Exception as e:
            log_error(f"Unexpected error calling Claude API: {str(e)}")
            raise ModelProviderError(message=str(e), model_name=self.name, model_id=self.id) from e

    def format_function_call_results(
        self, messages: List[Message], function_call_results: List[Message], tool_ids: List[str]
    ) -> None:
        """
        Handle the results of function calls.

        Args:
            messages (List[Message]): The list of conversation messages.
            function_call_results (List[Message]): The results of the function calls.
            tool_ids (List[str]): The tool ids.
        """
        if len(function_call_results) > 0:
            fc_responses: List = []
            for _fc_message in function_call_results:
                fc_responses.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": _fc_message.tool_call_id,
                        "content": str(_fc_message.content),
                    }
                )
            messages.append(Message(role="user", content=fc_responses))

    def get_system_message_for_model(self, tools: Optional[List[Any]] = None) -> Optional[str]:
        if tools is not None and len(tools) > 0:
            tool_call_prompt = "Do not reflect on the quality of the returned search results in your response"
            return tool_call_prompt
        return None

    def parse_provider_response(self, response: AnthropicMessage, **kwargs) -> ModelResponse:
        """
        Parse the Claude response into a ModelResponse.

        Args:
            response: Raw response from Anthropic

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Add role (Claude always uses 'assistant')
        model_response.role = response.role or "assistant"

        if response.content:
            for block in response.content:
                if block.type == "text":
                    if model_response.content is None:
                        model_response.content = block.text
                    else:
                        model_response.content += block.text

                    # Capture citations from the response
                    if block.citations is not None:
                        if model_response.citations is None:
                            model_response.citations = Citations(raw=[], urls=[], documents=[])
                        for citation in block.citations:
                            model_response.citations.raw.append(citation.model_dump())  # type: ignore
                            # Web search citations
                            if isinstance(citation, CitationsWebSearchResultLocation):
                                model_response.citations.urls.append(  # type: ignore
                                    UrlCitation(url=citation.url, title=citation.cited_text)
                                )
                            # Document citations
                            elif isinstance(citation, CitationPageLocation):
                                model_response.citations.documents.append(  # type: ignore
                                    DocumentCitation(
                                        document_title=citation.document_title,
                                        cited_text=citation.cited_text,
                                    )
                                )
                elif block.type == "thinking":
                    model_response.thinking = block.thinking
                    model_response.provider_data = {
                        "signature": block.signature,
                    }
                elif block.type == "redacted_thinking":
                    model_response.redacted_thinking = block.data

        # Extract tool calls from the response
        if response.stop_reason == "tool_use":
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    function_def = {"name": tool_name}
                    if tool_input:
                        function_def["arguments"] = json.dumps(tool_input)

                    model_response.extra = model_response.extra or {}
                    model_response.extra.setdefault("tool_ids", []).append(block.id)
                    model_response.tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": function_def,
                        }
                    )

        # Enhanced usage metrics parsing with all cache-related fields
        if response.usage is not None:
            usage_dict = {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

            # Map Anthropic cache metrics to standard field names
            if hasattr(response.usage, "cache_creation_input_tokens") and response.usage.cache_creation_input_tokens:
                usage_dict["cache_write_tokens"] = response.usage.cache_creation_input_tokens

            if hasattr(response.usage, "cache_read_input_tokens") and response.usage.cache_read_input_tokens:
                usage_dict["cached_tokens"] = response.usage.cache_read_input_tokens

            # Enhanced cache metrics for 1-hour cache (beta feature)
            if hasattr(response.usage, "cache_creation") and response.usage.cache_creation:
                cache_creation = response.usage.cache_creation
                if hasattr(cache_creation, "ephemeral_5m_input_tokens"):
                    usage_dict["cache_5m_creation_tokens"] = cache_creation.ephemeral_5m_input_tokens
                if hasattr(cache_creation, "ephemeral_1h_input_tokens"):
                    usage_dict["cache_1h_creation_tokens"] = cache_creation.ephemeral_1h_input_tokens

            # Enhanced cache read metrics for different TTLs
            if hasattr(response.usage, "cache_read") and response.usage.cache_read:
                cache_read = response.usage.cache_read
                if hasattr(cache_read, "ephemeral_5m_input_tokens"):
                    usage_dict["cache_5m_read_tokens"] = cache_read.ephemeral_5m_input_tokens
                if hasattr(cache_read, "ephemeral_1h_input_tokens"):
                    usage_dict["cache_1h_read_tokens"] = cache_read.ephemeral_1h_input_tokens

            model_response.response_usage = usage_dict

        return model_response

    def log_cache_performance(self, response_usage: Dict[str, Any], debug: bool = False) -> None:
        """
        Log cache performance metrics in debug mode.

        Args:
            response_usage: Usage metrics from the response
            debug: Whether to output detailed cache performance logs
        """
        if not debug:
            return

        cache_creation = response_usage.get("cache_write_tokens", 0)
        cache_read = response_usage.get("cached_tokens", 0)
        input_tokens = response_usage.get("input_tokens", 0)

        print("\n🔍 CACHE PERFORMANCE DEBUG:")
        print(f"   📊 Input tokens (not cached): {input_tokens}")
        print(f"   ✍️  Cache creation tokens: {cache_creation}")
        print(f"   📖 Cache read tokens: {cache_read}")

        # Calculate cache efficiency
        total_input = input_tokens + cache_read
        if total_input > 0:
            cache_hit_rate = (cache_read / total_input) * 100
            print(f"   📈 Cache hit rate: {cache_hit_rate:.1f}%")

            if cache_read > 0:
                # Cost analysis
                base_cost = (total_input * 0.003) / 1000  # $3 per 1M tokens
                cached_cost = (cache_read * 0.0003 + input_tokens * 0.003) / 1000
                savings = base_cost - cached_cost
                savings_percent = (savings / base_cost) * 100 if base_cost > 0 else 0

                print(f"   💰 Cost without cache: ${base_cost:.6f}")
                print(f"   💰 Cost with cache: ${cached_cost:.6f}")
                print(f"   💰 Savings: ${savings:.6f} ({savings_percent:.1f}%)")

        # Enhanced TTL-specific metrics
        cache_5m_create = response_usage.get("cache_5m_creation_tokens", 0)
        cache_1h_create = response_usage.get("cache_1h_creation_tokens", 0)
        cache_5m_read = response_usage.get("cache_5m_read_tokens", 0)
        cache_1h_read = response_usage.get("cache_1h_read_tokens", 0)

        if any([cache_5m_create, cache_1h_create, cache_5m_read, cache_1h_read]):
            print(f"   🕐 5m cache created: {cache_5m_create}")
            print(f"   🕐 5m cache read: {cache_5m_read}")
            print(f"   🕓 1h cache created: {cache_1h_create}")
            print(f"   🕓 1h cache read: {cache_1h_read}")

        print("")

    def parse_provider_response_delta(
        self, response: Union[ContentBlockStartEvent, ContentBlockDeltaEvent, ContentBlockStopEvent, MessageStopEvent]
    ) -> ModelResponse:
        """
        Parse the Claude streaming response into ModelProviderResponse objects.

        Args:
            response: Raw response chunk from Anthropic

        Returns:
            ModelResponse: Iterator of parsed response data
        """
        model_response = ModelResponse()

        if isinstance(response, ContentBlockStartEvent):
            if response.content_block.type == "redacted_thinking":
                model_response.redacted_thinking = response.content_block.data

        if isinstance(response, ContentBlockDeltaEvent):
            # Handle text content
            if response.delta.type == "text_delta":
                model_response.content = response.delta.text
            # Handle thinking content
            elif response.delta.type == "thinking_delta":
                model_response.thinking = response.delta.thinking
            elif response.delta.type == "signature_delta":
                model_response.provider_data = {
                    "signature": response.delta.signature,
                }

        elif isinstance(response, ContentBlockStopEvent):
            # Handle tool calls
            if response.content_block.type == "tool_use":  # type: ignore
                tool_use = response.content_block  # type: ignore
                tool_name = tool_use.name
                tool_input = tool_use.input

                function_def = {"name": tool_name}
                if tool_input:
                    function_def["arguments"] = json.dumps(tool_input)

                model_response.extra = model_response.extra or {}
                model_response.extra.setdefault("tool_ids", []).append(tool_use.id)

                model_response.tool_calls = [
                    {
                        "id": tool_use.id,
                        "type": "function",
                        "function": function_def,
                    }
                ]

        # Capture citations from the final response
        elif isinstance(response, MessageStopEvent):
            model_response.content = ""
            model_response.citations = Citations(raw=[], urls=[], documents=[])
            for block in response.message.content:  # type: ignore
                citations = getattr(block, "citations", None)
                if not citations:
                    continue
                for citation in citations:
                    model_response.citations.raw.append(citation.model_dump())  # type: ignore
                    # Web search citations
                    if isinstance(citation, CitationsWebSearchResultLocation):
                        model_response.citations.urls.append(UrlCitation(url=citation.url, title=citation.cited_text))  # type: ignore
                    # Document citations
                    elif isinstance(citation, CitationPageLocation):
                        model_response.citations.documents.append(  # type: ignore
                            DocumentCitation(document_title=citation.document_title, cited_text=citation.cited_text)
                        )

        # Enhanced usage metrics for streaming responses
        if hasattr(response, "usage") and response.usage is not None:
            usage_dict = {
                "input_tokens": response.usage.input_tokens or 0,
                "output_tokens": response.usage.output_tokens or 0,
            }

            # Map Anthropic cache metrics to standard field names
            if hasattr(response.usage, "cache_creation_input_tokens") and response.usage.cache_creation_input_tokens:
                usage_dict["cache_write_tokens"] = response.usage.cache_creation_input_tokens

            if hasattr(response.usage, "cache_read_input_tokens") and response.usage.cache_read_input_tokens:
                usage_dict["cached_tokens"] = response.usage.cache_read_input_tokens

            # Enhanced cache metrics for 1-hour cache (beta feature)
            if hasattr(response.usage, "cache_creation") and response.usage.cache_creation:
                cache_creation = response.usage.cache_creation
                if hasattr(cache_creation, "ephemeral_5m_input_tokens"):
                    usage_dict["cache_5m_creation_tokens"] = cache_creation.ephemeral_5m_input_tokens
                if hasattr(cache_creation, "ephemeral_1h_input_tokens"):
                    usage_dict["cache_1h_creation_tokens"] = cache_creation.ephemeral_1h_input_tokens

            # Enhanced cache read metrics for different TTLs
            if hasattr(response.usage, "cache_read") and response.usage.cache_read:
                cache_read = response.usage.cache_read
                if hasattr(cache_read, "ephemeral_5m_input_tokens"):
                    usage_dict["cache_5m_read_tokens"] = cache_read.ephemeral_5m_input_tokens
                if hasattr(cache_read, "ephemeral_1h_input_tokens"):
                    usage_dict["cache_1h_read_tokens"] = cache_read.ephemeral_1h_input_tokens

            model_response.response_usage = usage_dict

        # Capture the Beta response
        try:
            if (
                isinstance(response, BetaRawContentBlockDeltaEvent)
                and isinstance(response.delta, BetaTextDelta)
                and response.delta.text is not None
            ):
                model_response.content = response.delta.text
        except Exception as e:
            log_error(f"Error parsing Beta response: {e}")

        return model_response
