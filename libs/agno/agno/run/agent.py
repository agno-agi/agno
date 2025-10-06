from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Citations, Message
from agno.models.metrics import Metrics
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.base import BaseRunOutputEvent, MessageReferences, RunStatus
from agno.utils.log import logger


@dataclass
class RunInput:
    """Container for the raw input data passed to Agent.run().

    This captures the original input exactly as provided by the user,
    separate from the processed messages that go to the model.

    Attributes:
        input_content: The literal input message/content passed to run()
        images: Images directly passed to run()
        videos: Videos directly passed to run()
        audios: Audio files directly passed to run()
        files: Files directly passed to run()
    """

    input_content: Union[str, List, Dict, Message, BaseModel, List[Message]]
    images: Optional[Sequence[Image]] = None
    videos: Optional[Sequence[Video]] = None
    audios: Optional[Sequence[Audio]] = None
    files: Optional[Sequence[File]] = None

    def input_content_string(self) -> str:
        import json

        if isinstance(self.input_content, (str)):
            return self.input_content
        elif isinstance(self.input_content, BaseModel):
            return self.input_content.model_dump_json(exclude_none=True)
        elif isinstance(self.input_content, Message):
            return json.dumps(self.input_content.to_dict())
        elif isinstance(self.input_content, list) and self.input_content and isinstance(self.input_content[0], Message):
            return json.dumps([m.to_dict() for m in self.input_content])
        else:
            return str(self.input_content)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation"""
        result: Dict[str, Any] = {}

        if self.input_content is not None:
            if isinstance(self.input_content, (str)):
                result["input_content"] = self.input_content
            elif isinstance(self.input_content, BaseModel):
                result["input_content"] = self.input_content.model_dump(exclude_none=True)
            elif isinstance(self.input_content, Message):
                result["input_content"] = self.input_content.to_dict()
            elif (
                isinstance(self.input_content, list)
                and self.input_content
                and isinstance(self.input_content[0], Message)
            ):
                result["input_content"] = [m.to_dict() for m in self.input_content]
            else:
                result["input_content"] = self.input_content

        if self.images:
            result["images"] = [img.to_dict() for img in self.images]
        if self.videos:
            result["videos"] = [vid.to_dict() for vid in self.videos]
        if self.audios:
            result["audios"] = [aud.to_dict() for aud in self.audios]
        if self.files:
            result["files"] = [file.to_dict() for file in self.files]

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunInput":
        """Create RunInput from dictionary"""
        images = None
        if data.get("images"):
            images = [Image.model_validate(img_data) for img_data in data["images"]]

        videos = None
        if data.get("videos"):
            videos = [Video.model_validate(vid_data) for vid_data in data["videos"]]

        audios = None
        if data.get("audios"):
            audios = [Audio.model_validate(aud_data) for aud_data in data["audios"]]

        files = None
        if data.get("files"):
            files = [File.model_validate(file_data) for file_data in data["files"]]

        return cls(
            input_content=data.get("input_content", ""), images=images, videos=videos, audios=audios, files=files
        )


class RunEvent(str, Enum):
    """Events that can be sent by the run() functions"""

    run_started = "RunStarted"
    run_content = "RunContent"
    run_intermediate_content = "RunIntermediateContent"
    run_completed = "RunCompleted"
    run_error = "RunError"
    run_cancelled = "RunCancelled"

    run_paused = "RunPaused"
    run_continued = "RunContinued"

    pre_hook_started = "PreHookStarted"
    pre_hook_completed = "PreHookCompleted"

    tool_call_started = "ToolCallStarted"
    tool_call_completed = "ToolCallCompleted"

    reasoning_started = "ReasoningStarted"
    reasoning_step = "ReasoningStep"
    reasoning_completed = "ReasoningCompleted"

    memory_update_started = "MemoryUpdateStarted"
    memory_update_completed = "MemoryUpdateCompleted"

    parser_model_response_started = "ParserModelResponseStarted"
    parser_model_response_completed = "ParserModelResponseCompleted"

    output_model_response_started = "OutputModelResponseStarted"
    output_model_response_completed = "OutputModelResponseCompleted"

    custom_event = "CustomEvent"


@dataclass
class BaseAgentRunEvent(BaseRunOutputEvent):
    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""
    agent_id: str = ""
    agent_name: str = ""
    run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    session_id: Optional[str] = None

    # Step context for workflow execution
    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    step_index: Optional[int] = None
    tools: Optional[List[ToolExecution]] = None

    # For backwards compatibility
    content: Optional[Any] = None

    @property
    def tools_requiring_confirmation(self):
        return [t for t in self.tools if t.requires_confirmation] if self.tools else []

    @property
    def tools_requiring_user_input(self):
        return [t for t in self.tools if t.requires_user_input] if self.tools else []

    @property
    def tools_awaiting_external_execution(self):
        return [t for t in self.tools if t.external_execution_required] if self.tools else []


@dataclass
class RunStartedEvent(BaseAgentRunEvent):
    """Event sent when the run starts"""

    event: str = RunEvent.run_started.value
    model: str = ""
    model_provider: str = ""


@dataclass
class RunContentEvent(BaseAgentRunEvent):
    """Main event for each delta of the RunOutput"""

    event: str = RunEvent.run_content.value
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: Optional[str] = None
    model_provider_data: Optional[Dict[str, Any]] = None
    citations: Optional[Citations] = None
    response_audio: Optional[Audio] = None  # Model audio response
    image: Optional[Image] = None  # Image attached to the response
    references: Optional[List[MessageReferences]] = None
    additional_input: Optional[List[Message]] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None


@dataclass
class IntermediateRunContentEvent(BaseAgentRunEvent):
    event: str = RunEvent.run_intermediate_content.value
    content: Optional[Any] = None
    content_type: str = "str"


@dataclass
class RunCompletedEvent(BaseAgentRunEvent):
    event: str = RunEvent.run_completed.value
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: Optional[str] = None
    citations: Optional[Citations] = None
    model_provider_data: Optional[Dict[str, Any]] = None
    images: Optional[List[Image]] = None  # Images attached to the response
    videos: Optional[List[Video]] = None  # Videos attached to the response
    audio: Optional[List[Audio]] = None  # Audio attached to the response
    response_audio: Optional[Audio] = None  # Model audio response
    references: Optional[List[MessageReferences]] = None
    additional_input: Optional[List[Message]] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None
    metadata: Optional[Dict[str, Any]] = None
    metrics: Optional[Metrics] = None


@dataclass
class RunPausedEvent(BaseAgentRunEvent):
    event: str = RunEvent.run_paused.value
    tools: Optional[List[ToolExecution]] = None

    @property
    def is_paused(self):
        return True


@dataclass
class RunContinuedEvent(BaseAgentRunEvent):
    event: str = RunEvent.run_continued.value


@dataclass
class RunErrorEvent(BaseAgentRunEvent):
    event: str = RunEvent.run_error.value
    content: Optional[str] = None

    # From exceptions
    error_type: Optional[str] = None
    error_id: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None


@dataclass
class RunCancelledEvent(BaseAgentRunEvent):
    event: str = RunEvent.run_cancelled.value
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class PreHookStartedEvent(BaseAgentRunEvent):
    event: str = RunEvent.pre_hook_started.value
    pre_hook_name: Optional[str] = None
    run_input: Optional[RunInput] = None


@dataclass
class PreHookCompletedEvent(BaseAgentRunEvent):
    event: str = RunEvent.pre_hook_completed.value
    pre_hook_name: Optional[str] = None
    run_input: Optional[RunInput] = None


@dataclass
class MemoryUpdateStartedEvent(BaseAgentRunEvent):
    event: str = RunEvent.memory_update_started.value


@dataclass
class MemoryUpdateCompletedEvent(BaseAgentRunEvent):
    event: str = RunEvent.memory_update_completed.value


@dataclass
class ReasoningStartedEvent(BaseAgentRunEvent):
    event: str = RunEvent.reasoning_started.value


@dataclass
class ReasoningStepEvent(BaseAgentRunEvent):
    event: str = RunEvent.reasoning_step.value
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: str = ""


@dataclass
class ReasoningCompletedEvent(BaseAgentRunEvent):
    event: str = RunEvent.reasoning_completed.value
    content: Optional[Any] = None
    content_type: str = "str"


@dataclass
class ToolCallStartedEvent(BaseAgentRunEvent):
    event: str = RunEvent.tool_call_started.value
    tool: Optional[ToolExecution] = None


@dataclass
class ToolCallCompletedEvent(BaseAgentRunEvent):
    event: str = RunEvent.tool_call_completed.value
    tool: Optional[ToolExecution] = None
    content: Optional[Any] = None
    images: Optional[List[Image]] = None  # Images produced by the tool call
    videos: Optional[List[Video]] = None  # Videos produced by the tool call
    audio: Optional[List[Audio]] = None  # Audio produced by the tool call


@dataclass
class ParserModelResponseStartedEvent(BaseAgentRunEvent):
    event: str = RunEvent.parser_model_response_started.value


@dataclass
class ParserModelResponseCompletedEvent(BaseAgentRunEvent):
    event: str = RunEvent.parser_model_response_completed.value


@dataclass
class OutputModelResponseStartedEvent(BaseAgentRunEvent):
    event: str = RunEvent.output_model_response_started.value


@dataclass
class OutputModelResponseCompletedEvent(BaseAgentRunEvent):
    event: str = RunEvent.output_model_response_completed.value


@dataclass
class CustomEvent(BaseAgentRunEvent):
    event: str = RunEvent.custom_event.value


RunOutputEvent = Union[
    RunStartedEvent,
    RunContentEvent,
    IntermediateRunContentEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunCancelledEvent,
    RunPausedEvent,
    RunContinuedEvent,
    PreHookStartedEvent,
    PreHookCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    ReasoningCompletedEvent,
    MemoryUpdateStartedEvent,
    MemoryUpdateCompletedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
    ParserModelResponseStartedEvent,
    ParserModelResponseCompletedEvent,
    OutputModelResponseStartedEvent,
    OutputModelResponseCompletedEvent,
    CustomEvent,
]


# Map event string to dataclass
RUN_EVENT_TYPE_REGISTRY = {
    RunEvent.run_started.value: RunStartedEvent,
    RunEvent.run_content.value: RunContentEvent,
    RunEvent.run_intermediate_content.value: IntermediateRunContentEvent,
    RunEvent.run_completed.value: RunCompletedEvent,
    RunEvent.run_error.value: RunErrorEvent,
    RunEvent.run_cancelled.value: RunCancelledEvent,
    RunEvent.run_paused.value: RunPausedEvent,
    RunEvent.run_continued.value: RunContinuedEvent,
    RunEvent.pre_hook_started.value: PreHookStartedEvent,
    RunEvent.pre_hook_completed.value: PreHookCompletedEvent,
    RunEvent.reasoning_started.value: ReasoningStartedEvent,
    RunEvent.reasoning_step.value: ReasoningStepEvent,
    RunEvent.reasoning_completed.value: ReasoningCompletedEvent,
    RunEvent.memory_update_started.value: MemoryUpdateStartedEvent,
    RunEvent.memory_update_completed.value: MemoryUpdateCompletedEvent,
    RunEvent.tool_call_started.value: ToolCallStartedEvent,
    RunEvent.tool_call_completed.value: ToolCallCompletedEvent,
    RunEvent.parser_model_response_started.value: ParserModelResponseStartedEvent,
    RunEvent.parser_model_response_completed.value: ParserModelResponseCompletedEvent,
    RunEvent.output_model_response_started.value: OutputModelResponseStartedEvent,
    RunEvent.output_model_response_completed.value: OutputModelResponseCompletedEvent,
    RunEvent.custom_event.value: CustomEvent,
}


def run_output_event_from_dict(data: dict) -> BaseRunOutputEvent:
    event_type = data.get("event", "")
    cls = RUN_EVENT_TYPE_REGISTRY.get(event_type)
    if not cls:
        raise ValueError(f"Unknown event type: {event_type}")
    return cls.from_dict(data)  # type: ignore


@dataclass
class RunOutput:
    """Response returned by Agent.run() or Workflow.run() functions"""

    run_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    session_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    workflow_id: Optional[str] = None
    user_id: Optional[str] = None

    # Input media and messages from user
    input: Optional[RunInput] = None

    content: Optional[Any] = None
    content_type: str = "str"

    reasoning_content: Optional[str] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None

    model_provider_data: Optional[Dict[str, Any]] = None

    model: Optional[str] = None
    model_provider: Optional[str] = None
    messages: Optional[List[Message]] = None
    metrics: Optional[Metrics] = None
    additional_input: Optional[List[Message]] = None

    tools: Optional[List[ToolExecution]] = None

    images: Optional[List[Image]] = None  # Images attached to the response
    videos: Optional[List[Video]] = None  # Videos attached to the response
    audio: Optional[List[Audio]] = None  # Audio attached to the response
    files: Optional[List[File]] = None  # Files attached to the response
    response_audio: Optional[Audio] = None  # Model audio response

    citations: Optional[Citations] = None
    references: Optional[List[MessageReferences]] = None

    metadata: Optional[Dict[str, Any]] = None

    created_at: int = field(default_factory=lambda: int(time()))

    events: Optional[List[RunOutputEvent]] = None

    status: RunStatus = RunStatus.running

    # === FOREIGN KEY RELATIONSHIPS ===
    # These fields establish relationships to parent workflow/step structures
    # and should be treated as foreign keys for data integrity
    workflow_step_id: Optional[str] = None  # FK: Points to StepOutput.step_id

    @property
    def is_paused(self):
        return self.status == RunStatus.paused

    @property
    def is_cancelled(self):
        return self.status == RunStatus.cancelled

    @property
    def tools_requiring_confirmation(self):
        return [t for t in self.tools if t.requires_confirmation] if self.tools else []

    @property
    def tools_requiring_user_input(self):
        return [t for t in self.tools if t.requires_user_input] if self.tools else []

    @property
    def tools_awaiting_external_execution(self):
        return [t for t in self.tools if t.external_execution_required] if self.tools else []

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            k: v
            for k, v in asdict(self).items()
            if v is not None
            and k
            not in [
                "messages",
                "tools",
                "metadata",
                "images",
                "videos",
                "audio",
                "files",
                "response_audio",
                "input",
                "citations",
                "events",
                "additional_input",
                "reasoning_steps",
                "reasoning_messages",
                "references",
            ]
        }

        if self.metrics is not None:
            _dict["metrics"] = self.metrics.to_dict() if isinstance(self.metrics, Metrics) else self.metrics

        if self.events is not None:
            _dict["events"] = [e.to_dict() for e in self.events]

        if self.status is not None:
            _dict["status"] = self.status.value if isinstance(self.status, RunStatus) else self.status

        if self.messages is not None:
            _dict["messages"] = [m.to_dict() for m in self.messages]

        if self.metadata is not None:
            _dict["metadata"] = self.metadata

        if self.additional_input is not None:
            _dict["additional_input"] = [m.to_dict() for m in self.additional_input]

        if self.reasoning_messages is not None:
            _dict["reasoning_messages"] = [m.to_dict() for m in self.reasoning_messages]

        if self.reasoning_steps is not None:
            _dict["reasoning_steps"] = [rs.model_dump() for rs in self.reasoning_steps]

        if self.references is not None:
            _dict["references"] = [r.model_dump() for r in self.references]

        if self.images is not None:
            _dict["images"] = []
            for img in self.images:
                if isinstance(img, Image):
                    _dict["images"].append(img.to_dict())
                else:
                    _dict["images"].append(img)

        if self.videos is not None:
            _dict["videos"] = []
            for vid in self.videos:
                if isinstance(vid, Video):
                    _dict["videos"].append(vid.to_dict())
                else:
                    _dict["videos"].append(vid)

        if self.audio is not None:
            _dict["audio"] = []
            for aud in self.audio:
                if isinstance(aud, Audio):
                    _dict["audio"].append(aud.to_dict())
                else:
                    _dict["audio"].append(aud)

        if self.files is not None:
            _dict["files"] = []
            for file in self.files:
                if isinstance(file, File):
                    _dict["files"].append(file.to_dict())
                else:
                    _dict["files"].append(file)

        if self.response_audio is not None:
            if isinstance(self.response_audio, Audio):
                _dict["response_audio"] = self.response_audio.to_dict()
            else:
                _dict["response_audio"] = self.response_audio

        if self.citations is not None:
            if isinstance(self.citations, Citations):
                _dict["citations"] = self.citations.model_dump(exclude_none=True)
            else:
                _dict["citations"] = self.citations

        if self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True, mode="json")

        if self.tools is not None:
            _dict["tools"] = []
            for tool in self.tools:
                if isinstance(tool, ToolExecution):
                    _dict["tools"].append(tool.to_dict())
                else:
                    _dict["tools"].append(tool)

        if self.input is not None:
            _dict["input"] = self.input.to_dict()

        return _dict

    def to_json(self, separators=(", ", ": "), indent: Optional[int] = 2) -> str:
        import json

        try:
            _dict = self.to_dict()
        except Exception:
            logger.error("Failed to convert response to json", exc_info=True)
            raise

        if indent is None:
            return json.dumps(_dict, separators=separators)
        else:
            return json.dumps(_dict, indent=indent, separators=separators)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunOutput":
        if "run" in data:
            data = data.pop("run")

        events = data.pop("events", None)
        events = [run_output_event_from_dict(event) for event in events] if events else None

        messages = data.pop("messages", None)
        messages = [Message.from_dict(message) for message in messages] if messages else None

        citations = data.pop("citations", None)
        citations = Citations.model_validate(citations) if citations else None

        tools = data.pop("tools", [])
        tools = [ToolExecution.from_dict(tool) for tool in tools] if tools else None

        images = data.pop("images", [])
        images = [Image.model_validate(image) for image in images] if images else None

        videos = data.pop("videos", [])
        videos = [Video.model_validate(video) for video in videos] if videos else None

        audio = data.pop("audio", [])
        audio = [Audio.model_validate(audio) for audio in audio] if audio else None

        files = data.pop("files", [])
        files = [File.model_validate(file) for file in files] if files else None

        response_audio = data.pop("response_audio", None)
        response_audio = Audio.model_validate(response_audio) if response_audio else None

        input_data = data.pop("input", None)
        input_obj = None
        if input_data:
            input_obj = RunInput.from_dict(input_data)

        metrics = data.pop("metrics", None)
        if metrics:
            metrics = Metrics(**metrics)

        additional_input = data.pop("additional_input", None)

        if additional_input is not None:
            additional_input = [Message.from_dict(message) for message in additional_input]

        reasoning_steps = data.pop("reasoning_steps", None)
        if reasoning_steps is not None:
            reasoning_steps = [ReasoningStep.model_validate(step) for step in reasoning_steps]

        reasoning_messages = data.pop("reasoning_messages", None)
        if reasoning_messages is not None:
            reasoning_messages = [Message.from_dict(message) for message in reasoning_messages]

        references = data.pop("references", None)
        if references is not None:
            references = [MessageReferences.model_validate(reference) for reference in references]

        return cls(
            messages=messages,
            metrics=metrics,
            citations=citations,
            tools=tools,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            response_audio=response_audio,
            input=input_obj,
            events=events,
            additional_input=additional_input,
            reasoning_steps=reasoning_steps,
            reasoning_messages=reasoning_messages,
            references=references,
            **data,
        )

    def get_content_as_string(self, **kwargs) -> str:
        import json

        from pydantic import BaseModel

        if isinstance(self.content, str):
            return self.content
        elif isinstance(self.content, BaseModel):
            return self.content.model_dump_json(exclude_none=True, **kwargs)
        else:
            return json.dumps(self.content, **kwargs)
