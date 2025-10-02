from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.media import Audio, Image, Video
from agno.run.agent import RunOutput
from agno.run.base import BaseRunOutputEvent, RunStatus
from agno.run.team import TeamRunOutput

if TYPE_CHECKING:
    from agno.workflow.types import StepOutput, WorkflowMetrics
else:
    StepOutput = Any
    WorkflowMetrics = Any


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

    custom_event = "CustomEvent"


@dataclass
class BaseWorkflowRunOutputEvent(BaseRunOutputEvent):
    """Base class for all workflow run response events"""

    created_at: int = field(default_factory=lambda: int(time()))
    event: str = ""

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    parent_step_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = {k: v for k, v in asdict(self).items() if v is not None}

        if hasattr(self, "content") and self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        # Handle StepOutput fields that contain Message objects
        if hasattr(self, "step_results") and self.step_results is not None:
            _dict["step_results"] = [step.to_dict() if hasattr(step, "to_dict") else step for step in self.step_results]

        if hasattr(self, "step_response") and self.step_response is not None:
            _dict["step_response"] = (
                self.step_response.to_dict() if hasattr(self.step_response, "to_dict") else self.step_response
            )

        if hasattr(self, "iteration_results") and self.iteration_results is not None:
            _dict["iteration_results"] = [
                step.to_dict() if hasattr(step, "to_dict") else step for step in self.iteration_results
            ]

        if hasattr(self, "all_results") and self.all_results is not None:
            _dict["all_results"] = [
                [step.to_dict() if hasattr(step, "to_dict") else step for step in iteration]
                for iteration in self.all_results
            ]

        return _dict

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
class WorkflowStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when workflow execution starts"""

    event: str = WorkflowRunEvent.workflow_started.value


@dataclass
class WorkflowCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when workflow execution completes"""

    event: str = WorkflowRunEvent.workflow_completed.value
    content: Optional[Any] = None
    content_type: str = "str"

    # Store actual step execution results as StepOutput objects
    step_results: List[StepOutput] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowErrorEvent(BaseWorkflowRunOutputEvent):
    """Event sent when workflow execution fails"""

    event: str = WorkflowRunEvent.workflow_error.value
    error: Optional[str] = None

    # From exceptions
    error_type: Optional[str] = None
    error_id: Optional[str] = None
    additional_data: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowCancelledEvent(BaseWorkflowRunOutputEvent):
    """Event sent when workflow execution is cancelled"""

    event: str = WorkflowRunEvent.workflow_cancelled.value
    reason: Optional[str] = None

    @property
    def is_cancelled(self):
        return True


@dataclass
class StepStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when step execution starts"""

    event: str = WorkflowRunEvent.step_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None


@dataclass
class StepCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when step execution completes"""

    event: str = WorkflowRunEvent.step_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None

    content: Optional[Any] = None
    content_type: str = "str"

    # Media content fields
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audio: Optional[List[Audio]] = None
    response_audio: Optional[Audio] = None

    # Store actual step execution results as StepOutput objects
    step_response: Optional[StepOutput] = None


@dataclass
class StepErrorEvent(BaseWorkflowRunOutputEvent):
    """Event sent when step execution fails"""

    event: str = WorkflowRunEvent.step_error.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    error: Optional[str] = None


@dataclass
class LoopExecutionStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when loop execution starts"""

    event: str = WorkflowRunEvent.loop_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    max_iterations: Optional[int] = None


@dataclass
class LoopIterationStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when loop iteration starts"""

    event: str = WorkflowRunEvent.loop_iteration_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    iteration: int = 0
    max_iterations: Optional[int] = None


@dataclass
class LoopIterationCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when loop iteration completes"""

    event: str = WorkflowRunEvent.loop_iteration_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    iteration: int = 0
    max_iterations: Optional[int] = None
    iteration_results: List[StepOutput] = field(default_factory=list)
    should_continue: bool = True


@dataclass
class LoopExecutionCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when loop execution completes"""

    event: str = WorkflowRunEvent.loop_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    total_iterations: int = 0
    max_iterations: Optional[int] = None
    all_results: List[List[StepOutput]] = field(default_factory=list)


@dataclass
class ParallelExecutionStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when parallel step execution starts"""

    event: str = WorkflowRunEvent.parallel_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    parallel_step_count: Optional[int] = None


@dataclass
class ParallelExecutionCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when parallel step execution completes"""

    event: str = WorkflowRunEvent.parallel_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    parallel_step_count: Optional[int] = None

    # Results from all parallel steps
    step_results: List[StepOutput] = field(default_factory=list)


@dataclass
class ConditionExecutionStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when condition step execution starts"""

    event: str = WorkflowRunEvent.condition_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    condition_result: Optional[bool] = None


@dataclass
class ConditionExecutionCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when condition step execution completes"""

    event: str = WorkflowRunEvent.condition_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    condition_result: Optional[bool] = None
    executed_steps: Optional[int] = None

    # Results from executed steps
    step_results: List[StepOutput] = field(default_factory=list)


