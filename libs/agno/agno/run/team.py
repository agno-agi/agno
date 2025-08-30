from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import AudioArtifact, AudioResponse, ImageArtifact, VideoArtifact
from agno.models.message import Citations, Message
from agno.models.metrics import Metrics
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunEvent, RunOutput, RunOutputEvent, run_output_event_from_dict
from agno.run.base import BaseRunOutputEvent, MessageReferences, RunStatus


class TeamRunEvent(str, Enum):
    """Events that can be sent by the run() functions"""

    run_started = "TeamRunStarted"
    run_content = "TeamRunContent"
    run_intermediate_content = "TeamRunIntermediateContent"
    run_completed = "TeamRunCompleted"
    run_error = "TeamRunError"
    run_cancelled = "TeamRunCancelled"

    tool_call_started = "TeamToolCallStarted"
    tool_call_completed = "TeamToolCallCompleted"

    reasoning_started = "TeamReasoningStarted"
    reasoning_step = "TeamReasoningStep"
    reasoning_completed = "TeamReasoningCompleted"

    memory_update_started = "TeamMemoryUpdateStarted"
    memory_update_completed = "TeamMemoryUpdateCompleted"

    parser_model_response_started = "TeamParserModelResponseStarted"
    parser_model_response_completed = "TeamParserModelResponseCompleted"

    output_model_response_started = "TeamOutputModelResponseStarted"
    output_model_response_completed = "TeamOutputModelResponseCompleted"


@dataclass
class BaseTeamRunEvent(BaseRunOutputEvent):
    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""
    team_id: str = ""
    team_name: str = ""
    run_id: Optional[str] = None
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
    citations: Optional[Citations] = None
    response_audio: Optional[AudioResponse] = None  # Model audio response
    image: Optional[ImageArtifact] = None  # Image attached to the response
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
class RunCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_completed.value
    content: Optional[Any] = None
    content_type: str = "str"
    reasoning_content: Optional[str] = None
    citations: Optional[Citations] = None
    images: Optional[List[ImageArtifact]] = None  # Images attached to the response
    videos: Optional[List[VideoArtifact]] = None  # Videos attached to the response
    audio: Optional[List[AudioArtifact]] = None  # Audio attached to the response
    response_audio: Optional[AudioResponse] = None  # Model audio response
    references: Optional[List[MessageReferences]] = None
    additional_input: Optional[List[Message]] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None
    member_responses: List[Union["TeamRunOutput", RunOutput]] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    metrics: Optional[Metrics] = None


@dataclass
class RunErrorEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_error.value
    content: Optional[str] = None


@dataclass
class RunCancelledEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.run_cancelled.value
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class MemoryUpdateStartedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.memory_update_started.value


@dataclass
class MemoryUpdateCompletedEvent(BaseTeamRunEvent):
    event: str = TeamRunEvent.memory_update_completed.value


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
    images: Optional[List[ImageArtifact]] = None  # Images produced by the tool call
    videos: Optional[List[VideoArtifact]] = None  # Videos produced by the tool call
    audio: Optional[List[AudioArtifact]] = None  # Audio produced by the tool call


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


TeamRunOutputEvent = Union[
    RunStartedEvent,
    RunContentEvent,
    IntermediateRunContentEvent,
    RunCompletedEvent,
    RunErrorEvent,
    RunCancelledEvent,
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
]

