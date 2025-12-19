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
from agno.run.agent import RunEvent, RunOutput, RunOutputEvent, run_output_event_from_dict
from agno.run.base import BaseRunOutputEvent, MessageReferences, RunStatus
from agno.run.requirement import RunRequirement
from agno.utils.log import log_error
from agno.utils.media import (
    reconstruct_audio_list,
    reconstruct_files,
    reconstruct_images,
    reconstruct_response_audio,
    reconstruct_videos,
)


@dataclass
class TeamRunInput:
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

            # Handle input_content provided as a list of Message objects
            elif (
                isinstance(self.input_content, list)
                and self.input_content
                and isinstance(self.input_content[0], Message)
            ):
                result["input_content"] = [m.to_dict() for m in self.input_content]

            # Handle input_content provided as a list of dicts
            elif (
                isinstance(self.input_content, list) and self.input_content and isinstance(self.input_content[0], dict)
            ):
                for content in self.input_content:
                    # Handle media input
                    if isinstance(content, dict):
                        if content.get("images"):
                            content["images"] = [
                                img.to_dict() if isinstance(img, Image) else img for img in content["images"]
                            ]
                        if content.get("videos"):
                            content["videos"] = [
                                vid.to_dict() if isinstance(vid, Video) else vid for vid in content["videos"]
                            ]
                        if content.get("audios"):
                            content["audios"] = [
                                aud.to_dict() if isinstance(aud, Audio) else aud for aud in content["audios"]
                            ]
                        if content.get("files"):
                            content["files"] = [
                                file.to_dict() if isinstance(file, File) else file for file in content["files"]
                            ]
                result["input_content"] = self.input_content
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
    def from_dict(cls, data: Dict[str, Any]) -> "TeamRunInput":
        """Create TeamRunInput from dictionary"""
        images = reconstruct_images(data.get("images"))
        videos = reconstruct_videos(data.get("videos"))
        audios = reconstruct_audio_list(data.get("audios"))
        files = reconstruct_files(data.get("files"))

        return cls(
            input_content=data.get("input_content", ""), images=images, videos=videos, audios=audios, files=files
        )


class TeamRunEvent(str, Enum):
    """Events that can be sent by the run() functions"""

    run_started = "TeamRunStarted"
    run_content = "TeamRunContent"
    run_intermediate_content = "TeamRunIntermediateContent"
    run_content_completed = "TeamRunContentCompleted"
    run_completed = "TeamRunCompleted"
    run_error = "TeamRunError"
    run_cancelled = "TeamRunCancelled"

    pre_hook_started = "TeamPreHookStarted"
    pre_hook_completed = "TeamPreHookCompleted"

    post_hook_started = "TeamPostHookStarted"
    post_hook_completed = "TeamPostHookCompleted"

    tool_call_started = "TeamToolCallStarted"
    tool_call_completed = "TeamToolCallCompleted"
    tool_call_error = "TeamToolCallError"

    reasoning_started = "TeamReasoningStarted"
    reasoning_step = "TeamReasoningStep"
    reasoning_content_delta = "TeamReasoningContentDelta"
    reasoning_completed = "TeamReasoningCompleted"

    memory_update_started = "TeamMemoryUpdateStarted"
    memory_update_completed = "TeamMemoryUpdateCompleted"

    session_summary_started = "TeamSessionSummaryStarted"
    session_summary_completed = "TeamSessionSummaryCompleted"

    parser_model_response_started = "TeamParserModelResponseStarted"
    parser_model_response_completed = "TeamParserModelResponseCompleted"

    output_model_response_started = "TeamOutputModelResponseStarted"
    output_model_response_completed = "TeamOutputModelResponseCompleted"

    custom_event = "CustomEvent"


@dataclass
class BaseTeamRunEvent(BaseRunOutputEvent):
    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""
    team_id: str = ""
    team_name: str = ""
    run_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    session_id: Optional[str] = None

    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None  # This is the workflow's run_id
    step_id: Optional[str] = None
    step_name: Optional[str] = None
    step_index: Optional[int] = None

    # For backwards compatibility
    content: Optional[Any] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseTeamRunEvent":
        member_responses = data.pop("member_responses", None)
        event = super().from_dict(data)

        member_responses_final = []
        for response in member_responses or []:
            if "agent_id" in response:
                run_response_parsed = RunOutput.from_dict(response)
            else:
                run_response_parsed = TeamRunOutput.from_dict(response)  # type: ignore
            member_responses_final.append(run_response_parsed)

        if member_responses_final:
            event.member_responses = member_responses_final

        return event


