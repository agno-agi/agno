from copy import copy
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.metrics import RunMetrics
from agno.models.message import Citations, Message, MessageReferences
from agno.reasoning.step import ReasoningStep
from agno.utils.log import log_error


@dataclass
class RunContext:
    run_id: str
    session_id: str
    user_id: Optional[str] = None

    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None

    dependencies: Optional[Dict[str, Any]] = None
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
    metadata: Optional[Dict[str, Any]] = None
    session_state: Optional[Dict[str, Any]] = None
    output_schema: Optional[Union[Type[BaseModel], Dict[str, Any]]] = None

    # Live reference to the current run's message list. Available in tool hooks
    # via run_context.messages. Hooks receive a shallow copy (via _safe_hook_call)
    # so accidental list mutations (.clear(), .append()) won't corrupt the run.
    # Individual Message objects are shared references — do not mutate them.
    messages: Optional[List[Message]] = None

    # Runtime-resolved callable factory results
    tools: Optional[List[Any]] = None
    knowledge: Optional[Any] = None
    members: Optional[List[Any]] = None

    # Per-run additive tools from the client (e.g., AG-UI frontend tools)
    # Merged AFTER agent.tools during tool resolution
    client_tools: Optional[List[Any]] = None


class _EventIndexCarrier:
    """Plain (non-dataclass) base carrying ``event_index``.

    The stream-assigned monotonic index, stamped by the event stream's
    add_event at publish time. Stamping the shared object means the
    component's own session save persists the REAL index with the stored
    event - which is what lets the DB replay fallback honor a client's
    last_event_index instead of renumbering from zero (indices are NOT
    gapless: retries and continuation legs leave gaps that positional
    renumbering destroys). None for events that never rode a stream
    (non-streaming runs, legacy rows).

    DELIBERATELY NOT a dataclass field. The only field form that lets a
    defaulted base attribute coexist with subclasses' required positional
    fields is field(kw_only=True) - which is Python 3.10+, and this package
    supports 3.9. Annotations on a NON-dataclass base are not fields (on
    any Python version, and to mypy's dataclass plugin alike), so there is
    no ordering constraint and no constructor parameter - while instance
    assignment still shadows the class default per-object and type checkers
    see an ordinary Optional[int] attribute. Because asdict()/fields() do
    not see it, to_dict and from_dict carry it EXPLICITLY - keep the three
    in sync.
    """

    event_index: Optional[int] = None


