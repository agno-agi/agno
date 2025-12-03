from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.models.anthropic import Claude as AnthropicClaude
from agno.models.message import Message
from agno.metrics import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.utils.http import get_default_async_client, get_default_sync_client
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.models.claude import format_tools_for_model

try:
    from anthropic import AnthropicBedrock, AsyncAnthropicBedrock
except ImportError:
    raise ImportError("`anthropic[bedrock]` not installed. Please install using `pip install anthropic[bedrock]`")

try:
    from boto3.session import Session
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`")


@dataclass
class Claude(AnthropicClaude):
    """
    AWS Bedrock Claude model.

    For more information, see: https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic.html
    """

    id: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    name: str = "AwsBedrockAnthropicClaude"
    provider: str = "AwsBedrock"

    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    aws_region: Optional[str] = None
    api_key: Optional[str] = None
    session: Optional[Session] = None

    client: Optional[AnthropicBedrock] = None  # type: ignore
    async_client: Optional[AsyncAnthropicBedrock] = None  # type: ignore

    def __post_init__(self):
        """Validate model configuration after initialization"""
        # Validate thinking support immediately at model creation
        if self.thinking:
            self._validate_thinking_support()
        # Overwrite output schema support for AWS Bedrock Claude
        self.supports_native_structured_outputs = False
        self.supports_json_schema_outputs = False

    def _get_client_params(self) -> Dict[str, Any]:
        if self.session:
            credentials = self.session.get_credentials()
            client_params: Dict[str, Any] = {
                "aws_access_key": credentials.access_key,
                "aws_secret_key": credentials.secret_key,
                "aws_session_token": credentials.token,
                "aws_region": self.session.region_name,
            }
        else:
            self.api_key = self.api_key or getenv("AWS_BEDROCK_API_KEY")
            if self.api_key:
                self.aws_region = self.aws_region or getenv("AWS_REGION")
                client_params = {
                    "api_key": self.api_key,
                }
                if self.aws_region:
                    client_params["aws_region"] = self.aws_region
            else:
                self.aws_access_key = self.aws_access_key or getenv("AWS_ACCESS_KEY")
                self.aws_secret_key = self.aws_secret_key or getenv("AWS_SECRET_KEY")
                self.aws_region = self.aws_region or getenv("AWS_REGION")

                client_params = {
                    "aws_secret_key": self.aws_secret_key,
                    "aws_access_key": self.aws_access_key,
                    "aws_region": self.aws_region,
                }
        if not (self.aws_access_key or (self.aws_access_key and self.aws_secret_key)):
            log_error(
                "AWS credentials not found. Please either set the AWS_BEDROCK_API_KEY or AWS_ACCESS_KEY and AWS_SECRET_KEY environment variables."
            )

        if self.timeout is not None:
            client_params["timeout"] = self.timeout

        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def get_client(self):
        """
        Get the Bedrock client.

        Returns:
            AnthropicBedrock: The Bedrock client.
        """
        if self.client is not None and not self.client.is_closed():
            return self.client

        client_params = self._get_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.Client):
                client_params["http_client"] = self.http_client
            else:
                log_warning("http_client is not an instance of httpx.Client. Using default global httpx.Client.")
                # Use global sync client when user http_client is invalid
                client_params["http_client"] = get_default_sync_client()
        else:
            # Use global sync client when no custom http_client is provided
            client_params["http_client"] = get_default_sync_client()

        self.client = AnthropicBedrock(
            **client_params,  # type: ignore
        )
        return self.client

    def get_async_client(self):
        """
        Get the Bedrock async client.

        Returns:
            AsyncAnthropicBedrock: The Bedrock async client.
        """
        if self.async_client is not None:
            return self.async_client

        client_params = self._get_client_params()

        if self.http_client:
            if isinstance(self.http_client, httpx.AsyncClient):
                client_params["http_client"] = self.http_client
            else:
                log_warning(
                    "http_client is not an instance of httpx.AsyncClient. Using default global httpx.AsyncClient."
                )
                # Use global async client when user http_client is invalid
                client_params["http_client"] = get_default_async_client()
        else:
            # Use global async client when no custom http_client is provided
            client_params["http_client"] = get_default_async_client()

        self.async_client = AsyncAnthropicBedrock(
            **client_params,  # type: ignore
        )
        return self.async_client

    def get_request_params(
        self,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The keyword arguments for API requests.
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
        if self.timeout:
            _request_params["timeout"] = self.timeout

        # Build betas list - include existing betas and add new one if needed
        betas_list = list(self.betas) if self.betas else []

        # Include betas if any are present
        if betas_list:
            _request_params["betas"] = betas_list

        if self.request_params:
            _request_params.update(self.request_params)

        if _request_params:
            log_debug(f"Calling {self.provider} with request parameters: {_request_params}", log_level=2)
        return _request_params

    def _prepare_request_kwargs(
        self,
        system_message: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> ModelResponse:
        """
        Send a request to the Anthropic API to generate a response.
        """

        try:
            chat_messages, system_message = format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message, tools)

            # Initialize MessageMetrics and start timer
            self._ensure_message_metrics_initialized(assistant_message)
            response = self.get_client().messages.create(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            )
            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(response, response_format=response_format)

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

        # Format tools (this will handle strict mode)
        if tools:
            request_kwargs["tools"] = format_tools_for_model(tools)

        try:
            # Initialize MessageMetrics and start timer
            self._ensure_message_metrics_initialized(assistant_message)

            with self.get_client().messages.stream(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            ) as stream:
                for chunk in stream:
                    yield self._parse_provider_response_delta(chunk)

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
    ) -> ModelResponse:
        """
        Send an asynchronous request to the Anthropic API to generate a response.
        """

        try:
            chat_messages, system_message = format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message, tools)

            # Initialize MessageMetrics and start timer
            self._ensure_message_metrics_initialized(assistant_message)

            response = await self.get_async_client().messages.create(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            )

            assistant_message.metrics.stop_timer()

            model_response = self._parse_provider_response(response, response_format=response_format)

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
    ) -> AsyncIterator[ModelResponse]:
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
            request_kwargs = self._prepare_request_kwargs(system_message, tools)

            # Initialize MessageMetrics and start timer
            self._ensure_message_metrics_initialized(assistant_message)

            async with self.get_async_client().messages.stream(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            ) as stream:
                async for chunk in stream:
                    yield self._parse_provider_response_delta(chunk)

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