@dataclass
class RunStartedEvent(BaseTeamRunEvent):
    """Event sent when the run starts"""

    event: str = TeamRunEvent.run_started.value
    model: str = ""
    model_provider: str = ""


@dataclass
class RunContentEvent(BaseTeamRunEvent):
    """Main event for each delta of the RunOutput"""

    event: str = TeamRunEvent.run_content.value
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
class IntermediateRunContentEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_intermediate_content.value
    content: Optional[Any] = None
    content_type: str = "str"


@dataclass
class RunContentCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_content_completed.value


@dataclass
class RunCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_completed.value
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
    member_responses: List[Union["TeamRunOutput", RunOutput]] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    metrics: Optional[Metrics] = None
    session_state: Optional[Dict[str, Any]] = None


@dataclass
class RunErrorEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_error.value
    content: Optional[str] = None

    # From exceptions
    error_type: Optional[str] = None
    error_id: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None


@dataclass
class RunCancelledEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_cancelled.value
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class PreHookStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.pre_hook_started.value
    pre_hook_name: Optional[str] = None
    run_input: Optional[TeamRunInput] = None


@dataclass
class PreHookCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.pre_hook_completed.value
    pre_hook_name: Optional[str] = None
    run_input: Optional[TeamRunInput] = None


@dataclass
class PostHookStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.post_hook_started.value
    post_hook_name: Optional[str] = None


@dataclass
class PostHookCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.post_hook_completed.value
    post_hook_name: Optional[str] = None


@dataclass
class MemoryUpdateStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.memory_update_started.value


@dataclass
class MemoryUpdateCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.memory_update_completed.value


@dataclass
class SessionSummaryStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.session_summary_started.value


@dataclass
class SessionSummaryCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.session_summary_completed.value
    session_summary: Optional[Any] = None


@dataclass
class ReasoningStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.reasoning_started.value


@dataclass
class ReasoningStepEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.reasoning_step.value
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: str = ""


@dataclass
class ReasoningContentDeltaEvent(BaseTeamRunEvent):
    """Event for streaming reasoning content chunks as they arrive."""

    event: str = TeamRunEvent.reasoning_content_delta.value
    reasoning_content: str = ""  # The delta/chunk of reasoning content


@dataclass
class ReasoningCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.reasoning_completed.value
    content: Optional[Any] = None
    content_type: str = "str"


@dataclass
class ToolCallStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.tool_call_started.value
    tool: Optional[ToolExecution] = None


@dataclass
class ToolCallCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.tool_call_completed.value
    tool: Optional[ToolExecution] = None
    content: Optional[Any] = None
    images: Optional[List[Image]] = None  # Images produced by the tool call
    videos: Optional[List[Video]] = None  # Videos produced by the tool call
    audio: Optional[List[Audio]] = None  # Audio produced by the tool call


@dataclass
class ToolCallErrorEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.tool_call_error.value
    tool: Optional[ToolExecution] = None
    error: Optional[str] = None


@dataclass
class ParserModelResponseStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.parser_model_response_started.value


@dataclass
class ParserModelResponseCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.parser_model_response_completed.value


@dataclass
class OutputModelResponseStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.output_model_response_started.value


@dataclass
class OutputModelResponseCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.output_model_response_completed.value


@dataclass
class CustomEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.custom_event.value

    def __init__(self, **kwargs):
        # Store arbitrary attributes directly on the instance
        for key, value in kwargs.items():
            setattr(self, key, value)


TeamRunOutputEvent = Union[
    RunStartedEvent,
    RunContentEvent,
    IntermediateRunContentEvent,
    RunContentCompletedEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunCancelledEvent,
    PreHookStartedEvent,
    PreHookCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    ReasoningContentDeltaEvent,
    ReasoningCompletedEvent,
    MemoryUpdateStartedEvent,
    MemoryUpdateCompletedEvent,
    SessionSummaryStartedEvent,
    SessionSummaryCompletedEvent,
    ToolCallStartedEvent,
    ToolCallCompletedEvent,
    ToolCallErrorEvent,
    ParserModelResponseStartedEvent,
    ParserModelResponseCompletedEvent,
    OutputModelResponseStartedEvent,
    OutputModelResponseCompletedEvent,
    CustomEvent,
]

