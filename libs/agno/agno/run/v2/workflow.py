from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import AudioArtifact, AudioResponse, ImageArtifact, VideoArtifact
from agno.run.base import RunStatus
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.workflow.v2.types import StepOutput, WorkflowMetrics


class WorkflowRunEvent(str, Enum):
    """Events that can be sent by workflow execution"""

    workflow_started = "WorkflowStarted"
    workflow_completed = "WorkflowCompleted"
    workflow_cancelled = "WorkflowCancelled"
    workflow_error = "WorkflowError"

    step_started = "StepStarted"
    step_completed = "StepCompleted"
    step_error = "StepError"

    loop_execution_started = "LoopExecutionStarted"
    loop_iteration_started = "LoopIterationStarted"
    loop_iteration_completed = "LoopIterationCompleted"
    loop_execution_completed = "LoopExecutionCompleted"

    parallel_execution_started = "ParallelExecutionStarted"
    parallel_execution_completed = "ParallelExecutionCompleted"

    condition_execution_started = "ConditionExecutionStarted"
    condition_execution_completed = "ConditionExecutionCompleted"

    router_execution_started = "RouterExecutionStarted"
    router_execution_completed = "RouterExecutionCompleted"

    steps_execution_started = "StepsExecutionStarted"
    steps_execution_completed = "StepsExecutionCompleted"

    step_output = "StepOutput"


@dataclass
class BaseWorkflowRunResponseEvent:
    """Base class for all workflow run response events"""

    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {k: v for k, v in asdict(self).items() if v is not None}

        if hasattr(self, "content") and self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        # Handle StepOutput fields that contain Message objects
        if hasattr(self, "step_responses") and self.step_responses is not None:
            _dict["step_responses"] = [step.to_dict() for step in self.step_responses]

        if hasattr(self, "step_response") and self.step_response is not None:
            _dict["step_response"] = self.step_response.to_dict()

        if hasattr(self, "iteration_results") and self.iteration_results is not None:
            _dict["iteration_results"] = [step.to_dict() for step in self.iteration_results]

        if hasattr(self, "all_results") and self.all_results is not None:
            _dict["all_results"] = [[step.to_dict() for step in iteration] for iteration in self.all_results]

        if hasattr(self, "step_results") and self.step_results is not None:
            _dict["step_results"] = [step.to_dict() for step in self.step_results]

        return _dict

    def to_json(self) -> str:
        import json

        try:
            _dict = self.to_dict()
        except Exception:
            log_error("Failed to convert response to json", exc_info=True)
            raise

        return json.dumps(_dict, indent=2)

    @property
    def is_cancelled(self):
        return False

    @property
    def is_error(self):
        return False

    @property
    def status(self):
        status = "Completed"
        if self.is_error:
            status = "Error"
        if self.is_cancelled:
            status = "Cancelled"

        return status


@dataclass
class WorkflowStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution starts"""

    event: str = WorkflowRunEvent.workflow_started.value


@dataclass
class WorkflowCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution completes"""

    event: str = WorkflowRunEvent.workflow_completed.value
    content: Optional[Any] = None
    content_type: str = "str"

    # Store actual step execution results as StepOutput objects
    step_responses: List["StepOutput"] = field(default_factory=list)  # noqa: F821
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowErrorEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution fails"""

    event: str = WorkflowRunEvent.workflow_error.value
    error: Optional[str] = None


@dataclass
class WorkflowCancelledEvent(BaseWorkflowRunResponseEvent):
    """Event sent when workflow execution is cancelled"""

    event: str = WorkflowRunEvent.workflow_cancelled.value
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class StepStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when step execution starts"""

    event: str = WorkflowRunEvent.step_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None


@dataclass
class StepCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when step execution completes"""

    event: str = WorkflowRunEvent.step_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None

    content: Optional[Any] = None
    content_type: str = "str"

    # Media content fields
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
    response_audio: Optional[AudioResponse] = None

    # Store actual step execution results as StepOutput objects
    step_response: Optional["StepOutput"] = None  # noqa: F821


@dataclass
class StepErrorEvent(BaseWorkflowRunResponseEvent):
    """Event sent when step execution fails"""

    event: str = WorkflowRunEvent.step_error.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    error: Optional[str] = None


@dataclass
class LoopExecutionStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when loop execution starts"""

    event: str = WorkflowRunEvent.loop_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    max_iterations: Optional[int] = None