@dataclass
class BaseRunOutputEvent(_EventIndexCarrier):
    # Fields hand-serialized in to_dict below (when the subclass has them);
    # nulled on a shallow copy before asdict so their deep recursive
    # serialization never runs only to be discarded.
    _HAND_SERIALIZED_FIELDS = (
        "tools",
        "tool",
        "metadata",
        "image",
        "images",
        "videos",
        "audio",
        "response_audio",
        "citations",
        "member_responses",
        "reasoning_messages",
        "reasoning_steps",
        "references",
        "additional_input",
        "session_summary",
        "metrics",
        "run_input",
        "requirements",
        "tasks",
        "memories",
        "followups",
    )

    def to_dict(self) -> Dict[str, Any]:
        light_copy = copy(self)
        for field_name in self._HAND_SERIALIZED_FIELDS:
            if hasattr(light_copy, field_name):
                setattr(light_copy, field_name, None)
        light_content = getattr(light_copy, "content", None)
        if light_content and isinstance(light_content, BaseModel):
            # Re-serialized below via model_dump under the same truthiness
            # condition; asdict would deep-copy it here for nothing
            setattr(light_copy, "content", None)
        _dict = {k: v for k, v in asdict(light_copy).items() if v is not None}

        # Not a dataclass field (3.9-compatible class attribute - see its
        # declaration), so asdict() misses it: carry it explicitly
        if self.event_index is not None:
            _dict["event_index"] = self.event_index

        if hasattr(self, "metadata") and self.metadata is not None:
            _dict["metadata"] = self.metadata

        if hasattr(self, "additional_input") and self.additional_input is not None:
            _dict["additional_input"] = [m.to_dict() for m in self.additional_input]

        if hasattr(self, "reasoning_messages") and self.reasoning_messages is not None:
            _dict["reasoning_messages"] = [m.to_dict() for m in self.reasoning_messages]

        if hasattr(self, "reasoning_steps") and self.reasoning_steps is not None:
            _dict["reasoning_steps"] = [rs.model_dump() for rs in self.reasoning_steps]

        if hasattr(self, "references") and self.references is not None:
            _dict["references"] = [r.model_dump() for r in self.references]

        if hasattr(self, "followups") and self.followups is not None:
            _dict["followups"] = self.followups

        if hasattr(self, "member_responses") and self.member_responses:
            _dict["member_responses"] = [response.to_dict() for response in self.member_responses]

        if hasattr(self, "images") and self.images is not None:
            _dict["images"] = []
            for img in self.images:
                if isinstance(img, Image):
                    _dict["images"].append(img.to_dict())
                else:
                    _dict["images"].append(img)

        if hasattr(self, "videos") and self.videos is not None:
            _dict["videos"] = []
            for vid in self.videos:
                if isinstance(vid, Video):
                    _dict["videos"].append(vid.to_dict())
                else:
                    _dict["videos"].append(vid)

        if hasattr(self, "audio") and self.audio is not None:
            _dict["audio"] = []
            for aud in self.audio:
                if isinstance(aud, Audio):
                    _dict["audio"].append(aud.to_dict())
                else:
                    _dict["audio"].append(aud)

        if hasattr(self, "files") and self.files is not None:
            _dict["files"] = []
            for file in self.files:
                if isinstance(file, File):
                    _dict["files"].append(file.to_dict())
                else:
                    _dict["files"].append(file)

        if hasattr(self, "response_audio") and self.response_audio is not None:
            if isinstance(self.response_audio, Audio):
                _dict["response_audio"] = self.response_audio.to_dict()
            else:
                _dict["response_audio"] = self.response_audio

        if hasattr(self, "image") and self.image is not None:
            if isinstance(self.image, Image):
                _dict["image"] = self.image.to_dict()
            else:
                _dict["image"] = self.image

        if hasattr(self, "citations") and self.citations is not None:
            if isinstance(self.citations, Citations):
                _dict["citations"] = self.citations.model_dump(exclude_none=True)
            else:
                _dict["citations"] = self.citations

        if hasattr(self, "content") and self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        if hasattr(self, "tools") and self.tools is not None:
            from agno.models.response import ToolExecution

            _dict["tools"] = []
            for tool in self.tools:
                if isinstance(tool, ToolExecution):
                    _dict["tools"].append(tool.to_dict())
                else:
                    _dict["tools"].append(tool)

        if hasattr(self, "tool") and self.tool is not None:
            from agno.models.response import ToolExecution

            if isinstance(self.tool, ToolExecution):
                _dict["tool"] = self.tool.to_dict()
            else:
                _dict["tool"] = self.tool

        if hasattr(self, "metrics") and self.metrics is not None:
            _dict["metrics"] = self.metrics.to_dict()

        if hasattr(self, "session_summary") and self.session_summary is not None:
            _dict["session_summary"] = self.session_summary.to_dict()

        if hasattr(self, "run_input") and self.run_input is not None:
            _dict["run_input"] = self.run_input.to_dict()

        if hasattr(self, "requirements") and self.requirements is not None:
            _dict["requirements"] = [req.to_dict() if hasattr(req, "to_dict") else req for req in self.requirements]

        if hasattr(self, "memories") and self.memories is not None:
            _dict["memories"] = [mem.to_dict() if hasattr(mem, "to_dict") else mem for mem in self.memories]

        if hasattr(self, "tasks") and self.tasks is not None:
            _dict["tasks"] = [t.to_dict() for t in self.tasks]

        return _dict

    def to_json(self, separators=(", ", ": "), indent: Optional[int] = 2) -> str:
        import json

        from agno.utils.serialize import json_serializer

        try:
            _dict = self.to_dict()
        except Exception as e:
            log_error(f"Failed to convert response event to json: {str(e)}")
            raise

        if indent is None:
            return json.dumps(_dict, separators=separators, default=json_serializer, ensure_ascii=False)
        else:
            return json.dumps(_dict, indent=indent, separators=separators, default=json_serializer, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        # Not a dataclass field (see its declaration): pop before
        # construction, restore by assignment after
        event_index = data.pop("event_index", None)

        tool = data.pop("tool", None)
        if tool:
            from agno.models.response import ToolExecution

            data["tool"] = ToolExecution.from_dict(tool)

        tools = data.pop("tools", None)
        if tools:
            from agno.models.response import ToolExecution

            data["tools"] = [ToolExecution.from_dict(t) for t in tools]

        images = data.pop("images", None)
        if images:
            data["images"] = [Image.model_validate(image) for image in images]

        videos = data.pop("videos", None)
        if videos:
            data["videos"] = [Video.model_validate(video) for video in videos]

        audio = data.pop("audio", None)
        if audio:
            data["audio"] = [Audio.model_validate(audio) for audio in audio]

        files = data.pop("files", None)
        if files:
            from agno.utils.media import reconstruct_files

            data["files"] = reconstruct_files(files)

        response_audio = data.pop("response_audio", None)
        if response_audio:
            data["response_audio"] = Audio.model_validate(response_audio)

        image = data.pop("image", None)
        if image:
            data["image"] = Image.model_validate(image)

        additional_input = data.pop("additional_input", None)
        if additional_input is not None:
            data["additional_input"] = [Message.model_validate(message) for message in additional_input]

        reasoning_steps = data.pop("reasoning_steps", None)
        if reasoning_steps is not None:
            data["reasoning_steps"] = [ReasoningStep.model_validate(step) for step in reasoning_steps]

        reasoning_messages = data.pop("reasoning_messages", None)
        if reasoning_messages is not None:
            data["reasoning_messages"] = [Message.model_validate(message) for message in reasoning_messages]

        references = data.pop("references", None)
        if references is not None:
            data["references"] = [MessageReferences.model_validate(reference) for reference in references]

        metrics = data.pop("metrics", None)
        if metrics:
            data["metrics"] = RunMetrics.from_dict(metrics)

        session_summary = data.pop("session_summary", None)
        if session_summary:
            from agno.session.summary import SessionSummary

            data["session_summary"] = SessionSummary.from_dict(session_summary)

        run_input = data.pop("run_input", None)
        if run_input:
            from agno.run.team import BaseTeamRunEvent

            if issubclass(cls, BaseTeamRunEvent):
                from agno.run.team import TeamRunInput

                data["run_input"] = TeamRunInput.from_dict(run_input)
            else:
                from agno.run.agent import RunInput

                data["run_input"] = RunInput.from_dict(run_input)

        # Handle requirements
        requirements_data = data.pop("requirements", None)
        if requirements_data is not None:
            from agno.run.requirement import RunRequirement

            requirements_list: List[RunRequirement] = []
            for item in requirements_data:
                if isinstance(item, RunRequirement):
                    requirements_list.append(item)
                elif isinstance(item, dict):
                    requirements_list.append(RunRequirement.from_dict(item))
            data["requirements"] = requirements_list if requirements_list else None

        # Handle tasks (TaskData objects in TaskStateUpdatedEvent)
        tasks_data = data.pop("tasks", None)
        if tasks_data is not None:
            from agno.run.team import TaskData

            data["tasks"] = [TaskData.from_dict(t) if isinstance(t, dict) else t for t in tasks_data]

        # Filter data to only include fields that are actually defined in the target class
        # CustomEvent accepts arbitrary fields, so skip filtering for it
        if cls.__name__ == "CustomEvent":
            event = cls(**data)
        else:
            from dataclasses import fields

            supported_fields = {f.name for f in fields(cls)}
            filtered_data = {k: v for k, v in data.items() if k in supported_fields}
            event = cls(**filtered_data)
        if event_index is not None:
            event.event_index = event_index
        return event

    @property
    def is_paused(self):
        return False

    @property
    def is_cancelled(self):
        return False


class RunStatus(str, Enum):
    """State of the main run response"""

    pending = "PENDING"
    running = "RUNNING"
    completed = "COMPLETED"
    paused = "PAUSED"
    cancelled = "CANCELLED"
    error = "ERROR"
    # Marker for a run whose response was regenerated via /continue?regenerate=true
    # (replace_original defaults to true). The new regenerated run sits alongside it
    # as a sibling (via fork mechanics); the old run keeps this status so
    # history-builders can skip it when rebuilding context. Pass replace_original=false
    # to keep the original COMPLETED and visible instead.
    regenerated = "REGENERATED"


# Canonical set of run statuses excluded when rebuilding message history/context.
# Single source of truth: session.get_messages (agent + team) and the DB-level
# bounded-history read (agno.db.utils.HISTORY_SKIP_STATUSES) both derive from this,
# so the full-load and "most recent N" read paths can never return different
# history windows for the same session.
HISTORY_SKIP_STATUSES: list["RunStatus"] = [
    RunStatus.paused,
    RunStatus.cancelled,
    RunStatus.error,
    RunStatus.regenerated,
]