@dataclass
class RouterExecutionStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when router step execution starts"""

    event: str = WorkflowRunEvent.router_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    # Names of steps selected by router
    selected_steps: List[str] = field(default_factory=list)


@dataclass
class RouterExecutionCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when router step execution completes"""

    event: str = WorkflowRunEvent.router_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    # Names of steps that were selected
    selected_steps: List[str] = field(default_factory=list)
    executed_steps: Optional[int] = None

    # Results from executed steps
    step_results: List[StepOutput] = field(default_factory=list)


@dataclass
class StepsExecutionStartedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when steps execution starts"""

    event: str = WorkflowRunEvent.steps_execution_started.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    steps_count: Optional[int] = None


@dataclass
class StepsExecutionCompletedEvent(BaseWorkflowRunOutputEvent):
    """Event sent when steps execution completes"""

    event: str = WorkflowRunEvent.steps_execution_completed.value
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None
    steps_count: Optional[int] = None
    executed_steps: Optional[int] = None

    # Results from executed steps
    step_results: List[StepOutput] = field(default_factory=list)


@dataclass
class StepOutputEvent(BaseWorkflowRunOutputEvent):
    """Event sent when a step produces output - replaces direct StepOutput yielding"""

    event: str = "StepOutput"
    step_name: Optional[str] = None
    step_index: Optional[Union[int, tuple]] = None

    # Store actual step execution result as StepOutput object
    step_output: Optional[StepOutput] = None

    # Properties for backward compatibility
    @property
    def content(self) -> Optional[Union[str, Dict[str, Any], List[Any], BaseModel, Any]]:
        return self.step_output.content if self.step_output else None

    @property
    def images(self) -> Optional[List[Image]]:
        return self.step_output.images if self.step_output else None

    @property
    def videos(self) -> Optional[List[Video]]:
        return self.step_output.videos if self.step_output else None

    @property
    def audio(self) -> Optional[List[Audio]]:
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


@dataclass
class CustomEvent(BaseWorkflowRunOutputEvent):
    """Event sent when a custom event is produced"""

    event: str = WorkflowRunEvent.custom_event.value


# Union type for all workflow run response events
WorkflowRunOutputEvent = Union[
    WorkflowStartedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowCancelledEvent,
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
    CustomEvent,
]

# Map event string to dataclass for workflow events
WORKFLOW_RUN_EVENT_TYPE_REGISTRY = {
    WorkflowRunEvent.workflow_started.value: WorkflowStartedEvent,
    WorkflowRunEvent.workflow_completed.value: WorkflowCompletedEvent,
    WorkflowRunEvent.workflow_cancelled.value: WorkflowCancelledEvent,
    WorkflowRunEvent.workflow_error.value: WorkflowErrorEvent,
    WorkflowRunEvent.step_started.value: StepStartedEvent,
    WorkflowRunEvent.step_completed.value: StepCompletedEvent,
    WorkflowRunEvent.step_error.value: StepErrorEvent,
    WorkflowRunEvent.loop_execution_started.value: LoopExecutionStartedEvent,
    WorkflowRunEvent.loop_iteration_started.value: LoopIterationStartedEvent,
    WorkflowRunEvent.loop_iteration_completed.value: LoopIterationCompletedEvent,
    WorkflowRunEvent.loop_execution_completed.value: LoopExecutionCompletedEvent,
    WorkflowRunEvent.parallel_execution_started.value: ParallelExecutionStartedEvent,
    WorkflowRunEvent.parallel_execution_completed.value: ParallelExecutionCompletedEvent,
    WorkflowRunEvent.condition_execution_started.value: ConditionExecutionStartedEvent,
    WorkflowRunEvent.condition_execution_completed.value: ConditionExecutionCompletedEvent,
    WorkflowRunEvent.router_execution_started.value: RouterExecutionStartedEvent,
    WorkflowRunEvent.router_execution_completed.value: RouterExecutionCompletedEvent,
    WorkflowRunEvent.steps_execution_started.value: StepsExecutionStartedEvent,
    WorkflowRunEvent.steps_execution_completed.value: StepsExecutionCompletedEvent,
    WorkflowRunEvent.step_output.value: StepOutputEvent,
    WorkflowRunEvent.custom_event.value: CustomEvent,
}


def workflow_run_output_event_from_dict(data: dict) -> BaseWorkflowRunOutputEvent:
    event_type = data.get("event", "")
    cls = WORKFLOW_RUN_EVENT_TYPE_REGISTRY.get(event_type)
    if not cls:
        raise ValueError(f"Unknown workflow event type: {event_type}")
    return cls.from_dict(data)  # type: ignore


@dataclass
class WorkflowRunOutput:
    """Response returned by Workflow.run() functions - kept for backwards compatibility"""

    input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None
    content: Optional[Union[str, Dict[str, Any], List[Any], BaseModel, Any]] = None
    content_type: str = "str"

    # Workflow-specific fields
    workflow_id: Optional[str] = None
    workflow_name: Optional[str] = None

    run_id: Optional[str] = None
    session_id: Optional[str] = None

    # Media content fields
    images: Optional[List[Image]] = None
    videos: Optional[List[Video]] = None
    audio: Optional[List[Audio]] = None
    response_audio: Optional[Audio] = None

    # Store actual step execution results as StepOutput objects
    step_results: List[Union[StepOutput, List[StepOutput]]] = field(default_factory=list)

    # Store agent/team responses separately with parent_run_id references
    step_executor_runs: Optional[List[Union[RunOutput, TeamRunOutput]]] = None

    # Store events from workflow execution
    events: Optional[List[WorkflowRunOutputEvent]] = None

    # Workflow metrics aggregated from all steps
    metrics: Optional[WorkflowMetrics] = None

    metadata: Optional[Dict[str, Any]] = None
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
                "metadata",
                "images",
                "videos",
                "audio",
                "response_audio",
                "step_results",
                "step_executor_runs",
                "events",
                "metrics",
            ]
        }

        if self.status is not None:
            _dict["status"] = self.status.value if isinstance(self.status, RunStatus) else self.status

        if self.metadata is not None:
            _dict["metadata"] = self.metadata

        if self.images is not None:
            _dict["images"] = [img.to_dict() for img in self.images]

        if self.videos is not None:
            _dict["videos"] = [vid.to_dict() for vid in self.videos]

        if self.audio is not None:
            _dict["audio"] = [aud.to_dict() for aud in self.audio]

        if self.response_audio is not None:
            _dict["response_audio"] = self.response_audio.to_dict()

        if self.step_results:
            flattened_responses = []
            for step_response in self.step_results:
                if isinstance(step_response, list):
                    # Handle List[StepOutput] from workflow components like Steps
                    flattened_responses.extend([s.to_dict() for s in step_response])
                else:
                    # Handle single StepOutput
                    flattened_responses.append(step_response.to_dict())
            _dict["step_results"] = flattened_responses

        if self.step_executor_runs:
            _dict["step_executor_runs"] = [run.to_dict() for run in self.step_executor_runs]

        if self.metrics is not None:
            _dict["metrics"] = self.metrics.to_dict()

        if self.input is not None:
            if isinstance(self.input, BaseModel):
                _dict["input"] = self.input.model_dump(exclude_none=True)
            else:
                _dict["input"] = self.input

        if self.content and isinstance(self.content, BaseModel):
            _dict["content"] = self.content.model_dump(exclude_none=True)

        if self.events is not None:
            _dict["events"] = [e.to_dict() for e in self.events]

        return _dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowRunOutput":
        # Import here to avoid circular import
        from agno.workflow.step import StepOutput

        workflow_metrics_dict = data.pop("metrics", {})
        workflow_metrics = None
        if workflow_metrics_dict:
            from agno.workflow.workflow import WorkflowMetrics

            workflow_metrics = WorkflowMetrics.from_dict(workflow_metrics_dict)

        step_results = data.pop("step_results", [])
        parsed_step_results: List[Union[StepOutput, List[StepOutput]]] = []
        if step_results:
            for step_output_dict in step_results:
                # Reconstruct StepOutput from dict
                parsed_step_results.append(StepOutput.from_dict(step_output_dict))

        # Parse step_executor_runs
        step_executor_runs_data = data.pop("step_executor_runs", [])
        step_executor_runs: List[Union[RunOutput, TeamRunOutput]] = []
        if step_executor_runs_data:
            step_executor_runs = []
            for run_data in step_executor_runs_data:
                if "team_id" in run_data or "team_name" in run_data:
                    step_executor_runs.append(TeamRunOutput.from_dict(run_data))
                else:
                    step_executor_runs.append(RunOutput.from_dict(run_data))

        metadata = data.pop("metadata", None)

        images = data.pop("images", [])
        images = [Image.model_validate(image) for image in images] if images else None

        videos = data.pop("videos", [])
        videos = [Video.model_validate(video) for video in videos] if videos else None

        audio = data.pop("audio", [])
        audio = [Audio.model_validate(audio) for audio in audio] if audio else None

        response_audio = data.pop("response_audio", None)
        response_audio = Audio.model_validate(response_audio) if response_audio else None

        events_data = data.pop("events", [])
        final_events = []
        for event in events_data or []:
            if "agent_id" in event:
                # Agent event from agent step
                from agno.run.agent import run_output_event_from_dict

                event = run_output_event_from_dict(event)
            elif "team_id" in event:
                # Team event from team step
                from agno.run.team import team_run_output_event_from_dict

                event = team_run_output_event_from_dict(event)
            else:
                # Pure workflow event
                event = workflow_run_output_event_from_dict(event)
            final_events.append(event)
        events = final_events

        input_data = data.pop("input", None)

        return cls(
            step_results=parsed_step_results,
            metadata=metadata,
            images=images,
            videos=videos,
            audio=audio,
            response_audio=response_audio,
            events=events,
            metrics=workflow_metrics,
            step_executor_runs=step_executor_runs,
            input=input_data,
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
