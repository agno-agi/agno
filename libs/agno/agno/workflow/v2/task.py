from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact, ImageArtifact, VideoArtifact
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.run.v2.workflow import (
    TaskStartedEvent,
    WorkflowRunEvent,
    WorkflowRunResponse,
)
from agno.team import Team
from agno.utils.log import logger


@dataclass
class TaskInput:
    """Input data for a task execution"""

    query: Optional[str] = None
    message: Optional[str] = None

    # state
    workflow_session_state: Optional[Dict[str, Any]] = None

    # Previous task outputs (for chaining)
    previous_outputs: Optional[Dict[str, Any]] = None

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    def get_primary_input(self) -> str:
        """Get the primary text input (query or message)"""
        return self.query or self.message or ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "query": self.query,
            "message": self.message,
            "workflow_session_state": self.workflow_session_state,
            "previous_outputs": self.previous_outputs,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
            "extra_data": self.extra_data,
        }


@dataclass
class TaskOutput:
    """Output data from a task execution"""

    # Primary output
    content: Optional[str] = None

    # Execution response
    response: Optional[Union[RunResponse, TeamRunResponse]] = None

    # Media outputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    # Structured data
    data: Optional[Dict[str, Any]] = None

    # Execution metadata
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "content": self.content,
            "response": self.response.to_dict() if self.response else None,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
            "data": self.data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskOutput":
        """Create TaskOutput from dictionary"""
        from agno.run.response import RunResponse
        from agno.run.team import TeamRunResponse

        # Reconstruct response if present
        response_data = data.get("response")
        response = None
        if response_data:
            # Determine if it's RunResponse or TeamRunResponse based on structure
            if "team_id" in response_data or "team_name" in response_data:
                response = TeamRunResponse.from_dict(response_data)
            else:
                response = RunResponse.from_dict(response_data)

        # Reconstruct media artifacts
        images = data.get("images")
        if images:
            images = [ImageArtifact.model_validate(img) for img in images]

        videos = data.get("videos")
        if videos:
            videos = [VideoArtifact.model_validate(vid) for vid in videos]

        audio = data.get("audio")
        if audio:
            audio = [AudioArtifact.model_validate(aud) for aud in audio]

        return cls(
            content=data.get("content"),
            response=response,
            images=images,
            videos=videos,
            audio=audio,
            data=data.get("data"),
            metadata=data.get("metadata"),
        )


