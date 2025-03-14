import json
from dataclasses import asdict, dataclass
from time import time
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict, Field

from agno.media import Audio, AudioResponse, File, Image, Video
from agno.utils.log import logger
from agno.utils.timer import Timer


class MessageReferences(BaseModel):
    """References added to user message"""

    # The query used to retrieve the references.
    query: str
    # References (from the vector database or function calls)
    references: Optional[List[Dict[str, Any]]] = None
    # Time taken to retrieve the references.
    time: Optional[float] = None


class UrlCitation(BaseModel):
    """URL of the citation"""

    url: Optional[str] = None
    title: Optional[str] = None


class DocumentCitation(BaseModel):
    """Document of the citation"""

    document_title: Optional[str] = None
    cited_text: Optional[str] = None
    file_name: Optional[str] = None


class Citations(BaseModel):
    """Citations for the message"""

    # Raw citations from the model
    raw: Optional[Any] = None

    # URLs of the citations.
    urls: Optional[List[UrlCitation]] = None

    # Document Citations
    documents: Optional[List[DocumentCitation]] = None


@dataclass
class MessageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens_details: Optional[dict] = None
    completion_tokens_details: Optional[dict] = None

    additional_metrics: Optional[dict] = None

    time: Optional[float] = None
    time_to_first_token: Optional[float] = None

    timer: Optional[Timer] = None

    def _to_dict(self) -> Dict[str, Any]:
        metrics_dict = asdict(self)
        metrics_dict.pop("timer")
        metrics_dict = {
            k: v
            for k, v in metrics_dict.items()
            if v is not None and (not isinstance(v, (int, float)) or v != 0) and (not isinstance(v, dict) or len(v) > 0)
        }
        return metrics_dict

    def start_timer(self):
        if self.timer is None:
            self.timer = Timer()
        self.timer.start()

    def stop_timer(self, set_time: bool = True):
        if self.timer is not None:
            self.timer.stop()
            if set_time:
                self.time = self.timer.elapsed

    def set_time_to_first_token(self):
        if self.timer is not None:
            self.time_to_first_token = self.timer.elapsed

    def __add__(self, other: "MessageMetrics") -> "MessageMetrics":
        # Create new instance with summed basic metrics
        result = MessageMetrics(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )

        # Handle prompt_tokens_details
        if self.prompt_tokens_details or other.prompt_tokens_details:
            result.prompt_tokens_details = {}
            # Merge from self
            if self.prompt_tokens_details:
                result.prompt_tokens_details.update(self.prompt_tokens_details)
            # Add values from other
            if other.prompt_tokens_details:
                for key, value in other.prompt_tokens_details.items():
                    result.prompt_tokens_details[key] = result.prompt_tokens_details.get(key, 0) + value

        # Handle completion_tokens_details similarly
        if self.completion_tokens_details or other.completion_tokens_details:
            result.completion_tokens_details = {}
            if self.completion_tokens_details:
                result.completion_tokens_details.update(self.completion_tokens_details)
            if other.completion_tokens_details:
                for key, value in other.completion_tokens_details.items():
                    result.completion_tokens_details[key] = result.completion_tokens_details.get(key, 0) + value

        # Handle additional metrics
        if self.additional_metrics or other.additional_metrics:
            result.additional_metrics = {}
            if self.additional_metrics:
                result.additional_metrics.update(self.additional_metrics)
            if other.additional_metrics:
                result.additional_metrics.update(other.additional_metrics)

        # Sum times if both exist
        if self.time is not None and other.time is not None:
            result.time = self.time + other.time
        elif self.time is not None:
            result.time = self.time
        elif other.time is not None:
            result.time = other.time

        # Handle time_to_first_token (take the first non-None value)
        result.time_to_first_token = self.time_to_first_token or other.time_to_first_token

        return result

    def __radd__(self, other: "MessageMetrics") -> "MessageMetrics":
        if other == 0:  # Handle sum() starting value
            return self
        return self + other


