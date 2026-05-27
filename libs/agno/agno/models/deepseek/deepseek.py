from dataclasses import dataclass, field
from os import getenv
from typing import Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_warning
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message


@dataclass
class DeepSeek(OpenAILike):
    """
    A class for interacting with DeepSeek models.

    Attributes:
        id (str): The model id. Defaults to "deepseek-chat".
        name (str): The model name. Defaults to "DeepSeek".
        provider (str): The provider name. Defaults to "DeepSeek".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.deepseek.com".
    """

    id: str = "deepseek-chat"
    name: str = "DeepSeek"
    provider: str = "DeepSeek"

    api_key: Optional[str] = field(default_factory=lambda: getenv("DEEPSEEK_API_KEY"))
    base_url: str = "https://api.deepseek.com"

    # Their support for structured outputs is currently broken
    supports_native_structured_outputs: bool = False

    def _get_client_params(self) -> Dict[str, Any]:
        # Fetch API key from env if not already set
        if not self.api_key:
            self.api_key = getenv("DEEPSEEK_API_KEY")
            if not self.api_key:
                # Raise error immediately if key is missing
                raise ModelAuthenticationError(
                    message="DEEPSEEK_API_KEY not set. Please set the DEEPSEEK_API_KEY environment variable.",
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

    def _format_message(self, message: Message, compress_tool_results: bool = False) -> Dict[str, Any]:
        """
        Format a message into the format expected by OpenAI.

        Args:
            message (Message): The message to format.
            compress_tool_results: Whether to compress tool results.

        Returns:
            Dict[str, Any]: The formatted message.
        """
        tool_result = message.get_content(use_compressed_content=compress_tool_results)

        message_dict: Dict[str, Any] = {
            "role": self.role_map[message.role] if self.role_map else self.default_role_map[message.role],
            "content": tool_result,
            "name": message.name,
            "tool_call_id": message.tool_call_id,
            "tool_calls": message.tool_calls,
            "reasoning_content": message.reasoning_content,
        }
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        # Ignore non-string message content
        # because we assume that the images/audio are already added to the message
        if (message.images is not None and len(message.images) > 0) or (
            message.audio is not None and len(message.audio) > 0
        ):
            # Ignore non-string message content
            # because we assume that the images/audio are already added to the message
            if isinstance(message.content, str):
                message_dict["content"] = [{"type": "text", "text": message.content}]
                if message.images is not None:
                    message_dict["content"].extend(images_to_message(images=message.images))

                if message.audio is not None:
                    message_dict["content"].extend(audio_to_message(audio=message.audio))

        if message.audio_output is not None:
            message_dict["content"] = ""
            message_dict["audio"] = {"id": message.audio_output.id}

        if message.videos is not None and len(message.videos) > 0:
            log_warning("Video input is currently unsupported.")

        if message.files is not None:
            # Ensure content is a list of parts
            content = message_dict.get("content")
            if isinstance(content, str):  # wrap existing text
                text = content
                message_dict["content"] = [{"type": "text", "text": text}]
            elif content is None:
                message_dict["content"] = []
            # Insert each file part before text parts
            for file in message.files:
                file_part = _format_file_for_message(file)
                if file_part:
                    message_dict["content"].insert(0, file_part)

        # Manually add the content field even if it is None
        if message.content is None:
            message_dict["content"] = ""
        return message_dict