@dataclass
class Task:
    """A single unit of work in a workflow pipeline"""

    name: str
    # Executor options - only one should be provided
    agent: Optional[Agent] = None
    team: Optional[Team] = None
    execution_function: Optional[Callable[[Dict[str, Any]], Any]] = None

    task_id: Optional[str] = None
    description: Optional[str] = None

    # Task configuration
    retry_count: int = 0
    max_retries: int = 3
    timeout_seconds: Optional[int] = None

    skip_on_failure: bool = False

    # Input validation mode
    # If False, only warn about missing inputs
    strict_input_validation: bool = False

    def __post_init__(self):
        if self.task_id is None:
            self.task_id = str(uuid4())

        # Validate executor configuration
        self._validate_executor_config()

        # Set the active executor
        self._set_active_executor()

    def _validate_executor_config(self):
        """Validate that only one executor type is provided"""
        executor_count = sum(
            [
                self.agent is not None,
                self.team is not None,
                self.execution_function is not None,
            ]
        )

        if executor_count == 0:
            raise ValueError(f"Task '{self.name}' must have one executor: agent=, team=, or execution_function=")

        if executor_count > 1:
            provided_executors = []
            if self.agent is not None:
                provided_executors.append("agent")
            if self.team is not None:
                provided_executors.append("team")
            if self.execution_function is not None:
                provided_executors.append("execution_function")

            raise ValueError(
                f"Task '{self.name}' can only have one executor type. "
                f"Provided: {', '.join(provided_executors)}. "
                f"Please use only one of: agent=, team=, or execution_function="
            )

    def _set_active_executor(self):
        """Set the active executor based on what was provided"""
        if self.agent is not None:
            self._active_executor = self.agent
            self._executor_type = "agent"
        elif self.team is not None:
            self._active_executor = self.team
            self._executor_type = "team"
        elif self.execution_function is not None:
            self._active_executor = self.execution_function
            self._executor_type = "function"

    def execute(
        self, task_input: TaskInput, context: Dict[str, Any] = None
    ) -> Iterator[Union[WorkflowRunResponse, TaskOutput]]:
        """Execute the task with TaskInput, yielding events and final TaskOutput"""
        logger.info(f"Executing task: {self.name}")

        # Yield task started event
        yield TaskStartedEvent(
            run_id=context.get("run_id", ""),
            content=f"Starting task: {self.name}",
            workflow_name=context.get("workflow_name") if context else None,
            pipeline_name=context.get("pipeline_name") if context else None,
            task_name=self.name,
            task_index=context.get("task_index") if context else None,
            workflow_id=context.get("workflow_id") if context else None,
            session_id=context.get("session_id") if context else None,
        )

        # Initialize executor with context and workflow session state
        self._initialize_executor_context(task_input, context)

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                response = self._execute_task(task_input)

                # Create TaskOutput from response
                task_output = self._create_task_output(response, task_input)

                logger.info(f"Task {self.name} completed successfully")
                yield task_output
                return

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Task {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        logger.info(f"Task {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty TaskOutput for skipped task
                        task_output = TaskOutput(
                            content=f"Task {self.name} failed but skipped", metadata={"skipped": True, "error": str(e)}
                        )
                        yield task_output
                        return
                    else:
                        raise e

    async def aexecute(
        self, task_input: TaskInput, context: Dict[str, Any] = None
    ) -> AsyncIterator[Union[WorkflowRunResponse, TaskOutput]]:
        """Execute the task with TaskInput asynchronously, yielding events and final TaskOutput"""
        logger.info(f"Executing async task: {self.name}")

        # Yield task started event
        yield WorkflowRunResponse(
            content=f"Starting task: {self.name}",
            event=WorkflowRunEvent.task_started,
            workflow_name=context.get("workflow_name") if context else None,
            pipeline_name=context.get("pipeline_name") if context else None,
            task_name=self.name,
            task_index=context.get("task_index") if context else None,
            workflow_id=context.get("workflow_id") if context else None,
            run_id=context.get("run_id") if context else None,
            session_id=context.get("session_id") if context else None,
        )

        # Initialize executor with context and workflow session state
        self._initialize_executor_context(task_input, context)

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._aexecute_task(task_input)

                # Create TaskOutput from response
                task_output = self._create_task_output(response, task_input)

                logger.info(f"Async task {self.name} completed successfully")
                yield task_output
                return

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Async task {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        logger.info(f"Async task {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty TaskOutput for skipped task
                        task_output = TaskOutput(
                            content=f"Task {self.name} failed but skipped", metadata={"skipped": True, "error": str(e)}
                        )
                        yield task_output
                        return
                    else:
                        raise e

    def _initialize_executor_context(self, task_input: TaskInput, context: Dict[str, Any] = None):
        """Initialize the executor with context and workflow session state"""
        if self._executor_type in ["agent", "team"]:
            executor = self._active_executor

            # Set workflow context
            if context:
                if hasattr(executor, "workflow_id"):
                    executor.workflow_id = context.get("workflow_id")
                if hasattr(executor, "workflow_session_id"):
                    executor.workflow_session_id = context.get("session_id")

            # Set workflow session state
            if task_input.workflow_session_state and hasattr(executor, "session_state"):
                if executor.session_state is None:
                    executor.session_state = {}
                executor.session_state.update(task_input.workflow_session_state)

    def _execute_task(self, task_input: TaskInput) -> Union[RunResponse, TeamRunResponse, TaskOutput]:
        """Execute the task based on executor type"""
        if self._executor_type == "function":
            # Execute function directly with TaskInput
            result = self._active_executor(task_input)

            # If function returns TaskOutput, use it directly
            if isinstance(result, TaskOutput):
                return result

            # Otherwise, wrap in TaskOutput
            return TaskOutput(content=str(result))

        # For agents and teams, prepare message with context
        message = task_input.get_primary_input()

        # Add context information to message if available
        if task_input.previous_outputs:
            message = self._format_message_with_previous_outputs(message, task_input.previous_outputs)

        # Execute agent or team with media
        if self._executor_type == "agent":
            return self._active_executor.run(
                message=message,
                images=task_input.images,
                videos=task_input.videos,
                audio=task_input.audio,
            )
        elif self._executor_type == "team":
            return self._active_executor.run(
                message=message,
                images=task_input.images,
                videos=task_input.videos,
                audio=task_input.audio,
            )
        else:
            raise ValueError(f"Unsupported executor type: {self._executor_type}")

    async def _aexecute_task(self, task_input: TaskInput) -> Union[RunResponse, TeamRunResponse, TaskOutput]:
        """Execute the task based on executor type asynchronously"""
        if self._executor_type == "function":
            # Execute function directly with TaskInput
            result = await self._active_executor(task_input)

            # If function returns TaskOutput, use it directly
            if isinstance(result, TaskOutput):
                return result

            # Otherwise, wrap in TaskOutput
            return TaskOutput(content=str(result))

        # For agents and teams, prepare message with context
        message = task_input.get_primary_input()

        # Add context information to message if available
        if task_input.previous_outputs:
            message = self._format_message_with_previous_outputs(message, task_input.previous_outputs)

        # Execute agent or team with media asynchronously
        if self._executor_type == "agent":
            return await self._active_executor.arun(
                message=message,
                images=task_input.images,
                videos=task_input.videos,
                audio=task_input.audio,
                files=getattr(task_input, "files", None),
            )
        elif self._executor_type == "team":
            return await self._active_executor.arun(
                message=message,
                images=task_input.images,
                videos=task_input.videos,
                audio=task_input.audio,
                files=getattr(task_input, "files", None),
            )
        else:
            raise ValueError(f"Unsupported executor type: {self._executor_type}")

    def _format_message_with_previous_outputs(self, message: str, previous_outputs: Dict[str, Any]) -> str:
        """Format message with previous task outputs for context"""
        context_parts = [message]

        if previous_outputs:
            context_parts.append("\n--- Previous Task Outputs ---")
            for key, value in previous_outputs.items():
                context_parts.append(f"{key}: {value}")
            context_parts.append("--- End Previous Outputs ---\n")

        return "\n".join(context_parts)

    def _create_task_output(
        self, response: Union[RunResponse, TeamRunResponse, TaskOutput], task_input: TaskInput
    ) -> TaskOutput:
        """Create TaskOutput from execution response"""
        if isinstance(response, TaskOutput):
            return response

        # Create metadata
        metadata = {
            "task_name": self.name,
            "task_id": self.task_id,
            "executor_type": self._executor_type,
            "executor_name": self.executor_name,
        }

        # Extract media from response
        images = getattr(response, "images", None)
        videos = getattr(response, "videos", None)
        audio = getattr(response, "audio", None)

        return TaskOutput(
            content=response.content,
            response=response,
            images=images,
            videos=videos,
            audio=audio,
            metadata=metadata,
        )

    def _convert_function_result_to_response(self, result: Any) -> RunResponse:
        """Convert function execution result to RunResponse"""
        if isinstance(result, RunResponse):
            return result
        elif isinstance(result, str):
            return RunResponse(content=result)
        elif isinstance(result, dict):
            # If it's a dict, try to extract content
            content = result.get("content", str(result))
            return RunResponse(content=content)
        else:
            # Convert any other type to string
            return RunResponse(content=str(result))

    @property
    def executor_name(self) -> str:
        """Get the name of the current executor"""
        if hasattr(self._active_executor, "name"):
            return self._active_executor.name
        elif self._executor_type == "function":
            return getattr(self._active_executor, "__name__", "anonymous_function")
        else:
            return f"{self._executor_type}_executor"

    @property
    def executor_type(self) -> str:
        """Get the type of the current executor"""
        return self._executor_type