# Map event string to dataclass for team events
TEAM_RUN_EVENT_TYPE_REGISTRY = {
    TeamRunEvent.run_started.value: RunStartedEvent,
    TeamRunEvent.run_content.value: RunContentEvent,
    TeamRunEvent.run_intermediate_content.value: IntermediateRunContentEvent,
    TeamRunEvent.run_content_completed.value: RunContentCompletedEvent,
    TeamRunEvent.run_completed.value: RunCompletedEvent,
    TeamRunEvent.run_error.value: RunErrorEvent,
    TeamRunEvent.run_cancelled.value: RunCancelledEvent,
    TeamRunEvent.pre_hook_started.value: PreHookStartedEvent,
    TeamRunEvent.pre_hook_completed.value: PreHookCompletedEvent,
    TeamRunEvent.post_hook_started.value: PostHookStartedEvent,
    TeamRunEvent.post_hook_completed.value: PostHookCompletedEvent,
    TeamRunEvent.reasoning_started.value: ReasoningStartedEvent,
    TeamRunEvent.reasoning_step.value: ReasoningStepEvent,
    TeamRunEvent.reasoning_content_delta.value: ReasoningContentDeltaEvent,
    TeamRunEvent.reasoning_completed.value: ReasoningCompletedEvent,
    TeamRunEvent.memory_update_started.value: MemoryUpdateStartedEvent,
    TeamRunEvent.memory_update_completed.value: MemoryUpdateCompletedEvent,
    TeamRunEvent.session_summary_started.value: SessionSummaryStartedEvent,
    TeamRunEvent.session_summary_completed.value: SessionSummaryCompletedEvent,
    TeamRunEvent.tool_call_started.value: ToolCallStartedEvent,
    TeamRunEvent.tool_call_completed.value: ToolCallCompletedEvent,
    TeamRunEvent.tool_call_error.value: ToolCallErrorEvent,
    TeamRunEvent.parser_model_response_started.value: ParserModelResponseStartedEvent,
    TeamRunEvent.parser_model_response_completed.value: ParserModelResponseCompletedEvent,
    TeamRunEvent.output_model_response_started.value: OutputModelResponseStartedEvent,
    TeamRunEvent.output_model_response_completed.value: OutputModelResponseCompletedEvent,
    TeamRunEvent.custom_event.value: CustomEvent,
}


def team_run_output_event_from_dict(data: dict) -> BaseTeamRunEvent:
    event_type = data.get("event", "")
    if event_type in {e.value for e in RunEvent}:
        return run_output_event_from_dict(data)  # type: ignore
    else:
        event_class = TEAM_RUN_EVENT_TYPE_REGISTRY.get(event_type)
    if not event_class:
        raise ValueError(f"Unknown team event type: {event_type}")
    return event_class.from_dict(data)  # type: ignore