class Message(BaseModel):
    """Message sent to the Model"""

    # The role of the message author.
    # One of system, user, assistant, or tool.
    role: str
    # The contents of the message.
    content: Optional[Union[List[Any], str]] = None
    # An optional name for the participant.
    # Provides the model information to differentiate between participants of the same role.
    name: Optional[str] = None
    # Tool call that this message is responding to.
    tool_call_id: Optional[str] = None
    # The tool calls generated by the model, such as function calls.
    tool_calls: Optional[List[Dict[str, Any]]] = None

    # Additional modalities
    audio: Optional[Sequence[Audio]] = None
    images: Optional[Sequence[Image]] = None
    videos: Optional[Sequence[Video]] = None
    files: Optional[Sequence[File]] = None

    # Output from the models
    audio_output: Optional[AudioResponse] = None

    # The thinking content from the model
    thinking: Optional[str] = None
    redacted_thinking: Optional[str] = None

    # Data from the provider we might need on subsequent messages
    provider_data: Optional[Dict[str, Any]] = None

    # Citations received from the model
    citations: Optional[Citations] = None

    # --- Data not sent to the Model API ---
    # The reasoning content from the model
    reasoning_content: Optional[str] = None
    # The name of the tool called
    tool_name: Optional[str] = None
    # Arguments passed to the tool
    tool_args: Optional[Any] = None
    # The error of the tool call
    tool_call_error: Optional[bool] = None
    # If True, the agent will stop executing after this tool call.
    stop_after_tool_call: bool = False
    # When True, the message will be added to the agent's memory.
    add_to_agent_memory: bool = True
    # This flag is enabled when a message is fetched from the agent's memory.
    from_history: bool = False
    # Metrics for the message.
    metrics: MessageMetrics = Field(default_factory=MessageMetrics)
    # The references added to the message for RAG
    references: Optional[MessageReferences] = None
    # The Unix timestamp the message was created.
    created_at: int = Field(default_factory=lambda: int(time()))

    model_config = ConfigDict(extra="allow", populate_by_name=True, arbitrary_types_allowed=True)

    def get_content_string(self) -> str:
        """Returns the content as a string."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            if len(self.content) > 0 and isinstance(self.content[0], dict) and "text" in self.content[0]:
                return self.content[0].get("text", "")
            else:
                return json.dumps(self.content)
        return ""

    def to_dict(self) -> Dict[str, Any]:
        """Returns the message as a dictionary."""
        message_dict = {
            "content": self.content,
            "reasoning_content": self.reasoning_content,
            "from_history": self.from_history,
            "stop_after_tool_call": self.stop_after_tool_call,
            "role": self.role,
            "name": self.name,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_call_error": self.tool_call_error,
            "tool_calls": self.tool_calls,
            "thinking": self.thinking,
            "redacted_thinking": self.redacted_thinking,
        }
        # Filter out None and empty collections
        message_dict = {
            k: v for k, v in message_dict.items() if v is not None and not (isinstance(v, (list, dict)) and len(v) == 0)
        }

        # Convert media objects to dictionaries
        if self.images:
            message_dict["images"] = [img.to_dict() for img in self.images]
        if self.audio:
            message_dict["audio"] = [aud.to_dict() for aud in self.audio]
        if self.videos:
            message_dict["videos"] = [vid.to_dict() for vid in self.videos]
        if self.audio_output:
            message_dict["audio_output"] = self.audio_output.to_dict()

        if self.references:
            message_dict["references"] = self.references.model_dump()
        if self.metrics:
            message_dict["metrics"] = self.metrics._to_dict()
            if not message_dict["metrics"]:
                message_dict.pop("metrics")

        message_dict["created_at"] = self.created_at
        return message_dict

    def to_function_call_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_call_error": self.tool_call_error,
            "metrics": self.metrics,
            "created_at": self.created_at,
        }

    def log(self, metrics: bool = True, level: Optional[str] = None):
        """Log the message to the console

        Args:
            metrics (bool): Whether to log the metrics.
            level (str): The level to log the message at. One of debug, info, warning, or error.
                Defaults to debug.
        """
        _logger = logger.debug
        if level == "info":
            _logger = logger.info
        elif level == "warning":
            _logger = logger.warning
        elif level == "error":
            _logger = logger.error

        _logger(f"============== {self.role} ==============")
        if self.name:
            _logger(f"Name: {self.name}")
        if self.tool_call_id:
            _logger(f"Tool call Id: {self.tool_call_id}")
        if self.thinking:
            _logger(f"<thinking>\n{self.thinking}\n</thinking>")
        if self.content:
            if isinstance(self.content, str) or isinstance(self.content, list):
                _logger(self.content)
            elif isinstance(self.content, dict):
                _logger(json.dumps(self.content, indent=2))
        if self.tool_calls:
            _logger(f"Tool Calls: {json.dumps(self.tool_calls, indent=2)}")
        if self.images:
            _logger(f"Images added: {len(self.images)}")
        if self.videos:
            _logger(f"Videos added: {len(self.videos)}")
        if self.audio:
            _logger(f"Audio Files added: {len(self.audio)}")
        if self.files:
            _logger(f"Files added: {len(self.files)}")

        if metrics and self.metrics is not None and self.metrics != MessageMetrics():
            _logger("**************** METRICS ****************")
            if self.metrics.input_tokens:
                _logger(f"* Input tokens:                {self.metrics.input_tokens}")
            if self.metrics.output_tokens:
                _logger(f"* Output tokens:               {self.metrics.output_tokens}")
            if self.metrics.total_tokens:
                _logger(f"* Total tokens:                {self.metrics.total_tokens}")
            if self.metrics.prompt_tokens_details:
                _logger(f"* Prompt tokens details:       {self.metrics.prompt_tokens_details}")
            if self.metrics.completion_tokens_details:
                _logger(f"* Completion tokens details:   {self.metrics.completion_tokens_details}")
            if self.metrics.time is not None:
                _logger(f"* Time:                        {self.metrics.time:.4f}s")
            if self.metrics.output_tokens and self.metrics.time:
                _logger(f"* Tokens per second:           {self.metrics.output_tokens / self.metrics.time:.4f} tokens/s")
            if self.metrics.time_to_first_token is not None:
                _logger(f"* Time to first token:         {self.metrics.time_to_first_token:.4f}s")
            if self.metrics.additional_metrics:
                _logger(f"* Additional metrics:          {self.metrics.additional_metrics}")
            _logger("**************** METRICS ******************")

    def content_is_valid(self) -> bool:
        """Check if the message content is valid."""

        return self.content is not None and len(self.content) > 0
