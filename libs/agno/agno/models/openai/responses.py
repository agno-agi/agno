from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union
import asyncio
from agno.models.response import ModelResponse
from agno.utils.openai_responses import images_to_message
import httpx

from agno.exceptions import ModelProviderError
from agno.models.base import Model
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
    if parsed_version.major == 0:
        import warnings
        warnings.warn("OpenAI v1.x is recommended for the Responses API", UserWarning)

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
            # "response_format": self.response_format,  # TODO: Add this back in
            "metadata": self.metadata,
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

        # Add tools
        if self._tools is not None and len(self._tools) > 0:
            request_params["tools"] = self._tools

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

        # Manually add the content field even if it is None
        if message.content is None:
            message_dict["content"] = None

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

        if hasattr(response, "error") and response.error:
            raise ModelProviderError(
                message=response.error.get("message", "Unknown model error"),
                model_name=self.name,
                model_id=self.id,
            )

        # Get response message
        response_message = response.choices[0].message

        # Parse structured outputs if enabled
        try:
            if (
                self.response_format is not None
                and self.structured_outputs
                and issubclass(self.response_format, BaseModel)
            ):
                parsed_object = response_message.parsed  # type: ignore
                if parsed_object is not None:
                    model_response.parsed = parsed_object
        except Exception as e:
            logger.warning(f"Error retrieving structured outputs: {e}")

        # Add role
        if response_message.role is not None:
            model_response.role = response_message.role

        # Add content
        if response_message.content is not None:
            model_response.content = response_message.content

        # Add tool calls
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                model_response.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                logger.warning(f"Error processing tool calls: {e}")

        # Add audio transcript to content if available
        response_audio: Optional[ChatCompletionAudio] = response_message.audio
        if response_audio and response_audio.transcript and not model_response.content:
            model_response.content = response_audio.transcript

        # Add audio if present
        if hasattr(response_message, "audio") and response_message.audio is not None:
            # If the audio output modality is requested, we can extract an audio response
            try:
                if isinstance(response_message.audio, dict):
                    model_response.audio = AudioResponse(
                        id=response_message.audio.get("id"),
                        content=response_message.audio.get("data"),
                        expires_at=response_message.audio.get("expires_at"),
                        transcript=response_message.audio.get("transcript"),
                    )
                else:
                    model_response.audio = AudioResponse(
                        id=response_message.audio.id,
                        content=response_message.audio.data,
                        expires_at=response_message.audio.expires_at,
                        transcript=response_message.audio.transcript,
                    )
            except Exception as e:
                logger.warning(f"Error processing audio: {e}")

        if hasattr(response_message, "reasoning_content") and response_message.reasoning_content is not None:
            model_response.reasoning_content = response_message.reasoning_content

        if response.usage is not None:
            model_response.response_usage = response.usage

        return model_response

    def parse_provider_response_delta(self, response_delta: ChatCompletionChunk) -> ModelResponse:
        """
        Parse the OpenAI streaming response into a ModelResponse.

        Args:
            response_delta: Raw response chunk from OpenAI

        Returns:
            ProviderResponse: Iterator of parsed response data
        """
        model_response = ModelResponse()
        if response_delta.choices and len(response_delta.choices) > 0:
            delta: ChoiceDelta = response_delta.choices[0].delta

            # Add content
            if delta.content is not None:
                model_response.content = delta.content

            # Add tool calls
            if delta.tool_calls is not None:
                model_response.tool_calls = delta.tool_calls  # type: ignore

            # Add audio if present
            if hasattr(delta, "audio") and delta.audio is not None:
                try:
                    if isinstance(delta.audio, dict):
                        model_response.audio = AudioResponse(
                            id=delta.audio.get("id"),
                            content=delta.audio.get("data"),
                            expires_at=delta.audio.get("expires_at"),
                            transcript=delta.audio.get("transcript"),
                            sample_rate=24000,
                            mime_type="pcm16",
                        )
                    else:
                        model_response.audio = AudioResponse(
                            id=delta.audio.id,
                            content=delta.audio.data,
                            expires_at=delta.audio.expires_at,
                            transcript=delta.audio.transcript,
                            sample_rate=24000,
                            mime_type="pcm16",
                        )
                except Exception as e:
                    logger.warning(f"Error processing audio: {e}")

        # Add usage metrics if present
        if response_delta.usage is not None:
            model_response.response_usage = response_delta.usage

        return model_response
