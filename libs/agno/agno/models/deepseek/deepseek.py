from dataclasses import dataclass, field
from os import getenv
from typing import Any, ClassVar, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import log_warning
from agno.utils.openai import _format_file_for_message, audio_to_message, images_to_message


@dataclass
class DeepSeek(OpenAILike):
    """
    A class for interacting with DeepSeek models.

    DeepSeek V4 models have thinking mode enabled by default. In thinking mode,
    the following parameters have no effect when set (they are ignored by the API):
    - temperature
    - top_p
    - presence_penalty
    - frequency_penalty

    For more information, see: https://api-docs.deepseek.com/zh-cn/guides/thinking_mode

    Attributes:
        id (str): The model id. Defaults to "deepseek-v4-pro".
        name (str): The model name. Defaults to "DeepSeek".
        provider (str): The provider name. Defaults to "DeepSeek".
        api_key (Optional[str]): The API key.
        base_url (str): The base URL. Defaults to "https://api.deepseek.com".
    """

    id: str = "deepseek-v4-pro"
    name: str = "DeepSeek"
    provider: str = "DeepSeek"

    api_key: Optional[str] = field(default_factory=lambda: getenv("DEEPSEEK_API_KEY"))
    base_url: str = "https://api.deepseek.com"

    # Their support for structured outputs is currently broken
    supports_native_structured_outputs: bool = False

    # Agent scenarios default to max reasoning effort.
    # For non-agent use cases, set to "high" or None to disable.
    # Note: In thinking mode, temperature/top_p/presence_penalty/frequency_penalty are ignored.
    reasoning_effort: Optional[str] = "max"

    # Deprecated model IDs: these still work but will be removed in a future API version.
    # deepseek-chat -> non-thinking mode of deepseek-v4-flash
    # deepseek-reasoner -> thinking mode of deepseek-v4-flash
    _deprecated_model_ids: ClassVar[Dict[str, str]] = {
        "deepseek-chat": "deepseek-v4-flash",
        "deepseek-reasoner": "deepseek-v4-flash",
    }

    # Models that should NOT have thinking enabled by default.
    # deepseek-chat maps to non-thinking mode for backward compatibility.
    _non_thinking_model_ids: ClassVar[set] = {
        "deepseek-chat",
    }

    def __post_init__(self):
        if self.id in self._deprecated_model_ids:
            suggested = self._deprecated_model_ids[self.id]
            log_warning(
                f"Model '{self.id}' is deprecated and will be removed in a future API version. "
                f"Use '{suggested}' instead."
            )

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

    def get_request_params(
        self,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
    ) -> Dict[str, Any]:
        request_params = super().get_request_params(
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )

        # Enable thinking mode by default for all models except the legacy
        # deepseek-chat (which maps to non-thinking mode for backward compat).
        # Required for multi-turn reasoning_content concatenation with tool calls.
        if self.id not in self._non_thinking_model_ids:
            if "extra_body" not in request_params:
                request_params["extra_body"] = {"thinking": {"type": "enabled"}}
            elif "thinking" not in request_params["extra_body"]:
                request_params["extra_body"]["thinking"] = {"type": "enabled"}
        else:
            # For non-thinking models, strip reasoning_effort as it has no effect
            # and may cause unexpected streaming behavior.
            request_params.pop("reasoning_effort", None)

        return request_params

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
