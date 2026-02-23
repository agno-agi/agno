import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

import httpx
from pydantic import BaseModel, ValidationError

from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.models.base import Model
from agno.models.message import Citations, DocumentCitation, Message, UrlCitation
from agno.models.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.tools.function import Function
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.models.claude import MCPServerConfiguration, format_messages, format_tools_for_model
from agno.utils.tokens import count_schema_tokens

try:
    from anthropic import Anthropic as AnthropicClient
    from anthropic import (
        APIConnectionError,
        APIStatusError,
        RateLimitError,
    )
    from anthropic import (
        AsyncAnthropic as AsyncAnthropicClient,
    )
    from anthropic.lib.streaming._beta_types import (
        BetaRawContentBlockStartEvent,
        ParsedBetaContentBlockStopEvent,
        ParsedBetaMessageStopEvent,
    )
    from anthropic.types import (
        CitationPageLocation,
        CitationsWebSearchResultLocation,
        ContentBlockDeltaEvent,
        ContentBlockStartEvent,
        ContentBlockStopEvent,
        MessageDeltaUsage,
        # MessageDeltaEvent,  # Currently broken
        MessageStopEvent,
        Usage,
    )
    from anthropic.types import (
        Message as AnthropicMessage,
    )

except ImportError as e:
    raise ImportError("`anthropic` not installed. Please install it with `pip install anthropic`") from e

