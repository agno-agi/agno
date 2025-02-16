from collections.abc import AsyncIterator
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterator, List, Optional, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelProviderError
from agno.media import AudioOutput
from agno.models.base import Model, MessageData
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.utils.log import logger
from agno.utils.openai import add_audio_to_message, add_images_to_message

try:
    from openai import APIConnectionError, APIStatusError, RateLimitError
    from openai import AsyncOpenAI as AsyncOpenAIClient
    from openai import OpenAI as OpenAIClient
    from openai.types.chat import ChatCompletionAudio
    from openai.types.chat.chat_completion import ChatCompletion
    from openai.types.chat.chat_completion_chunk import (
        ChatCompletionChunk,
        ChoiceDelta,
        ChoiceDeltaToolCall,
    )
    from openai.types.chat.parsed_chat_completion import ParsedChatCompletion
except ModuleNotFoundError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class OpenAIRealtime(Model):

    id: str = "gpt-4o"
    name: str = "OpenAIChat"
    provider: str = "OpenAI"
    supports_structured_outputs: bool = True

    # Realtime parameters
    connection: Optional[Any] = None

    # Request parameters
    store: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Any] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    modalities: Optional[List[str]] = None
    audio: Optional[Dict[str, Any]] = None
    presence_penalty: Optional[float] = None
    response_format: Optional[Any] = None
    seed: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    temperature: Optional[float] = None
    user: Optional[str] = None
    top_p: Optional[float] = None
    extra_headers: Optional[Any] = None
    extra_query: Optional[Any] = None
    request_params: Optional[Dict[str, Any]] = None

    # Client parameters
    api_key: Optional[str] = None
    organization: Optional[str] = None
    base_url: Optional[Union[str, httpx.URL]] = None
    timeout: Optional[float] = None
    max_retries: Optional[int] = None
    default_headers: Optional[Any] = None
    default_query: Optional[Any] = None
    http_client: Optional[httpx.Client] = None
    client_params: Optional[Dict[str, Any]] = None

    # OpenAI clients
    client: Optional[OpenAIClient] = None
    async_client: Optional[AsyncOpenAIClient] = None

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

    def get_client(self) -> OpenAIClient:
        """
        Returns an OpenAI client.

        Returns:
            OpenAIClient: An instance of the OpenAI client.
        """
        pass

    def get_async_client(self) -> AsyncOpenAIClient:
        """
        Returns an asynchronous OpenAI client.

        Returns:
            AsyncOpenAIClient: An instance of the asynchronous OpenAI client.
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
        return AsyncOpenAIClient(**client_params)

    def invoke(self, messages: List[Message]) -> Union[ChatCompletion, ParsedChatCompletion]:
        pass

    async def ainvoke(self, messages: List[Message]) -> Union[ChatCompletion, ParsedChatCompletion]:
        pass

    def invoke_stream(self, messages: List[Message]) -> Iterator[ChatCompletionChunk]:
        pass

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[ChatCompletionChunk]:
        pass

    def parse_provider_response(self, event: ChatCompletionChunk) -> str:
        pass

    def parse_provider_response_delta(self, response: Any) -> ModelResponse:
        pass

    async def aprocess_response_stream(
        self, messages: List[Message], assistant_message: Message, stream_data: MessageData
    ) -> AsyncIterator[ModelResponse]:
        """
        Process a streaming response from the model.
        """
        try:
            # Send all messages in the conversation
            for message in messages:
                await self.connection.conversation.item.create(
                        item={
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": message.content}],
                        }
                    )
            await self.connection.response.create()

            # Process the streaming response
            async for event in self.connection:
                if event.type == 'response.text.delta':
                    yield ModelResponse(content=event.delta)
                elif event.type == 'response.audio_transcript.delta':
                    yield ModelResponse(content=event.delta)
                elif event.type == 'response.done':
                    return  # Use return instead of break to maintain connection
        except Exception as e:
            logger.error(f"Error in stream processing: {e}")
            raise

    async def aresponse_stream(self, messages: List[Message]) -> AsyncIterator[ModelResponse]:
        """
        Generate an asynchronous streaming response from the model.
        """
        logger.debug(f"---------- {self.get_provider()} Async Response Stream Start ----------")
        self._log_messages(messages)

        try:
            # Only create new connection if one doesn't exist
            if self.connection is None:
                self.connection = await self.get_async_client().beta.realtime.connect(model=self.id).enter()

            assistant_message = Message(role=self.assistant_message_role)
            stream_data = MessageData()

            assistant_message.metrics.start_timer()
            async for response in self.aprocess_response_stream(
                messages=messages, assistant_message=assistant_message, stream_data=stream_data,
            ):
                yield response
            assistant_message.metrics.stop_timer()

            messages.append(assistant_message)
            assistant_message.log(metrics=True)

        except Exception as e:
            logger.error(f"Error in response stream: {e}")
            raise

    async def create_connection(self) -> None:
        """
        Create a new connection to the OpenAI API.
        """
        self.connection = await self.get_async_client().beta.realtime.connect(model=self.id).enter()

    async def create_connection(self):
        """Create and store a persistent connection."""
        self.connection = await self.get_async_client().beta.realtime.connect(model=self.id).enter()
        await self.connection.session.update(session={'modalities': ['text']})


    async def send_text_message(self, message: str):
        """Send a message through the connection."""
        await self.connection.conversation.item.create(
            item={
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": message}],
            }
        )
        await self.connection.response.create()

    async def process_stream(self, console, audio_player):
        """Process the response stream and output to console."""
        async for event in self.connection:
            if event.type == 'response.text.delta':
                console.print(event.delta, end="")
            elif event.type == "response.audio.delta":
                audio_player.play(event.delta)
            elif event.type == "response.audio_transcript.delta":
                console.print(event.delta, end="")
            elif event.type == 'response.done':
                break
        console.print("\n")

    async def send_audio_message(self, audio_file: bytes):
        """Send a message through the connection."""
        await self.connection.input_audio_buffer.append(audio=audio_file)
        await self.connection.input_audio_buffer.commit()
        await self.connection.response.create()

    async def close_connection(self):
        """Close the connection if it exists."""
        if self.connection:
            await self.connection.close()