# Map event string to dataclass for team events
TEAM_RUN_EVENT_TYPE_REGISTRY = {
    TeamRunEvent.run_started.value: RunStartedEvent,
    TeamRunEvent.run_content.value: RunContentEvent,
    TeamRunEvent.run_intermediate_content.value: IntermediateRunContentEvent,
    TeamRunEvent.run_completed.value: RunCompletedEvent,
    TeamRunEvent.run_error.value: RunErrorEvent,
    TeamRunEvent.run_cancelled.value: RunCancelledEvent,
    TeamRunEvent.reasoning_started.value: ReasoningStartedEvent,
    TeamRunEvent.reasoning_step.value: ReasoningStepEvent,
    TeamRunEvent.reasoning_completed.value: ReasoningCompletedEvent,
    TeamRunEvent.memory_update_started.value: MemoryUpdateStartedEvent,
    TeamRunEvent.memory_update_completed.value: MemoryUpdateCompletedEvent,
    TeamRunEvent.tool_call_started.value: ToolCallStartedEvent,
    TeamRunEvent.tool_call_completed.value: ToolCallCompletedEvent,
    TeamRunEvent.parser_model_response_started.value: ParserModelResponseStartedEvent,
    TeamRunEvent.parser_model_response_completed.value: ParserModelResponseCompletedEvent,
    TeamRunEvent.output_model_response_started.value: OutputModelResponseStartedEvent,
    TeamRunEvent.output_model_response_completed.value: OutputModelResponseCompletedEvent,
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

    content: Optional[Any] = None
    content_type: str = "str"
    messages: Optional[List[Message]] = None
    metrics: Optional[Metrics] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None

    member_responses: List[Union["TeamRunOutput", RunOutput]] = field(default_factory=list)

    run_id: Optional[str] = None
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    session_id: Optional[str] = None
    parent_run_id: Optional[str] = None

    tools: Optional[List[ToolExecution]] = None

    images: Optional[List[ImageArtifact]] = None  # Images from member runs
    videos: Optional[List[VideoArtifact]] = None  # Videos from member runs
    audio: Optional[List[AudioArtifact]] = None  # Audio from member runs

    response_audio: Optional[AudioResponse] = None  # Model audio response

    reasoning_content: Optional[str] = None

    citations: Optional[Citations] = None

    metadata: Optional[Dict[str, Any]] = None

    references: Optional[List[MessageReferences]] = None
    additional_input: Optional[List[Message]] = None
    reasoning_steps: Optional[List[ReasoningStep]] = None
    reasoning_messages: Optional[List[Message]] = None
    created_at: int = field(default_factory=lambda: int(time()))

    events: Optional[List[Union[RunOutputEvent, TeamRunOutputEvent]]] = None

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

    def to_dict(self) -> Dict[str, Any]:
        _dict = {
            k: v
            for k, v in asdict(self).items()
            if v is not None
            and k
            not in [
                "messages",
                "status",
                "tools",
                "metadata",
                "images",
                "videos",
                "audio",
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

        return _dict

    def to_json(self) -> str:
        import json

        _dict = self.to_dict()

        return json.dumps(_dict, indent=2)

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
        messages = [Message.model_validate(message) for message in messages] if messages else None

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
            additional_input = [Message.model_validate(message) for message in additional_input]

        reasoning_steps = data.pop("reasoning_steps", None)
        if reasoning_steps is not None:
            reasoning_steps = [ReasoningStep.model_validate(step) for step in reasoning_steps]

        reasoning_messages = data.pop("reasoning_messages", None)
        if reasoning_messages is not None:
            reasoning_messages = [Message.model_validate(message) for message in reasoning_messages]

        references = data.pop("references", None)
        if references is not None:
            references = [MessageReferences.model_validate(reference) for reference in references]

        images = data.pop("images", [])
        images = [ImageArtifact.model_validate(image) for image in images] if images else None

        videos = data.pop("videos", [])
        videos = [VideoArtifact.model_validate(video) for video in videos] if videos else None

        audio = data.pop("audio", [])
        audio = [AudioArtifact.model_validate(audio) for audio in audio] if audio else None

        tools = data.pop("tools", [])
        tools = [ToolExecution.from_dict(tool) for tool in tools] if tools else None

        response_audio = data.pop("response_audio", None)
        response_audio = AudioResponse.model_validate(response_audio) if response_audio else None

        metrics = data.pop("metrics", None)
        if metrics:
            metrics = Metrics(**metrics)

        citations = data.pop("citations", None)
        citations = Citations.model_validate(citations) if citations else None

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
            response_audio=response_audio,
            citations=citations,
            tools=tools,
            events=events,
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