@dataclass
class TeamRunOutput:
    """Response returned by Team.run() functions"""

    run_id: Optional[str] = None
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    session_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    user_id: Optional[str] = None

    # Input media and messages from user
    input: Optional[TeamRunInput] = None

    content: Optional[Any] = None
    content_type: str = "str"

    messages: Optional[List[Message]] = None
    metrics: Optional[Metrics] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None

    member_responses: List[Union["TeamRunOutput", RunOutput]] = field(default_factory=list)

    tools: Optional[List[ToolExecution]] = None

    images: Optional[List[Image]] = None  # Images from member runs
    videos: Optional[List[Video]] = None  # Videos from member runs
    audio: Optional[List[Audio]] = None  # Audio from member runs
    files: Optional[List[File]] = None  # Files from member runs

    response_audio: Optional[Audio] = None  # Model audio response

    reasoning_content: Optional[str] = None

    citations: Optional[Citations] = None
    model_provider_data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    session_state: Optional[Dict[str, Any]] = None

    references: Optional[List[MessageReferences]] = None
    additional_input: Optional[List[Message]] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None
    created_at: int = field(default_factory=lambda: int(time()))

    events: Optional[List[Union[RunOutputEvent, TeamRunOutputEvent]]] = None

    status: RunStatus = RunStatus.running

    # User control flow (HITL) requirements to continue a run when paused, in order of arrival
    requirements: Optional[list[RunRequirement]] = None

    # === FOREIGN KEY RELATIONSHIPS ===
    # These fields establish relationships to parent workflow/step structures
    # and should be treated as foreign keys for data integrity
    workflow_step_id: Optional[str] = None  # FK: Points to StepOutput.step_id

    @property
    def active_requirements(self) -> list[RunRequirement]:
        if not self.requirements:
            return []
        return [requirement for requirement in self.requirements if not requirement.is_resolved()]

    @property
    def is_paused(self):
        return self.status == RunStatus.paused

    @property
    def is_cancelled(self):
        return self.status == RunStatus.cancelled

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            k: v
            for k, v in asdict(self).items()
            if v is not None
            and k
            not in [
                "messages",
                "metrics",
                "status",
                "tools",
                "metadata",
                "images",
                "videos",
                "audio",
                "files",
                "response_audio",
                "citations",
                "events",
                "additional_input",
                "reasoning_steps",
                "reasoning_messages",
                "references",
            ]
        }
        if self.events is not None:
            _dict["events"] = [e.to_dict() for e in self.events]

        if self.metrics is not None:
            _dict["metrics"] = self.metrics.to_dict() if isinstance(self.metrics, Metrics) else self.metrics

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
            _dict["images"] = [img.to_dict() for img in self.images]

        if self.videos is not None:
            _dict["videos"] = [vid.to_dict() for vid in self.videos]

        if self.audio is not None:
            _dict["audio"] = [aud.to_dict() for aud in self.audio]

        if self.files is not None:
            _dict["files"] = [file.to_dict() for file in self.files]

        if self.response_audio is not None:
            _dict["response_audio"] = self.response_audio.to_dict()

        if self.member_responses:
            _dict["member_responses"] = [response.to_dict() for response in self.member_responses]

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
            log_error("Failed to convert response to json", exc_info=True)
            raise

        if indent is None:
            return json.dumps(_dict, separators=separators)
        else:
            return json.dumps(_dict, indent=indent, separators=separators)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamRunOutput":
        events = data.pop("events", None)
        final_events = []
        for event in events or []:
            if "agent_id" in event:
                # Use the factory from response.py for agent events
                from agno.run.agent import run_output_event_from_dict

                event = run_output_event_from_dict(event)
            else:
                event = team_run_output_event_from_dict(event)
            final_events.append(event)
        events = final_events

        messages = data.pop("messages", None)
        messages = [Message.from_dict(message) for message in messages] if messages else None

        member_responses = data.pop("member_responses", [])
        parsed_member_responses: List[Union["TeamRunOutput", RunOutput]] = []
        if member_responses:
            for response in member_responses:
                if "agent_id" in response:
                    parsed_member_responses.append(RunOutput.from_dict(response))
                else:
                    parsed_member_responses.append(cls.from_dict(response))

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

        images = reconstruct_images(data.pop("images", []))
        videos = reconstruct_videos(data.pop("videos", []))
        audio = reconstruct_audio_list(data.pop("audio", []))
        files = reconstruct_files(data.pop("files", []))

        tools = data.pop("tools", [])
        tools = [ToolExecution.from_dict(tool) for tool in tools] if tools else None

        response_audio = reconstruct_response_audio(data.pop("response_audio", None))

        input_data = data.pop("input", None)
        input_obj = None
        if input_data:
            input_obj = TeamRunInput.from_dict(input_data)

        metrics = data.pop("metrics", None)
        if metrics:
            metrics = Metrics(**metrics)

        citations = data.pop("citations", None)
        citations = Citations.model_validate(citations) if citations else None

        # Filter data to only include fields that are actually defined in the TeamRunOutput dataclass
        from dataclasses import fields

        supported_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in supported_fields}

        return cls(
            messages=messages,
            metrics=metrics,
            member_responses=parsed_member_responses,
            additional_input=additional_input,
            reasoning_steps=reasoning_steps,
            reasoning_messages=reasoning_messages,
            references=references,
            images=images,
            videos=videos,
            audio=audio,
            files=files,
            response_audio=response_audio,
            input=input_obj,
            citations=citations,
            tools=tools,
            events=events,
            **filtered_data,
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

    def add_member_run(self, run_response: Union["TeamRunOutput", RunOutput]) -> None:
        self.member_responses.append(run_response)
        if run_response.images is not None:
            if self.images is None:
                self.images = []
            self.images.extend(run_response.images)
        if run_response.videos is not None:
            if self.videos is None:
                self.videos = []
            self.videos.extend(run_response.videos)
        if run_response.audio is not None:
            if self.audio is None:
                self.audio = []
            self.audio.extend(run_response.audio)
        if run_response.files is not None:
            if self.files is None:
                self.files = []
            self.files.extend(run_response.files)