@dataclass
class LoopIterationStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when loop iteration starts"""

    event: str = WorkflowRunEvent.loop_iteration_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    iteration: int = 0
    max_iterations: Optional[int] = None


@dataclass
class LoopIterationCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when loop iteration completes"""

    event: str = WorkflowRunEvent.loop_iteration_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    iteration: int = 0
    max_iterations: Optional[int] = None
    iteration_results: List["StepOutput"] = field(default_factory=list)  # noqa: F821
    should_continue: bool = True


@dataclass
class LoopExecutionCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when loop execution completes"""

    event: str = WorkflowRunEvent.loop_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    total_iterations: int = 0
    max_iterations: Optional[int] = None
    all_results: List[List["StepOutput"]] = field(default_factory=list)  # noqa: F821


@dataclass
class ParallelExecutionStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when parallel step execution starts"""

    event: str = WorkflowRunEvent.parallel_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    parallel_step_count: Optional[int] = None


@dataclass
class ParallelExecutionCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when parallel step execution completes"""

    event: str = WorkflowRunEvent.parallel_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    parallel_step_count: Optional[int] = None

    # Results from all parallel steps
    step_results: List["StepOutput"] = field(default_factory=list)  # noqa: F821


@dataclass
class ConditionExecutionStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when condition step execution starts"""

    event: str = WorkflowRunEvent.condition_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    condition_result: Optional[bool] = None


@dataclass
class ConditionExecutionCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when condition step execution completes"""

    event: str = WorkflowRunEvent.condition_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    condition_result: Optional[bool] = None
    executed_steps: Optional[int] = None

    # Results from executed steps
    step_results: List["StepOutput"] = field(default_factory=list)  # noqa: F821


@dataclass
class RouterExecutionStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when router step execution starts"""

    event: str = WorkflowRunEvent.router_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    # Names of steps selected by router
    selected_steps: List[str] = field(default_factory=list)


@dataclass
class RouterExecutionCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when router step execution completes"""

    event: str = WorkflowRunEvent.router_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    # Names of steps that were selected
    selected_steps: List[str] = field(default_factory=list)
    executed_steps: Optional[int] = None

    # Results from executed steps
    step_results: List["StepOutput"] = field(default_factory=list)  # noqa: F821


@dataclass
class StepsExecutionStartedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when steps execution starts"""

    event: str = WorkflowRunEvent.steps_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    steps_count: Optional[int] = None


@dataclass
class StepsExecutionCompletedEvent(BaseWorkflowRunResponseEvent):
    """Event sent when steps execution completes"""

    event: str = WorkflowRunEvent.steps_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    steps_count: Optional[int] = None
    executed_steps: Optional[int] = None

    # Results from executed steps
    step_results: List["StepOutput"] = field(default_factory=list)  # noqa: F821


@dataclass
class StepOutputEvent(BaseWorkflowRunResponseEvent):
    """Event sent when a step produces output - replaces direct StepOutput yielding"""

    event: str = "StepOutput"
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None

    # Store actual step execution result as StepOutput object
    step_output: Optional["StepOutput"] = None  # noqa: F821

    # Properties for backward compatibility
    @property
    def content(self) -> Optional[Union[str, Dict[str, Any], List[Any], BaseModel, Any]]:
        return self.step_output.content if self.step_output else None

    @property
    def images(self) -> Optional[List[ImageArtifact]]:
        return self.step_output.images if self.step_output else None

    @property
    def videos(self) -> Optional[List[VideoArtifact]]:
        return self.step_output.videos if self.step_output else None

    @property
    def audio(self) -> Optional[List[AudioArtifact]]:
        return self.step_output.audio if self.step_output else None

    @property
    def success(self) -> bool:
        return self.step_output.success if self.step_output else True

    @property
    def error(self) -> Optional[str]:
        return self.step_output.error if self.step_output else None

    @property
    def stop(self) -> bool:
        return self.step_output.stop if self.step_output else False


# Union type for all workflow run response events
WorkflowRunResponseEvent = Union[
    WorkflowStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    StepStartedEvent,
    StepCompletedEvent,
    StepErrorEvent,
    LoopExecutionStartedEvent,
    LoopIterationStartedEvent,
    LoopIterationCompletedEvent,
    LoopExecutionCompletedEvent,
    ParallelExecutionStartedEvent,
    ParallelExecutionCompletedEvent,
    ConditionExecutionStartedEvent,
    ConditionExecutionCompletedEvent,
    RouterExecutionStartedEvent,
    RouterExecutionCompletedEvent,
    StepsExecutionStartedEvent,
    StepsExecutionCompletedEvent,
    StepOutputEvent,
]