# Import Beta types
try:
    from anthropic.types.beta import BetaRawContentBlockDeltaEvent, BetaTextDelta
    from anthropic.types.beta.beta_message import BetaMessage
    from anthropic.types.beta.beta_usage import BetaUsage
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

    # Models that DO NOT support extended thinking
    # All future models are assumed to support thinking
    # Based on official Anthropic documentation: https://docs.claude.com/en/docs/about-claude/models/overview
    NON_THINKING_MODELS = {
        # Claude Haiku 3 family (does not support thinking)
        "claude-3-haiku-20240307",
        # Claude Haiku 3.5 family (does not support thinking)
        "claude-3-5-haiku-20241022",
        "claude-3-5-haiku-latest",
    }

    # Models that DO NOT support native structured outputs
    # All future models are assumed to support structured outputs
    NON_STRUCTURED_OUTPUT_MODELS = {
        # Claude 3.x family (all versions)
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        "claude-3-opus",
        "claude-3-sonnet",
        "claude-3-haiku",
        # Claude 3.5 family (all versions except Sonnet 4.5)
        "claude-3-5-sonnet-20240620",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet",
        "claude-3-5-haiku-20241022",
        "claude-3-5-haiku-latest",
        "claude-3-5-haiku",
        # Claude Sonnet 4.x family (versions before 4.5)
        "claude-sonnet-4-20250514",
        "claude-sonnet-4",
        # Claude Opus 4.x family (versions before 4.1 and 4.5)
        # (Add any Opus 4.x models released before 4.1/4.5 if they exist)
    }

    id: str = "claude-sonnet-4-5-20250929"
    name: str = "Claude"
    provider: str = "Anthropic"

    # Request parameters
    max_tokens: Optional[int] = 8192
    thinking: Optional[Dict[str, Any]] = None
    temperature: Optional[float] = None
    stop_sequences: Optional[List[str]] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    cache_system_prompt: Optional[bool] = False
    extended_cache_time: Optional[bool] = False
    request_params: Optional[Dict[str, Any]] = None

    # Anthropic beta and experimental features
    betas: Optional[List[str]] = None  # Enables specific experimental or newly released features.
    context_management: Optional[Dict[str, Any]] = None
    mcp_servers: Optional[List[MCPServerConfiguration]] = None
    skills: Optional[List[Dict[str, str]]] = (
        None  # e.g., [{"type": "anthropic", "skill_id": "pptx", "version": "latest"}]
    )

    # Client parameters
    api_key: Optional[str] = None
    auth_token: Optional[str] = None
    default_headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None
    http_client: Optional[Union[httpx.Client, httpx.AsyncClient]] = None
    client_params: Optional[Dict[str, Any]] = None

    client: Optional[AnthropicClient] = None
    async_client: Optional[AsyncAnthropicClient] = None

    def __post_init__(self):
        """Validate model configuration after initialization"""
        # Validate thinking support immediately at model creation
        if self.thinking:
            self._validate_thinking_support()
        # Set structured outputs capability flag for supported models
        if self._supports_structured_outputs():
            self.supports_native_structured_outputs = True
        # Set up skills configuration if skills are enabled
        if self.skills:
            self._setup_skills_configuration()

    def _get_client_params(self) -> Dict[str, Any]:
        client_params: Dict[str, Any] = {}

        self.api_key = self.api_key or getenv("ANTHROPIC_API_KEY")
        self.auth_token = self.auth_token or getenv("ANTHROPIC_AUTH_TOKEN")
        if not (self.api_key or self.auth_token):
            log_error(
                "ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN not set. Please set the ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN environment variable."
            )

        # Add API key to client parameters
        client_params["api_key"] = self.api_key
        client_params["auth_token"] = self.auth_token
        if self.timeout is not None:
            client_params["timeout"] = self.timeout

        # Add additional client parameters
        if self.client_params is not None:
            client_params.update(self.client_params)
        if self.default_headers is not None:
            client_params["default_headers"] = self.default_headers
        return client_params

    def _supports_structured_outputs(self) -> bool:
        """
        Check if the current model supports native structured outputs.

        Returns:
            bool: True if model supports structured outputs
        """
        # If model is in blacklist, it doesn't support structured outputs
        if self.id in self.NON_STRUCTURED_OUTPUT_MODELS:
            return False

        # Check for legacy model patterns which don't support structured outputs
        if self.id.startswith("claude-3-"):
            return False
        if self.id.startswith("claude-sonnet-4-") and not self.id.startswith("claude-sonnet-4-5"):
            return False
        if self.id.startswith("claude-opus-4-") and not (
            self.id.startswith("claude-opus-4-1") or self.id.startswith("claude-opus-4-5")
        ):
            return False

        return True

    def _using_structured_outputs(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Check if structured outputs are being used in this request.

        Args:
            response_format: Response format parameter
            tools: Tools list to check for strict mode

        Returns:
            bool: True if structured outputs are in use
        """
        # Check for output_format usage
        if response_format is not None:
            if self._supports_structured_outputs():
                return True
            else:
                log_warning(
                    f"Model '{self.id}' does not support structured outputs. "
                    "Structured output features will not be available for this model."
                )

        # Check for strict tools
        if tools:
            for tool in tools:
                if tool.get("type") == "function":
                    func_def = tool.get("function", {})
                    if func_def.get("strict") is True:
                        return True

        return False

    def _validate_thinking_support(self) -> None:
        """
        Validate that the current model supports extended thinking.

        Raises:
            ValueError: If thinking is enabled but the model doesn't support it
        """
        if self.thinking and self.id in self.NON_THINKING_MODELS:
            non_thinking_models = "\n  - ".join(sorted(self.NON_THINKING_MODELS))
            raise ValueError(
                f"Model '{self.id}' does not support extended thinking.\n\n"
                f"The following models do NOT support thinking:\n  - {non_thinking_models}\n\n"
                f"All other Claude models support extended thinking by default.\n"
                f"For more information, see: https://docs.anthropic.com/en/docs/about-claude/models/overview"
            )

    def _setup_skills_configuration(self) -> None:
        """
        Set up configuration for Claude Agent Skills.
        Automatically configures betas array with required values.

        Skills enable document creation capabilities (PowerPoint, Excel, Word, PDF).
        For more information, see: https://docs.claude.com/en/docs/agents-and-tools/agent-skills/quickstart
        """
        # Required betas for skills
        required_betas = ["code-execution-2025-08-25", "skills-2025-10-02"]

        # Initialize or merge betas
        if self.betas is None:
            self.betas = required_betas
        else:
            # Add required betas if not present
            for beta in required_betas:
                if beta not in self.betas:
                    self.betas.append(beta)

    def _ensure_additional_properties_false(self, schema: Dict[str, Any]) -> None:
        """
        Recursively ensure all object types have additionalProperties: false.
        """
        if isinstance(schema, dict):
            if schema.get("type") == "object":
                schema["additionalProperties"] = False

            # Recursively process nested schemas
            for key, value in schema.items():
                if key in ["properties", "items", "allOf", "anyOf", "oneOf"]:
                    if isinstance(value, dict):
                        self._ensure_additional_properties_false(value)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                self._ensure_additional_properties_false(item)

    def _build_output_format(self, response_format: Optional[Union[Dict, Type[BaseModel]]]) -> Optional[Dict[str, Any]]:
        """
        Build Anthropic output_format parameter from response_format.

        Args:
            response_format: Pydantic model or dict format

        Returns:
            Dict with output_format structure or None
        """
        if response_format is None:
            return None

        if not self._supports_structured_outputs():
            return None

        # Handle Pydantic BaseModel
        if isinstance(response_format, type) and issubclass(response_format, BaseModel):
            try:
                # Try to use Anthropic SDK's transform_schema helper if available
                from anthropic import transform_schema

                schema = transform_schema(response_format.model_json_schema())
            except (ImportError, AttributeError):
                # Fallback to direct schema conversion
                schema = response_format.model_json_schema()
                # Ensure additionalProperties is False
                if isinstance(schema, dict):
                    if "additionalProperties" not in schema:
                        schema["additionalProperties"] = False
                    # Recursively ensure all object types have additionalProperties: false
                    self._ensure_additional_properties_false(schema)

            return {"type": "json_schema", "schema": schema}

        # Handle dict format
        elif isinstance(response_format, dict):
            # Claude only supports json_schema, not json_object
            if response_format.get("type") == "json_object":
                return None
            return response_format

        return None

    def _validate_structured_outputs_usage(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Validate that structured outputs are only used with supported models.

        Raises:
            ValueError: If structured outputs are used with unsupported model
        """
        if not self._using_structured_outputs(response_format, tools):
            return

        if not self._supports_structured_outputs():
            raise ValueError(f"Model '{self.id}' does not support structured outputs.\n\n")

    def _has_beta_features(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Check if the model has any Anthropic beta features enabled."""
        return (
            self.mcp_servers is not None
            or self.context_management is not None
            or self.skills is not None
            or self.betas is not None
            or self._using_structured_outputs(response_format, tools)
        )

    def get_client(self) -> AnthropicClient:
        """
        Returns an instance of the Anthropic client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        _client_params = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                _client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                # Use global sync client when user http_client is invalid
                _client_params["http_client"] = get_default_sync_client()
        else:
            # Use global sync client when no custom http_client is provided
            _client_params["http_client"] = get_default_sync_client()
        self.client = AnthropicClient(**_client_params)
        return self.client

    def get_async_client(self) -> AsyncAnthropicClient:
        """
        Returns an instance of the async Anthropic client.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        _client_params = self._get_client_params()
        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                _client_params["http_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                # Use global async client when user http_client is invalid
                _client_params["http_client"] = get_default_async_client()
        else:
            # Use global async client when no custom http_client is provided
            _client_params["http_client"] = get_default_async_client()
        self.async_client = AsyncAnthropicClient(**_client_params)
        return self.async_client

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        model_dict = super().to_dict()
        model_dict.update(
            {
                "max_tokens": self.max_tokens,
                "thinking": self.thinking,
                "temperature": self.temperature,
                "stop_sequences": self.stop_sequences,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "cache_system_prompt": self.cache_system_prompt,
                "extended_cache_time": self.extended_cache_time,
                "betas": self.betas,
            }
        )
        cleaned_dict = {k: v for k, v in model_dict.items() if v is not None}
        return cleaned_dict

    def count_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        anthropic_messages, system_prompt = format_messages(messages, compress_tool_results=True)
        anthropic_tools = None
        if tools:
            formatted_tools = self._format_tools(tools)
            anthropic_tools = format_tools_for_model(formatted_tools)

        kwargs: Dict[str, Any] = {"messages": anthropic_messages, "model": self.id}
        if system_prompt:
            kwargs["system"] = system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = self.get_client().messages.count_tokens(**kwargs)
        return response.input_tokens + count_schema_tokens(response_format, self.id)

    async def acount_tokens(
        self,
        messages: List[Message],
        tools: Optional[List[Union[Function, Dict[str, Any]]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> int:
        anthropic_messages, system_prompt = format_messages(messages, compress_tool_results=True)
        anthropic_tools = None
        if tools:
            formatted_tools = self._format_tools(tools)
            anthropic_tools = format_tools_for_model(formatted_tools)

        kwargs: Dict[str, Any] = {"messages": anthropic_messages, "model": self.id}
        if system_prompt:
            kwargs["system"] = system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = await self.get_async_client().messages.count_tokens(**kwargs)
        return response.input_tokens + count_schema_tokens(response_format, self.id)

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.
        """
        # Validate thinking support if thinking is enabled
        if self.thinking:
            self._validate_thinking_support()

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

        # Build betas list - include existing betas and add new one if needed
        betas_list = list(self.betas) if self.betas else []

        # Add structured outputs beta header if using structured outputs
        if self._using_structured_outputs(response_format, tools):
            beta_header = "structured-outputs-2025-11-13"
            if beta_header not in betas_list:
                betas_list.append(beta_header)

        # Include betas if any are present
        if betas_list:
            _request_params["betas"] = betas_list

        if self.context_management:
            _request_params["context_management"] = self.context_management
        if self.mcp_servers:
            _request_params["mcp_servers"] = [
                {k: v for k, v in asdict(server).items() if v is not None} for server in self.mcp_servers
            ]
        if self.skills:
            _request_params["container"] = {"skills": self.skills}
        if self.request_params:
            _request_params.update(self.request_params)

        return _request_params

    def _prepare_request_kwargs(
        self,
        system_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> Dict[str, Any]:
        """
        Prepare the request keyword arguments for the API call.

        Args:
            system_message (str): The concatenated system messages.
            tools: Optional list of tools
            response_format: Optional response format (Pydantic model or dict)

        Returns:
            Dict[str, Any]: The request keyword arguments.
        """
        # Validate structured outputs usage
        self._validate_structured_outputs_usage(response_format, tools)

        # Pass response_format and tools to get_request_params for beta header handling
        request_kwargs = self.get_request_params(response_format=response_format, tools=tools).copy()
        if system_message:
            if self.cache_system_prompt:
                cache_control = (
                    {"type": "ephemeral", "ttl": "1h"}
                    if self.extended_cache_time is not None and self.extended_cache_time is True
                    else {"type": "ephemeral"}
                )
                request_kwargs["system"] = [{"text": system_message, "type": "text", "cache_control": cache_control}]
            else:
                request_kwargs["system"] = [{"text": system_message, "type": "text"}]

        # Add code execution tool if skills are enabled
        if self.skills:
            code_execution_tool = {"type": "code_execution_20250825", "name": "code_execution"}
            if tools:
                # Add code_execution to existing tools, code execution is needed for generating and processing files
                tools = tools + [code_execution_tool]
            else:
                tools = [code_execution_tool]

        # Format tools (this will handle strict mode)
        if tools:
            request_kwargs["tools"] = format_tools_for_model(tools)

        # Build output_format if response_format is provided
        output_format = self._build_output_format(response_format)
        if output_format:
            request_kwargs["output_format"] = output_format

        if request_kwargs:
            log_debug(f"Calling {self.provider} with request parameters: {request_kwargs}", log_level=2)
        return request_kwargs

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
        Send a request to the Anthropic API to generate a response.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
            request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            if self._has_beta_features(response_format=response_format, tools=tools):
                assistant_message.metrics.start_timer()
                provider_response = self.get_client().beta.messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                )
            else:
                assistant_message.metrics.start_timer()
                provider_response = self.get_client().messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                )

            assistant_message.metrics.stop_timer()

            # Parse the response into an Agno ModelResponse object
            model_response = self._parse_provider_response(provider_response, response_format=response_format)  # type: ignore

            return model_response

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
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
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
        chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
        request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            # Beta features
            if self._has_beta_features(response_format=response_format, tools=tools):
                assistant_message.metrics.start_timer()
                with self.get_client().beta.messages.stream(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                ) as stream:
                    for chunk in stream:
                        yield self._parse_provider_response_delta(chunk, response_format=response_format)  # type: ignore
            else:
                assistant_message.metrics.start_timer()
                with self.get_client().messages.stream(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                ) as stream:
                    for chunk in stream:  # type: ignore
                        yield self._parse_provider_response_delta(chunk, response_format=response_format)  # type: ignore

            assistant_message.metrics.stop_timer()

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
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Send an asynchronous request to the Anthropic API to generate a response.
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
            request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            # Beta features
            if self._has_beta_features(response_format=response_format, tools=tools):
                assistant_message.metrics.start_timer()
                provider_response = await self.get_async_client().beta.messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                )
            else:
                assistant_message.metrics.start_timer()
                provider_response = await self.get_async_client().messages.create(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                )

            assistant_message.metrics.stop_timer()

            # Parse the response into an Agno ModelResponse object
            model_response = self._parse_provider_response(provider_response, response_format=response_format)  # type: ignore

            return model_response

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
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """
        Stream an asynchronous response from the Anthropic API.
        Args:
            messages (List[Message]): A list of messages to send to the model.
        Returns:
            AsyncIterator[ModelResponse]: An async iterator of processed model responses.
        Raises:
            APIConnectionError: If there are network connectivity issues
            RateLimitError: If the API rate limit is exceeded
            APIStatusError: For other API-related errors
        """
        try:
            if run_response and run_response.metrics:
                run_response.metrics.set_time_to_first_token()

            chat_messages, system_message = format_messages(messages, compress_tool_results=compress_tool_results)
            request_kwargs = self._prepare_request_kwargs(system_message, tools=tools, response_format=response_format)

            if assistant_message.metrics is None:
                assistant_message.metrics = MessageMetrics()
            if self._has_beta_features(response_format=response_format, tools=tools):
                assistant_message.metrics.start_timer()
                async with self.get_async_client().beta.messages.stream(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                ) as stream:
                    async for chunk in stream:
                        yield self._parse_provider_response_delta(chunk, response_format=response_format)  # type: ignore
            else:
                assistant_message.metrics.start_timer()
                async with self.get_async_client().messages.stream(
                    model=self.id,
                    messages=chat_messages,  # type: ignore
                    **request_kwargs,
                ) as stream:
                    async for chunk in stream:  # type: ignore
                        yield self._parse_provider_response_delta(chunk, response_format=response_format)  # type: ignore

            assistant_message.metrics.stop_timer()

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

    def get_system_message_for_model(self, tools: Optional[List[Any]] = None) -> Optional[str]:
        if tools is not None and len(tools) > 0:
            tool_call_prompt = "Do not reflect on the quality of the returned search results in your response\n\n"
            return tool_call_prompt
        return None

    def _parse_provider_response(
        self,
        response: Union[AnthropicMessage, BetaMessage],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        **kwargs,
    ) -> ModelResponse:
        """
        Parse the Claude response into a ModelResponse.

        Args:
            response: Raw response from Anthropic
            response_format: Optional response format for structured output parsing

        Returns:
            ModelResponse: Parsed response data
        """
        model_response = ModelResponse()

        # Add role (Claude always uses 'assistant')
        model_response.role = response.role or "assistant"

        if response.content:
            for block in response.content:
                if block.type == "text":
                    text_content = block.text

                    if model_response.content is None:
                        model_response.content = text_content
                    else:
                        model_response.content += text_content

                    # Handle structured outputs (JSON outputs)
                    if (
                        response_format is not None
                        and isinstance(response_format, type)
                        and issubclass(response_format, BaseModel)
                    ):
                        if text_content:
                            try:
                                # Parse JSON from text content
                                parsed_data = json.loads(text_content)
                                # Validate against Pydantic model
                                model_response.parsed = response_format.model_validate(parsed_data)
                                log_debug(f"Successfully parsed structured output: {model_response.parsed}")
                            except json.JSONDecodeError as e:
                                log_warning(f"Failed to parse JSON from structured output: {e}")
                            except ValidationError as e:
                                log_warning(f"Failed to validate structured output against schema: {e}")
                            except Exception as e:
                                log_warning(f"Unexpected error parsing structured output: {e}")

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
                    model_response.reasoning_content = block.thinking
                    model_response.provider_data = {
                        "signature": block.signature,
                    }
                elif block.type == "redacted_thinking":
                    model_response.redacted_reasoning_content = block.data

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

                    model_response.tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": function_def,
                        }
                    )

        # Add usage metrics
        if response.usage is not None:
            model_response.response_usage = self._get_metrics(response.usage)

        # Capture context management information if present
        if self.context_management is not None and hasattr(response, "context_management"):
            if response.context_management is not None:  # type: ignore
                model_response.provider_data = model_response.provider_data or {}
                if hasattr(response.context_management, "model_dump"):
                    model_response.provider_data["context_management"] = response.context_management.model_dump()  # type: ignore
                else:
                    model_response.provider_data["context_management"] = response.context_management  # type: ignore
        # Extract file IDs if skills are enabled
        if self.skills and response.content:
            file_ids: List[str] = []
            for block in response.content:
                if block.type == "bash_code_execution_tool_result":
                    if hasattr(block, "content") and hasattr(block.content, "content"):
                        if isinstance(block.content.content, list):
                            for output_block in block.content.content:
                                if hasattr(output_block, "file_id"):
                                    file_ids.append(output_block.file_id)

            if file_ids:
                if model_response.provider_data is None:
                    model_response.provider_data = {}
                model_response.provider_data["file_ids"] = file_ids

        return model_response

    def _parse_provider_response_delta(
        self,
        response: Union[
            ContentBlockStartEvent,
            ContentBlockDeltaEvent,
            ContentBlockStopEvent,
            MessageStopEvent,
            BetaRawContentBlockDeltaEvent,
            BetaRawContentBlockStartEvent,
            ParsedBetaContentBlockStopEvent,
            ParsedBetaMessageStopEvent,
        ],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
    ) -> ModelResponse:
        """
        Parse the Claude streaming response into ModelProviderResponse objects.

        Args:
            response: Raw response chunk from Anthropic
            response_format: Optional response format for structured output parsing

        Returns:
            ModelResponse: Iterator of parsed response data
        """
        model_response = ModelResponse()

        if isinstance(response, (ContentBlockStartEvent, BetaRawContentBlockStartEvent)):
            if response.content_block.type == "redacted_reasoning_content":
                model_response.redacted_reasoning_content = response.content_block.data

        if isinstance(response, (ContentBlockDeltaEvent, BetaRawContentBlockDeltaEvent)):
            # Handle text content
            if response.delta.type == "text_delta":
                model_response.content = response.delta.text
            # Handle thinking content
            elif response.delta.type == "thinking_delta":
                model_response.reasoning_content = response.delta.thinking
            elif response.delta.type == "signature_delta":
                model_response.provider_data = {
                    "signature": response.delta.signature,
                }

        elif isinstance(response, (ContentBlockStopEvent, ParsedBetaContentBlockStopEvent)):
            if response.content_block.type == "tool_use":  # type: ignore
                tool_use = response.content_block  # type: ignore
                tool_name = tool_use.name  # type: ignore
                tool_input = tool_use.input  # type: ignore

                function_def = {"name": tool_name}
                if tool_input:
                    function_def["arguments"] = json.dumps(tool_input)

                model_response.extra = model_response.extra or {}

                model_response.tool_calls = [
                    {
                        "id": tool_use.id,  # type: ignore
                        "type": "function",
                        "function": function_def,
                    }
                ]

        # Capture citations from the final response and handle structured outputs
        elif isinstance(response, (MessageStopEvent, ParsedBetaMessageStopEvent)):
            # In streaming mode, content has already been emitted via ContentBlockDeltaEvent chunks
            # Setting content here would cause duplication since _populate_stream_data accumulates with +=
            # Keep content empty to avoid duplication
            model_response.content = ""
            model_response.citations = Citations(raw=[], urls=[], documents=[])

            # Accumulate text content for structured output parsing (but don't set model_response.content)
            # The text was already streamed via ContentBlockDeltaEvent chunks
            accumulated_text = ""

            for block in response.message.content:  # type: ignore
                # Handle text blocks for structured output parsing
                if block.type == "text":
                    accumulated_text += block.text  # type: ignore

                # Handle citations
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

            # Handle structured outputs (JSON outputs) from accumulated text
            # Note: We parse from accumulated_text but don't set model_response.content to avoid duplication
            # The content was already streamed via ContentBlockDeltaEvent chunks
            if (
                response_format is not None
                and isinstance(response_format, type)
                and issubclass(response_format, BaseModel)
            ):
                if accumulated_text:
                    try:
                        # Parse JSON from accumulated text content
                        parsed_data = json.loads(accumulated_text)
                        # Validate against Pydantic model
                        model_response.parsed = response_format.model_validate(parsed_data)
                        log_debug(f"Successfully parsed structured output from stream: {model_response.parsed}")
                    except json.JSONDecodeError as e:
                        log_warning(f"Failed to parse JSON from structured output in stream: {e}")
                    except ValidationError as e:
                        log_warning(f"Failed to validate structured output against schema in stream: {e}")
                    except Exception as e:
                        log_warning(f"Unexpected error parsing structured output in stream: {e}")

            # Capture context management information if present
            if self.context_management is not None and hasattr(response.message, "context_management"):  # type: ignore
                context_mgmt = response.message.context_management  # type: ignore
                if context_mgmt is not None:
                    model_response.provider_data = model_response.provider_data or {}
                    if hasattr(context_mgmt, "model_dump"):
                        model_response.provider_data["context_management"] = context_mgmt.model_dump()
                    else:
                        model_response.provider_data["context_management"] = context_mgmt

        if (
            isinstance(response, (MessageStopEvent, ParsedBetaMessageStopEvent))
            and hasattr(response, "message")
            and hasattr(response.message, "usage")
            and response.message.usage is not None  # type: ignore
        ):
            model_response.response_usage = self._get_metrics(response.message.usage)  # type: ignore

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

    def _get_metrics(self, response_usage: Union[Usage, MessageDeltaUsage, BetaUsage]) -> MessageMetrics:
        """
        Parse the given Anthropic-specific usage into an Agno MessageMetrics object.

        Args:
            response_usage: Usage data from Anthropic

        Returns:
            MessageMetrics: Parsed metrics data
        """
        metrics = MessageMetrics()

        metrics.input_tokens = response_usage.input_tokens or 0
        metrics.output_tokens = response_usage.output_tokens or 0
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens
        metrics.cache_read_tokens = response_usage.cache_read_input_tokens or 0
        metrics.cache_write_tokens = response_usage.cache_creation_input_tokens or 0

        # Anthropic-specific additional fields
        if response_usage.server_tool_use:
            metrics.provider_metrics = {"server_tool_use": response_usage.server_tool_use.model_dump()}
        if isinstance(response_usage, Usage):
            if response_usage.service_tier:
                metrics.provider_metrics = metrics.provider_metrics or {}
                metrics.provider_metrics["service_tier"] = response_usage.service_tier

        return metrics
