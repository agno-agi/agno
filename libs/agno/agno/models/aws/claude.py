import json
from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from agno.exceptions import ModelProviderError, ModelRateLimitError
from agno.media import Image
from agno.models.anthropic import Claude as AnthropicClaude
from agno.models.message import Message
from agno.utils.log import log_error, log_warning

try:
    from anthropic import AnthropicBedrock, APIConnectionError, APIStatusError, AsyncAnthropicBedrock, RateLimitError
    from anthropic.types import Message as AnthropicMessage
    from anthropic.types import (
        TextBlock,
        ToolUseBlock,
    )
except ImportError:
    log_error("`anthropic[bedrock]` not installed. Please install it via `pip install anthropic[bedrock]`.")
    raise

try:
    from boto3.session import Session
except ImportError:
    log_error("`boto3` not installed. Please install it via `pip install boto3`.")
    raise


ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "user",
}


def _format_image_for_message(image: Image) -> Optional[Dict[str, Any]]:
    """
    Add an image to a message by converting it to base64 encoded format.
    """
    using_filetype = False

    import base64

    # 'imghdr' was deprecated in Python 3.11: https://docs.python.org/3/library/imghdr.html
    # 'filetype' used as a fallback
    try:
        import imghdr
    except (ModuleNotFoundError, ImportError):
        try:
            import filetype

            using_filetype = True
        except (ModuleNotFoundError, ImportError):
            raise ImportError("`filetype` not installed. Please install using `pip install filetype`")

    type_mapping = {
        "jpeg": "image/jpeg",
        "jpg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }

    try:
        # Case 1: Image is a URL
        if image.url is not None:
            content_bytes = image.image_url_content

        # Case 2: Image is a local file path
        elif image.filepath is not None:
            from pathlib import Path

            path = Path(image.filepath) if isinstance(image.filepath, str) else image.filepath
            if path.exists() and path.is_file():
                with open(image.filepath, "rb") as f:
                    content_bytes = f.read()
            else:
                log_error(f"Image file not found: {image}")
                return None

        # Case 3: Image is a bytes object
        elif image.content is not None:
            content_bytes = image.content

        else:
            log_error(f"Unsupported image type: {type(image)}")
            return None

        if using_filetype:
            kind = filetype.guess(content_bytes)
            if not kind:
                log_error("Unable to determine image type")
                return None

            img_type = kind.extension
        else:
            img_type = imghdr.what(None, h=content_bytes)  # type: ignore

        if not img_type:
            log_error("Unable to determine image type")
            return None

        media_type = type_mapping.get(img_type)
        if not media_type:
            log_error(f"Unsupported image type: {img_type}")
            return None

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(content_bytes).decode("utf-8"),  # type: ignore
            },
        }

    except Exception as e:
        log_error(f"Error processing image: {e}")
        return None


def _format_messages(messages: List[Message]) -> Tuple[List[Dict[str, str]], str]:
    """
    Process the list of messages and separate them into API messages and system messages.

    Args:
        messages (List[Message]): The list of messages to process.

    Returns:
        Tuple[List[Dict[str, str]], str]: A tuple containing the list of API messages and the concatenated system messages.
    """

    chat_messages: List[Dict[str, str]] = []
    system_messages: List[str] = []

    for message in messages:
        content = message.content or ""
        if message.role == "system":
            if content is not None:
                system_messages.append(content)  # type: ignore
            continue
        elif message.role == "user":
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]

            if message.images is not None:
                for image in message.images:
                    image_content = _format_image_for_message(image)
                    if image_content:
                        content.append(image_content)

            if message.files is not None and len(message.files) > 0:
                log_warning("Files are not supported for AWS Bedrock Claude")

            if message.audio is not None and len(message.audio) > 0:
                log_warning("Audio is not supported for AWS Bedrock Claude")

            if message.videos is not None and len(message.videos) > 0:
                log_warning("Video is not supported for AWS Bedrock Claude")

        # Handle tool calls from history
        elif message.role == "assistant":
            content = []

            if isinstance(message.content, str) and message.content:
                content.append(TextBlock(text=message.content, type="text"))

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    content.append(
                        ToolUseBlock(
                            id=tool_call["id"],
                            input=json.loads(tool_call["function"]["arguments"])
                            if "arguments" in tool_call["function"]
                            else {},
                            name=tool_call["function"]["name"],
                            type="tool_use",
                        )
                    )
        chat_messages.append({"role": ROLE_MAP[message.role], "content": content})  # type: ignore
    return chat_messages, " ".join(system_messages)


@dataclass
class Claude(AnthropicClaude):
    """
    AWS Bedrock Claude model.

    Args:
        aws_region (Optional[str]): The AWS region to use.
        aws_access_key (Optional[str]): The AWS access key to use.
        aws_secret_key (Optional[str]): The AWS secret key to use.
        session (Optional[Session]): A boto3 Session object to use for authentication.
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
        if self.client is not None:
            return self.client

        client_params = {}

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
        if self.async_client is not None:
            return self.async_client

        client_params = {}

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

    def invoke(self, messages: List[Message]) -> AnthropicMessage:
        """
        Send a request to the Anthropic API to generate a response.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AnthropicMessage: The response from the model.

        Raises:
            APIConnectionError: If there are network connectivity issues
            RateLimitError: If the API rate limit is exceeded
            APIStatusError: For other API-related errors
        """

        try:
            chat_messages, system_message = _format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message)

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

    def invoke_stream(self, messages: List[Message]) -> Any:
        """
        Stream a response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.
        """

        chat_messages, system_message = _format_messages(messages)
        request_kwargs = self._prepare_request_kwargs(system_message)

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

    async def ainvoke(self, messages: List[Message]) -> AnthropicMessage:
        """
        Send an asynchronous request to the Anthropic API to generate a response.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            AnthropicMessage: The response from the model.

        Raises:
            APIConnectionError: If there are network connectivity issues
            RateLimitError: If the API rate limit is exceeded
            APIStatusError: For other API-related errors
        """

        try:
            chat_messages, system_message = _format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message)

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

    async def ainvoke_stream(self, messages: List[Message]) -> AsyncIterator[Any]:
        """
        Stream an asynchronous response from the Anthropic API.

        Args:
            messages (List[Message]): A list of messages to send to the model.

        Returns:
            Any: The streamed response from the model.
        """

        try:
            chat_messages, system_message = _format_messages(messages)
            request_kwargs = self._prepare_request_kwargs(system_message)
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
