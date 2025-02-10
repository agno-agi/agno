from dataclasses import dataclass
from os import getenv
from typing import Optional

from agno.media import AudioOutput
from agno.models.base import Metrics
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.utils.log import logger

try:
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    from openai.types.completion_usage import CompletionUsage
except ModuleNotFoundError:
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


@dataclass
class DeepSeek(OpenAILike):
    """
    A class for interacting with DeepSeek models.

    For more information, see: https://api-docs.deepseek.com/
    """

    id: str = "deepseek-chat"
    name: str = "DeepSeek"
    provider: str = "DeepSeek"

    api_key: Optional[str] = getenv("DEEPSEEK_API_KEY", None)
    base_url: str = "https://api.deepseek.com"

    def create_assistant_message(
        self,
        response_message: ChatCompletionMessage,
        metrics: Metrics,
        response_usage: Optional[CompletionUsage],
    ) -> Message:
        """
        Create an assistant message from the response.

        Args:
            response_message (ChatCompletionMessage): The response message.
            metrics (Metrics): The metrics.
            response_usage (Optional[CompletionUsage]): The response usage.

        Returns:
            Message: The assistant message.
        """
        assistant_message = Message(
            role=response_message.role or "assistant",
            content=response_message.content,
            reasoning_content=response_message.reasoning_content
            if hasattr(response_message, "reasoning_content")
            else None,
        )
        if response_message.tool_calls is not None and len(response_message.tool_calls) > 0:
            try:
                assistant_message.tool_calls = [t.model_dump() for t in response_message.tool_calls]
            except Exception as e:
                logger.warning(f"Error processing tool calls: {e}")
        if hasattr(response_message, "audio") and response_message.audio is not None:
            try:
                assistant_message.audio_output = AudioOutput(
                    id=response_message.audio.id,
                    content=response_message.audio.data,
                    expires_at=response_message.audio.expires_at,
                    transcript=response_message.audio.transcript,
                )
            except Exception as e:
                logger.warning(f"Error processing audio: {e}")

        # Update metrics
        self.update_usage_metrics(assistant_message, metrics, response_usage)
        return assistant_message