@dataclass
class WorkflowRunResponse:
    """Response returned by Workflow.run() functions - kept for backwards compatibility"""

    content: Optional[Union[str, Dict[str, Any], List[Any], BaseModel, Any]] = None
    content_type: str = "str"
    metrics: Optional[Dict[str, Any]] = None

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None

    run_id: Optional[str] = None
    session_id: Optional[str] = None

    # Media content fields
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None
    response_audio: Optional[AudioResponse] = None

    # Store actual step execution results as StepOutput objects
    step_responses: List[Union["StepOutput", List["StepOutput"]]] = field(default_factory=list)  # noqa: F821

    # Store events from workflow execution
    events: Optional[List[WorkflowRunResponseEvent]] = None

    # Workflow metrics aggregated from all steps
    workflow_metrics: Optional["WorkflowMetrics"] = None

    extra_data: Optional[Dict[str, Any]] = None
    created_at: int = field(default_factory=lambda: int(time()))

    status: RunStatus = RunStatus.pending

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
                "extra_data",
                "images",
                "videos",
                "audio",
                "response_audio",
                "step_responses",
                "events",
                "workflow_metrics",
            ]
        }

        if self.status is not None:
            _dict["status"] = self.status.value if isinstance(self.status, RunStatus) else self.status

        if self.extra_data is not None:
            _dict["extra_data"] = self.extra_data

        if self.images is not None:
            _dict["images"] = [img.to_dict() for img in self.images]

        if self.videos is not None:
            _dict["videos"] = [vid.to_dict() for vid in self.videos]

        if self.audio is not None:
            _dict["audio"] = [aud.to_dict() for aud in self.audio]

        if self.response_audio is not None:
            _dict["response_audio"] = self.response_audio.to_dict()

        if self.step_responses:
            flattened_responses = []
            for step_response in self.step_responses:
                if isinstance(step_response, list):
                    # Handle List[StepOutput] from workflow components like Steps
                    flattened_responses.extend([s.to_dict() for s in step_response])
                else:
                    # Handle single StepOutput
                    flattened_responses.append(step_response.to_dict())
            _dict["step_responses"] = flattened_responses

        if self.workflow_metrics is not None:
            _dict["workflow_metrics"] = self.workflow_metrics.to_dict()

        if self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        if self.events is not None:
            _dict["events"] = [e.to_dict() for e in self.events]

        return _dict

    def to_json(self) -> str:
        import json

        _dict = self.to_dict()
        return json.dumps(_dict, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowRunResponse":
        # Import here to avoid circular import
        from agno.workflow.v2.step import StepOutput

        workflow_metrics_dict = data.pop("workflow_metrics", {})
        workflow_metrics = None
        if workflow_metrics_dict:
            from agno.workflow.v2.workflow import WorkflowMetrics

            workflow_metrics = WorkflowMetrics.from_dict(workflow_metrics_dict)

        step_responses = data.pop("step_responses", [])
        parsed_step_responses: List[Union["StepOutput", List["StepOutput"]]] = []
        if step_responses:
            for step_output_dict in step_responses:
                # Reconstruct StepOutput from dict
                parsed_step_responses.append(StepOutput.from_dict(step_output_dict))

        extra_data = data.pop("extra_data", None)

        images = data.pop("images", [])
        images = [ImageArtifact.model_validate(image) for image in images] if images else None

        videos = data.pop("videos", [])
        videos = [VideoArtifact.model_validate(video) for video in videos] if videos else None

        audio = data.pop("audio", [])
        audio = [AudioArtifact.model_validate(audio) for audio in audio] if audio else None

        response_audio = data.pop("response_audio", None)
        response_audio = AudioResponse.model_validate(response_audio) if response_audio else None

        events = data.pop("events", [])

        return cls(
            step_responses=parsed_step_responses,
            extra_data=extra_data,
            images=images,
            videos=videos,
            audio=audio,
            response_audio=response_audio,
            events=events,
            workflow_metrics=workflow_metrics,
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

    def has_completed(self) -> bool:
        """Check if the workflow run is completed (either successfully or with error)"""
        return self.status in [RunStatus.completed, RunStatus.error]
