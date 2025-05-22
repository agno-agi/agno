from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.models.anthropic import Claude as AnthropicClaude
from agno.models.message import Message
from agno.utils.log import log_error, log_warning
from agno.utils.models.aws_claude import format_messages

try:
    from anthropic import AnthropicBedrock, APIConnectionError, APIStatusError, AsyncAnthropicBedrock, RateLimitError
    from anthropic.types import Message as AnthropicMessage
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

    id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    name: str = "AwsBedrockAnthropicClaude"
    provider: str = "AwsBedrock"

    aws_access_key: Optional[str] = None
    aws_secret_key: Optional[str] = None
    aws_region: Optional[str] = None
    session: Optional[Session] = None

    # -*- Request parameters
    max_tokens: int = 4096
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None

    # -*- Request parameters
    request_params: Optional[Dict[str, Any]] = None
    # -*- Client parameters
    client_params: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Returns:
            Dict[str, Any]: The dictionary representation of the model.
        """
        _dict = super().to_dict()
        _dict["max_tokens"] = self.max_tokens
        _dict["temperature"] = self.temperature
        _dict["top_p"] = self.top_p
        _dict["top_k"] = self.top_k
        _dict["stop_sequences"] = self.stop_sequences
        return _dict

    client: Optional[AnthropicBedrock] = None  # type: ignore
    async_client: Optional[AsyncAnthropicBedrock] = None  # type: ignore

    def get_client(self):
        """
        Get the Bedrock client.

        Returns:
            AnthropicBedrock: The Bedrock client.
        """
        if self.client is not None and not self.client.is_closed():
            return self.client

        if self.session:
            credentials = self.session.get_credentials()
            client_params = {
                "aws_access_key": credentials.access_key,
                "aws_secret_key": credentials.secret_key,
                "aws_session_token": credentials.token,
                "aws_region": self.session.region_name,
            }
        else:
            self.aws_access_key = self.aws_access_key or getenv("AWS_ACCESS_KEY")
            self.aws_secret_key = self.aws_secret_key or getenv("AWS_SECRET_KEY")
            self.aws_region = self.aws_region or getenv("AWS_REGION")

            client_params = {
                "aws_secret_key": self.aws_secret_key,
                "aws_access_key": self.aws_access_key,
                "aws_region": self.aws_region,
            }

        if self.client_params:
            client_params.update(self.client_params)

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

        if self.session:
            credentials = self.session.get_credentials()
            client_params = {
                "aws_access_key": credentials.access_key,
                "aws_secret_key": credentials.secret_key,
                "aws_session_token": credentials.token,
                "aws_region": self.session.region_name,
            }
        else:
            client_params = {
                "aws_secret_key": self.aws_secret_key,
                "aws_access_key": self.aws_access_key,
                "aws_region": self.aws_region,
            }

        if self.client_params:
            client_params.update(self.client_params)

        self.async_client = AsyncAnthropicBedrock(
            **client_params,  # type: ignore
        )
        return self.async_client

    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """
        Generate keyword arguments for API requests.

        Returns:
            Dict[str, Any]: The keyword arguments for API requests.
        """
        _request_params: Dict[str, Any] = {}
        if self.max_tokens:
            _request_params["max_tokens"] = self.max_tokens
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def invoke(
        self,
        messages: List[Message],
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AnthropicMessage:
        """
        Send a request to the Anthropic API to generate a response.
        """

        try:
            chat_messages, system_message = format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message, tools)

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
        request_kwargs = self._prepare_request_kwargs(system_message, tools)

        try:
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
    ) -> AnthropicMessage:
        """
        Send an asynchronous request to the Anthropic API to generate a response.
        """

        try:
            chat_messages, system_message = format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message, tools)

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
            request_kwargs = self._prepare_request_kwargs(system_message, tools)
            async with self.get_async_client().messages.stream(
                model=self.id,
                messages=chat_messages,  # type: ignore
                **request_kwargs,
            ) as stream:
                async for chunk in stream:
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
