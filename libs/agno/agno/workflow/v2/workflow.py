from dataclasses import dataclass, field
from datetime import datetime
from os import getenv
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Literal, Optional, Union, overload, Awaitable
from uuid import uuid4

from pydantic import BaseModel
from typing_extensions import get_args

from agno.media import Audio, Image, Video
from agno.run.base import RunStatus
from agno.run.response import RunResponseEvent
from agno.run.team import TeamRunResponseEvent
from agno.run.v2.workflow import (
    TaskCompletedEvent,
    TaskStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
    WorkflowStartedEvent,
)
from agno.storage.base import Storage
from agno.storage.session.v2.workflow import WorkflowSession as WorkflowSessionV2
from agno.utils.log import log_debug, log_info, logger, set_log_level_to_debug, set_log_level_to_info
from agno.utils.merge_dict import merge_dictionaries
from agno.workflow.v2.pipeline import Pipeline
from agno.workflow.v2.task import Task
from agno.workflow.v2.types import WorkflowExecutionInput

WorkflowExecutor = Callable[
            ["Workflow", WorkflowExecutionInput],
            Union[
                Any,
                Iterator[Any],
                Awaitable[Any],
                AsyncIterator[Any],
            ]
        ]


@dataclass
class Workflow:
    """Pipeline-based workflow execution"""

    # Workflow identification - make name optional with default
    name: Optional[str] = None
    workflow_id: Optional[str] = None
    description: Optional[str] = None

    # Workflow configuration
    pipelines: List[Pipeline] = field(default_factory=list)
    tasks: Optional[List[Task]] = field(default_factory=list)

    # Custom executor for the workflow
    executor: Optional[WorkflowExecutor] = None

    storage: Optional[Storage] = None

    # Session management
    session_id: Optional[str] = None
    workflow_session_id: Optional[str] = None
    workflow_session_state: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None

    # Runtime state
    run_id: Optional[str] = None
    run_response: Optional[WorkflowRunResponse] = None

    # Workflow session for storage
    workflow_session: Optional[WorkflowSessionV2] = None
    debug_mode: Optional[bool] = False

    def __init__(
        self,
        workflow_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        storage: Optional[Storage] = None,
        pipelines: Optional[List[Pipeline]] = None,
        tasks: Optional[List[Task]] = None,
        executor: Optional[WorkflowExecutor] = None,
        session_id: Optional[str] = None,
        workflow_session_state: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        debug_mode: Optional[bool] = False,
    ):
        self.workflow_id = workflow_id
        self.name = name
        self.description = description
        self.storage = storage
        self.pipelines = pipelines
        self.tasks = tasks
        self.executor = executor
        self.session_id = session_id
        self.workflow_session_state = workflow_session_state
        self.user_id = user_id
        self.debug_mode = debug_mode

    def initialize_workflow(self):
        if self.workflow_id is None:
            self.workflow_id = str(uuid4())
            log_debug(f"Generated new workflow_id: {self.workflow_id}")

        if self.session_id is None:
            self.session_id = str(uuid4())
            log_debug(f"Generated new session_id: {self.session_id}")

        # Set storage mode to workflow_v2
        if self.storage is not None:
            self.storage.mode = "workflow_v2"

        self._update_workflow_session_state()

        # Initialize pipelines/tasks
        for pipeline in self.pipelines or []:
            pipeline.initialize()
            for task in pipeline.tasks:
                active_executor = task.active_executor

                if hasattr(active_executor, "workflow_session_id"):
                    active_executor.workflow_session_id = self.session_id
                if hasattr(active_executor, "workflow_id"):
                    active_executor.workflow_id = self.workflow_id

                if self.workflow_session_state is not None:
                    # Initialize session_state if it doesn't exist
                    if hasattr(active_executor, "workflow_session_state"):
                        if active_executor.workflow_session_state is None:
                            active_executor.workflow_session_state = {}

                # If it's a team, update all members
                if hasattr(active_executor, "members"):
                    for member in active_executor.members:
                        member.workflow_session_id = self.session_id
                        member.workflow_id = self.workflow_id

                        # Initialize session_state if it doesn't exist
                        if member.workflow_session_state is None:
                            member.workflow_session_state = {}

    def _set_debug(self) -> None:
        """Set debug mode and configure logging"""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()

            # Propagate to pipelines
            for pipeline in self.pipelines:
                # Propagate to tasks in pipeline
                for task in pipeline.tasks:
                    # Propagate to task executors (agents/teams)
                    if hasattr(task, "active_executor") and task.active_executor:  # Fixed: removed underscore
                        executor = task.active_executor
                        if hasattr(executor, "debug_mode"):
                            executor.debug_mode = True

                        # If it's a team, propagate to all members
                        if hasattr(executor, "members"):
                            for member in executor.members:
                                if hasattr(member, "debug_mode"):
                                    member.debug_mode = True
        else:
            set_log_level_to_info()

    def _auto_create_pipeline_from_tasks(self):
        """Auto-create a pipeline from tasks for manual triggers"""
        # Only auto-create for manual triggers and when tasks are provided but no pipelines
        if self.tasks and not self.pipelines:
            # Create a default pipeline_name
            pipeline_name = "Default Pipeline"

            # Create pipeline from tasks
            auto_pipeline = Pipeline(
                name=pipeline_name,
                description=f"Auto-generated pipeline for workflow {self.name}",
                tasks=self.tasks.copy(),
            )

            # Add to pipelines
            self.pipelines = [auto_pipeline]

            log_info(f"Auto-created pipeline for workflow {self.name} with {len(self.tasks)} tasks")

    def execute(
        self, pipeline: Pipeline, execution_input: WorkflowExecutionInput, workflow_run_response: WorkflowRunResponse
    ) -> WorkflowRunResponse:
        """Execute a specific pipeline by name synchronously"""
        self._set_debug()

        log_debug(f"Starting workflow execution: {self.run_id}")
        workflow_run_response.status = RunStatus.running

        if self.executor:
            # Execute the workflow with the custom executor
            workflow_run_response.content = self.executor(self, execution_input)
            workflow_run_response.status = RunStatus.completed

        else:
            try:
                # Execute the pipeline synchronously - pass WorkflowRunResponse instead of context
                pipeline.execute(
                    pipeline_input=execution_input,
                    workflow_run_response=workflow_run_response,
                    session_id=self.session_id,
                    user_id=self.user_id,
                )

                # Collect updated workflow_session_state from agents after execution
                self._collect_workflow_session_state_from_agents_and_teams()

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")
                workflow_run_response.status = RunStatus.error
                workflow_run_response.content = f"Workflow execution failed: {e}"

        # Store error response
        if self.workflow_session:
            self.workflow_session.add_run(workflow_run_response)
        self.write_to_storage()

        return workflow_run_response

    def execute_stream(
        self,
        pipeline: Pipeline,
        execution_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""
        self._set_debug()

        log_debug(f"Starting workflow execution with streaming: {self.run_id}")
        workflow_run_response.status = RunStatus.running


        if self.executor:
            yield WorkflowStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name,
                workflow_id=workflow_run_response.workflow_id,
                session_id=workflow_run_response.session_id,
            )

            import inspect

            # Execute the workflow with the custom executor
            if inspect.isgeneratorfunction(self.executor):
                content = ""
                for chunk in self.executor(self, execution_input):
                    if (
                        isinstance(chunk, tuple(get_args(RunResponseEvent)))
                        or isinstance(chunk, tuple(get_args(TeamRunResponseEvent)))
                        or isinstance(chunk, tuple(get_args(WorkflowRunResponseEvent)))
                    ):
                        # Update the run_response with the content from the result
                        if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                            content += chunk.content
                    yield chunk
                workflow_run_response.content = content
            else:
                workflow_run_response.content = self.executor(self, execution_input)

            workflow_run_response.status = RunStatus.completed
            yield WorkflowCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                content=workflow_run_response.content,
                workflow_name=workflow_run_response.workflow_name,
                workflow_id=workflow_run_response.workflow_id,
                session_id=workflow_run_response.session_id,
            )
        else:
            try:
                # Update pipeline info in the response
                workflow_run_response.pipeline_name = pipeline.name

                log_debug("Yielding WorkflowStartedEvent")
                yield WorkflowStartedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name,
                    pipeline_name=pipeline.name,
                    workflow_id=workflow_run_response.workflow_id,
                    session_id=workflow_run_response.session_id,
                )

                # Execute the pipeline with streaming and yield all events
                for event in pipeline.execute_stream(
                    pipeline_input=execution_input,
                    workflow_run_response=workflow_run_response,
                    session_id=self.session_id,
                    user_id=self.user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                ):
                    yield event

                log_debug("Yielding WorkflowCompletedEvent")
                # Yield workflow completed event
                yield WorkflowCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    content=workflow_run_response.content,
                    workflow_name=workflow_run_response.workflow_name,
                    pipeline_name=pipeline.name,
                    workflow_id=workflow_run_response.workflow_id,
                    session_id=workflow_run_response.session_id,
                    task_responses=workflow_run_response.task_responses,
                    extra_data=workflow_run_response.extra_data,
                )

                # Collect updated workflow_session_state from agents after execution
                self._collect_workflow_session_state_from_agents_and_teams()

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")

                from agno.run.v2.workflow import WorkflowErrorEvent

                error_event = WorkflowErrorEvent(
                    run_id=self.run_id or "",
                    workflow_id=self.workflow_id,
                    workflow_name=self.name,
                    pipeline_name=pipeline.name,
                    session_id=self.session_id,
                    error=str(e),
                )

                yield error_event

                # Update workflow_run_response with error
                workflow_run_response.content = error_event.error
                workflow_run_response.status = RunStatus.error

        # Store the completed workflow response
        if self.workflow_session:
            self.workflow_session.add_run(workflow_run_response)

        # Save to storage after complete execution
        self.write_to_storage()

    async def aexecute(
        self, pipeline: Pipeline, execution_input: WorkflowExecutionInput, workflow_run_response: WorkflowRunResponse
    ) -> WorkflowRunResponse:
        """Execute a specific pipeline by name synchronously"""
        log_debug(f"Starting async workflow execution: {self.run_id}")
        workflow_run_response.status = RunStatus.running

        if self.executor:
            # Execute the workflow with the custom executor
            workflow_run_response.content = self.executor(self, execution_input)
            workflow_run_response.status = RunStatus.completed

        else:
            try:
                # Execute the pipeline asynchronously - pass WorkflowRunResponse instead of context
                await pipeline.aexecute(
                    pipeline_input=execution_input,
                    workflow_run_response=workflow_run_response,
                    session_id=self.session_id,
                    user_id=self.user_id,
                )

                # Collect updated workflow_session_state from agents after execution
                self._collect_workflow_session_state_from_agents_and_teams()

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")

                workflow_run_response.status = RunStatus.error
                workflow_run_response.content = f"Workflow execution failed: {e}"

        # Store error response
        if self.workflow_session:
            self.workflow_session.add_run(workflow_run_response)
        self.write_to_storage()

        return workflow_run_response

    async def aexecute_stream(
        self,
        pipeline: Pipeline,
        execution_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""
        log_debug(f"Starting async workflow execution with streaming: {self.run_id}")
        workflow_run_response.status = RunStatus.running

        if self.executor:
            yield WorkflowStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name,
                workflow_id=workflow_run_response.workflow_id,
                session_id=workflow_run_response.session_id,
            )

            import inspect

            # Execute the workflow with the custom executor
            if inspect.isasyncgenfunction(self.executor):
                content = ""
                async for chunk in self.executor(self, execution_input):
                    content += chunk
                    yield chunk
                workflow_run_response.content = content
            elif inspect.isgeneratorfunction(self.executor):
                content = ""
                for chunk in self.executor(self, execution_input):
                    if (
                        isinstance(chunk, tuple(get_args(RunResponseEvent)))
                        or isinstance(chunk, tuple(get_args(TeamRunResponseEvent)))
                        or isinstance(chunk, tuple(get_args(WorkflowRunResponseEvent)))
                    ):
                        # Update the run_response with the content from the result
                        if hasattr(chunk, "content") and chunk.content is not None and isinstance(chunk.content, str):
                            content += chunk.content
                    yield chunk
                workflow_run_response.content = content
            else:
                workflow_run_response.content = self.executor(self, execution_input)

            workflow_run_response.status = RunStatus.completed

            yield WorkflowCompletedEvent(
                run_id=workflow_run_response.run_id or "",
                content=workflow_run_response.content,
                workflow_name=workflow_run_response.workflow_name,
                workflow_id=workflow_run_response.workflow_id,
                session_id=workflow_run_response.session_id,
            )
        else:
            try:
                # Update pipeline info in the response
                workflow_run_response.pipeline_name = pipeline.name

                log_debug("Yielding WorkflowStartedEvent")
                yield WorkflowStartedEvent(
                    run_id=workflow_run_response.run_id or "",
                    workflow_name=workflow_run_response.workflow_name,
                    pipeline_name=pipeline.name,
                    workflow_id=workflow_run_response.workflow_id,
                    session_id=workflow_run_response.session_id,
                )

                # Execute the pipeline with streaming and yield all events
                async for event in pipeline.aexecute_stream(
                    pipeline_input=execution_input,
                    workflow_run_response=workflow_run_response,
                    session_id=self.session_id,
                    user_id=self.user_id,
                    stream_intermediate_steps=stream_intermediate_steps,
                ):
                    yield event

                log_debug("Yielding WorkflowCompletedEvent")
                # Yield workflow completed event
                yield WorkflowCompletedEvent(
                    run_id=workflow_run_response.run_id or "",
                    content=workflow_run_response.content,
                    workflow_name=workflow_run_response.workflow_name,
                    pipeline_name=pipeline.name,
                    workflow_id=workflow_run_response.workflow_id,
                    session_id=workflow_run_response.session_id,
                    task_responses=workflow_run_response.task_responses,
                    extra_data=workflow_run_response.extra_data,
                )

                # Collect updated workflow_session_state from agents after execution
                self._collect_workflow_session_state_from_agents_and_teams()

            except Exception as e:
                logger.error(f"Workflow execution failed: {e}")

                from agno.run.v2.workflow import WorkflowErrorEvent

                error_event = WorkflowErrorEvent(
                    run_id=self.run_id or "",
                    workflow_id=self.workflow_id,
                    workflow_name=self.name,
                    pipeline_name=pipeline.name,
                    session_id=self.session_id,
                    error=str(e),
                )
                yield error_event
                # Update workflow_run_response with error
                workflow_run_response.content = error_event.error
                workflow_run_response.event = WorkflowRunEvent.workflow_error

        # Store error response
        if self.workflow_session:
            self.workflow_session.add_run(workflow_run_response)
        self.write_to_storage()

    def _update_workflow_session_state(self):
        if not self.workflow_session_state:
            self.workflow_session_state = {}

        self.workflow_session_state.update(
            {
                "workflow_id": self.workflow_id,
                "run_id": self.run_id,
                "session_id": self.session_id,
            }
        )
        if self.name:
            self.workflow_session_state["workflow_name"] = self.name

        return self.workflow_session_state

    @overload
    def run(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[False] = False,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> WorkflowRunResponse: ...

    @overload
    def run(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[True] = True,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> Iterator[WorkflowRunResponseEvent]: ...

    def run(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> Union[WorkflowRunResponse, Iterator[WorkflowRunResponseEvent]]:
        """Execute the workflow synchronously with optional streaming"""
        log_debug(f"Workflow Run Start: {self.name}", center=True)
        log_debug(f"Stream: {stream}")

        if user_id is not None:
            self.user_id = user_id
            log_debug(f"User ID: {user_id}")
        if session_id is not None:
            self.session_id = session_id
            log_debug(f"Session ID: {session_id}")

        self._auto_create_pipeline_from_tasks()
        self.run_id = str(uuid4())

        self.initialize_workflow()

        # Load or create session
        self.load_session()

        selected_pipeline_name = self._get_pipeline_name(
            selector=selector, message=message, message_data=message_data, user_id=user_id, session_id=session_id
        )

        if self.pipelines:
            pipeline = self.get_pipeline(selected_pipeline_name)
            log_debug(f"Pipeline found with {len(pipeline.tasks)} tasks")
            if not pipeline:
                raise ValueError(f"Pipeline '{selected_pipeline_name}' not found")
        else:
            pipeline = None

        # Create workflow run response that will be updated by reference
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            pipeline_name=selected_pipeline_name,
            created_at=int(datetime.now().timestamp()),
        )
        self.run_response = workflow_run_response

        inputs = WorkflowExecutionInput(
            message=message,
            message_data=message_data,
            audio=audio,
            images=images,
            videos=videos,
        )
        log_debug(
            f"Created pipeline input with session state keys: {list(self.workflow_session_state.keys()) if self.workflow_session_state else 'None'}"
        )

        if stream:
            return self.execute_stream(
                pipeline=pipeline,
                execution_input=inputs,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
            )
        else:
            return self.execute(pipeline=pipeline, execution_input=inputs, workflow_run_response=workflow_run_response)

    @overload
    async def arun(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[False] = False,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> WorkflowRunResponse: ...

    @overload
    async def arun(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: Literal[True] = True,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> AsyncIterator[WorkflowRunResponseEvent]: ...

    async def arun(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
    ) -> Union[WorkflowRunResponse, AsyncIterator[WorkflowRunResponseEvent]]:
        """Execute the workflow synchronously with optional streaming"""
        log_debug(f"Async Workflow Run Start: {self.name}", center=True)
        log_debug(f"Stream: {stream}")

        # Set user_id and session_id if provided
        if user_id is not None:
            self.user_id = user_id
            log_debug(f"User ID: {user_id}")
        if session_id is not None:
            self.session_id = session_id
            log_debug(f"Session ID: {session_id}")

        self._auto_create_pipeline_from_tasks()
        self.run_id = str(uuid4())

        self.initialize_workflow()

        # Load or create session
        self.load_session()

        selected_pipeline_name = self._get_pipeline_name(
            selector=selector, message=message, message_data=message_data, user_id=user_id, session_id=session_id
        )
        pipeline = self.get_pipeline(selected_pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{selected_pipeline_name}' not found")

        # Create workflow run response that will be updated by reference
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            pipeline_name=selected_pipeline_name,
            created_at=int(datetime.now().timestamp()),
        )
        self.run_response = workflow_run_response

        inputs = WorkflowExecutionInput(
            message=message,
            message_data=message_data,
            audio=audio,
            images=images,
            videos=videos,
        )
        log_debug(
            f"Created async pipeline input with session state keys: {list(self.workflow_session_state.keys()) if self.workflow_session_state else 'None'}"
        )

        if stream:
            return self.aexecute_stream(
                pipeline=pipeline,
                execution_input=inputs,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
            )
        else:
            return await self.aexecute(
                pipeline=pipeline, execution_input=inputs, workflow_run_response=workflow_run_response
            )

    def _get_pipeline_name(
        self,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        message: Optional[str] = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Get pipeline name from selector or default to first pipeline"""
        if selector:
            if isinstance(selector, str):
                # String selector - direct pipeline name
                selected_name = selector
                log_debug(f"Using string selector: {selected_name}")
            elif callable(selector):
                # Callable selector - call with context
                try:
                    selected_name = selector(
                        message=message,
                        message_data=message_data,
                        user_id=user_id,
                        session_id=session_id,
                        pipelines=[p.name for p in self.pipelines],
                        workflow=self,
                    )
                    log_debug(f"Callable selector returned: {selected_name}")
                except Exception as e:
                    log_debug(f"Selector function failed: {e}")
                    raise ValueError(f"Pipeline selector function failed: {e}")
            else:
                raise ValueError(f"Invalid selector type: {type(selector)}. Must be string or callable.")

            # Validate selected pipeline exists
            target_pipeline = self.get_pipeline(selected_name)
            if not target_pipeline:
                available_pipelines = [seq.name for seq in self.pipelines]
                raise ValueError(
                    f"Selector returned invalid pipeline '{selected_name}'. Available pipelines: {available_pipelines}"
                )
            return selected_name
        else:
            # Default to first pipeline if no selector provided
            if not self.pipelines:
                raise ValueError("No pipelines available in workflow")
            selected_pipeline_name = self.pipelines[0].name
            log_debug(f"No selector provided, defaulting to first pipeline: {selected_pipeline_name}")
            return selected_pipeline_name

    def get_workflow_session(self) -> WorkflowSessionV2:
        """Get a WorkflowSessionV2 object for storage"""
        workflow_data = {}
        if self.pipelines:
            workflow_data["pipelines"] = [
                {
                    "name": pipeline.name,
                    "description": pipeline.description,
                    "tasks": [
                        {
                            "name": task.name,
                            "description": task.description,
                            "executor_type": task.executor_type,
                        }
                        for task in pipeline.tasks
                    ],
                }
                for pipeline in self.pipelines
            ]
        elif self.executor:
            workflow_data["executor"] = self.executor.__name__

        return WorkflowSessionV2(
            session_id=self.session_id,
            user_id=self.user_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            runs=self.workflow_session.runs if self.workflow_session else [],
            workflow_data=workflow_data,
            session_data={},
        )

    def load_workflow_session(self, session: WorkflowSessionV2):
        """Load workflow session from storage"""
        if self.workflow_id is None and session.workflow_id is not None:
            self.workflow_id = session.workflow_id
        if self.user_id is None and session.user_id is not None:
            self.user_id = session.user_id
        if self.session_id is None and session.session_id is not None:
            self.session_id = session.session_id
        if self.name is None and session.workflow_name is not None:
            self.name = session.workflow_name

        self.workflow_session = session
        log_debug(f"Loaded WorkflowSessionV2: {session.session_id}")

    def read_from_storage(self) -> Optional[WorkflowSessionV2]:
        """Load the WorkflowSessionV2 from storage"""
        if self.storage is not None and self.session_id is not None:
            session = self.storage.read(session_id=self.session_id)
            if session and isinstance(session, WorkflowSessionV2):
                self.load_workflow_session(session)
                return session
        return None

    def write_to_storage(self) -> Optional[WorkflowSessionV2]:
        """Save the WorkflowSessionV2 to storage"""
        if self.storage is not None:
            session_to_save = self.get_workflow_session()
            saved_session = self.storage.upsert(session=session_to_save)
            if saved_session and isinstance(saved_session, WorkflowSessionV2):
                self.workflow_session = saved_session
                return saved_session
        return None

    def load_session(self, force: bool = False) -> Optional[str]:
        """Load an existing session from storage or create a new one"""
        log_debug(f"Current session_id: {self.session_id}")

        if self.workflow_session is not None and not force:
            if self.session_id is not None and self.workflow_session.session_id == self.session_id:
                log_debug("Using existing workflow session")
                return self.workflow_session.session_id

        if self.storage is not None:
            # Try to load existing session
            log_debug(f"Reading WorkflowSessionV2: {self.session_id}")
            existing_session = self.read_from_storage()

            # Create new session if it doesn't exist
            if existing_session is None:
                log_debug("Creating new WorkflowSessionV2")
                self.workflow_session = WorkflowSessionV2(
                    session_id=self.session_id,  # type: ignore
                    user_id=self.user_id,
                    workflow_id=self.workflow_id,
                    workflow_name=self.name,
                )
                saved_session = self.write_to_storage()
                if saved_session is None:
                    raise Exception("Failed to create new WorkflowSessionV2 in storage")
                log_debug(f"Created WorkflowSessionV2: {saved_session.session_id}")

        return self.session_id

    def new_session(self) -> None:
        """Create a new workflow session"""
        log_debug("Creating new workflow session")

        self.workflow_session = None
        self.session_id = str(uuid4())

        log_debug(f"New session ID: {self.session_id}")
        self.load_session(force=True)

    def print_response(
        self,
        message: Optional[str] = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with rich formatting and optional streaming

        Args:
            message: The main query/input for the workflow
            message_data: Attached message data to the input
            selector: Either callable or string. If string, it will be used as the pipeline name. If callable, it will be used to select the pipeline.
            user_id: User ID
            session_id: Session ID
            audio: Audio input
            images: Image input
            videos: Video input
            stream: Whether to stream the response content
            stream_intermediate_steps: Whether to stream intermediate steps
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_task_details: Whether to show individual task outputs
            console: Rich console instance (optional)
        """

        self._auto_create_pipeline_from_tasks()

        if stream:
            self._print_response_stream(
                message=message,
                message_data=message_data,
                selector=selector,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                stream_intermediate_steps=stream_intermediate_steps,
                markdown=markdown,
                show_time=show_time,
                show_task_details=show_task_details,
                console=console,
            )
        else:
            self._print_response(
                message=message,
                message_data=message_data,
                selector=selector,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                markdown=markdown,
                show_time=show_time,
                show_task_details=show_task_details,
                console=console,
            )

    def _print_response(
        self,
        message: str,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with rich formatting (non-streaming)"""
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        # Validate pipeline configuration based on trigger type
        if not self.pipelines and not self.executor:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        pipeline_name = self._get_pipeline_name(
            selector=selector, message=message, message_data=message_data, user_id=user_id, session_id=session_id
        )

        pipeline = self.get_pipeline(pipeline_name)

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline:
            if pipeline_name and pipeline_name != "Default Pipeline":
                workflow_info += f"""\n\n**Pipeline:** {pipeline_name}"""
            workflow_info += f"""\n\n**Tasks:** {len(pipeline.tasks)} tasks"""
        if message:
            workflow_info += f"""\n\n**Message:** {message}"""
        if message_data:
            if isinstance(message_data, BaseModel):
                data_display = message_data.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(message_data, dict):
                import json

                data_display = json.dumps(message_data, indent=2, default=str)
            else:
                data_display = str(message_data)
            workflow_info += f"""\n\n**Structured Data:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        with Live(console=console) as live_log:
            status = Status("Starting workflow...", spinner="dots")
            live_log.update(status)

            try:
                # Execute workflow and get the response directly
                workflow_response: WorkflowRunResponse = self.run(
                    message=message,
                    selector=selector,
                    message_data=message_data,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                )

                response_timer.stop()

                # Show individual task responses if available
                if show_task_details and workflow_response.task_responses:
                    for i, task_output in enumerate(workflow_response.task_responses):
                        if task_output.content:
                            task_panel = create_panel(
                                content=Markdown(task_output.content) if markdown else task_output.content,
                                title=f"Task {i + 1}: {task_output.task_name} (Completed)",
                                border_style="green",
                            )
                            console.print(task_panel)

                # Show final summary
                if workflow_response.extra_data:
                    status = workflow_response.status.value
                    summary_content = ""
                    summary_content += f"""\n\n**Status:** {status}"""
                    summary_content += f"""\n\n**Tasks Completed:** {len(workflow_response.task_responses) if workflow_response.task_responses else 0}"""
                    summary_content = summary_content.strip()

                    summary_panel = create_panel(
                        content=Markdown(summary_content) if markdown else summary_content,
                        title="Execution Summary",
                        border_style="blue",
                    )
                    console.print(summary_panel)

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                import traceback

                traceback.print_exc()
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    def _print_response_stream(
        self,
        message: str,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with clean streaming - green task blocks displayed once"""
        from rich.console import Group
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        if not self.pipelines and not self.executor:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        pipeline_name = self._get_pipeline_name(
            selector=selector, message=message, message_data=message_data, user_id=user_id, session_id=session_id
        )

        pipeline = self.get_pipeline(pipeline_name)

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline:
            if pipeline_name and pipeline_name != "Default Pipeline":
                workflow_info += f"""\n\n**Pipeline:** {pipeline_name}"""
            workflow_info += f"""\n\n**Tasks:** {len(pipeline.tasks)} tasks"""
        if message:
            workflow_info += f"""\n\n**Message:** {message}"""
        if message_data:
            if isinstance(message_data, BaseModel):
                data_display = message_data.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(message_data, dict):
                import json

                data_display = json.dumps(message_data, indent=2, default=str)
            else:
                data_display = str(message_data)
            workflow_info += f"""\n\n**Structured Data:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        # Streaming execution variables
        current_task_content = ""
        current_task_name = ""
        current_task_index = 0
        task_responses = []
        task_started_printed = False

        with Live(console=console, refresh_per_second=10) as live_log:
            status = Status("Starting workflow...", spinner="dots")
            live_log.update(status)

            try:
                for response in self.run(
                    message=message,
                    message_data=message_data,
                    selector=selector,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    stream=True,
                    stream_intermediate_steps=stream_intermediate_steps,
                ):
                    # Handle the new event types
                    if isinstance(response, WorkflowStartedEvent):
                        status.update("Workflow started...")
                        live_log.update(status)

                    elif isinstance(response, TaskStartedEvent):
                        current_task_name = response.task_name or "Unknown"
                        current_task_index = response.task_index or 0
                        current_task_content = ""
                        task_started_printed = False
                        status.update(f"Starting task {current_task_index + 1}: {current_task_name}...")
                        live_log.update(status)

                    elif isinstance(response, TaskCompletedEvent):
                        task_name = response.task_name or "Unknown"
                        task_index = response.task_index or 0

                        status.update(f"Completed task {task_index + 1}: {task_name}")

                        if response.content:
                            task_responses.append(
                                {
                                    "task_name": task_name,
                                    "task_index": task_index,
                                    "content": response.content,
                                    "event": response.event,
                                }
                            )

                        # Print the final task result in green (only once)
                        if show_task_details and current_task_content and not task_started_printed:
                            live_log.update(status, refresh=True)

                            final_task_panel = create_panel(
                                content=Markdown(current_task_content) if markdown else current_task_content,
                                title=f"Task {task_index + 1}: {task_name} (Completed)",
                                border_style="green",
                            )
                            console.print(final_task_panel)
                            task_started_printed = True

                    elif isinstance(response, WorkflowCompletedEvent):
                        status.update("Workflow completed!")
                        live_log.update(status, refresh=True)

                        # Show final summary
                        if response.extra_data:
                            status = response.status
                            summary_content = ""
                            if pipeline_name != "Default Pipeline":
                                summary_content += f"""\n\n**Pipeline:** {pipeline_name}"""
                            summary_content += f"""\n\n**Status:** {status}"""
                            summary_content += f"""\n\n**Tasks Completed:** {len(response.task_responses) if response.task_responses else 0}"""
                            summary_content = summary_content.strip()

                            summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title="Execution Summary",
                                border_style="blue",
                            )
                            console.print(summary_panel)

                    else:
                        if isinstance(response, str):
                            response_str = response
                        else:
                            from agno.run.response import RunResponseContentEvent

                            # Check if this is a streaming content event from agent or team
                            if isinstance(
                                response,
                                (RunResponseContentEvent, WorkflowRunResponseEvent),
                            ):
                                # Extract the content from the streaming event
                                response_str = response.content
                            else:
                                continue

                        # Filter out empty responses and add to current task content
                        if response_str and response_str.strip():
                            current_task_content += response_str

                            # Live update the task panel with streaming content
                            if show_task_details and not task_started_printed:
                                # Show the streaming content live in green panel
                                live_task_panel = create_panel(
                                    content=Markdown(current_task_content) if markdown else current_task_content,
                                    title=f"Task {current_task_index + 1}: {current_task_name} (Streaming...)",
                                    border_style="green",
                                )

                                # Create group with status and current task content
                                group = Group(status, live_task_panel)
                                live_log.update(group)

                response_timer.stop()

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    async def aprint_response(
        self,
        message: Optional[str] = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with rich formatting and optional streaming

        Args:
            message: The main message/input for the workflow
            message_data: Attached message data to the input
            selector: Either callable or string. If string, it will be used as the pipeline name. If callable, it will be used to select the pipeline.
            user_id: User ID
            session_id: Session ID
            audio: Audio input
            images: Image input
            videos: Video input
            stream_intermediate_steps: Whether to stream intermediate steps
            stream: Whether to stream the response content
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_task_details: Whether to show individual task outputs
            console: Rich console instance (optional)
        """
        self._auto_create_pipeline_from_tasks()
        if stream:
            await self._aprint_response_stream(
                message=message,
                message_data=message_data,
                selector=selector,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                stream_intermediate_steps=stream_intermediate_steps,
                markdown=markdown,
                show_time=show_time,
                show_task_details=show_task_details,
                console=console,
            )
        else:
            await self._aprint_response(
                message=message,
                message_data=message_data,
                selector=selector,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                markdown=markdown,
                show_time=show_time,
                show_task_details=show_task_details,
                console=console,
            )

    async def _aprint_response(
        self,
        message: str,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with rich formatting (non-streaming)"""
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        # Validate pipeline configuration based on trigger type
        if not self.pipelines and not self.executor:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        pipeline_name = self._get_pipeline_name(
            selector=selector, message=message, message_data=message_data, user_id=user_id, session_id=session_id
        )

        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            console.print(f"[red]Pipeline '{pipeline_name}' not found[/red]")
            return

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline_name != "Default Pipeline":
            workflow_info += f"""\n\n**Pipeline:** {pipeline_name}"""
        workflow_info += f"""\n\n**Tasks:** {len(pipeline.tasks)} tasks"""
        if message:
            workflow_info += f"""\n\n**Message:** {message}"""
        if message_data:
            if isinstance(message_data, BaseModel):
                data_display = message_data.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(message_data, dict):
                import json

                data_display = json.dumps(message_data, indent=2, default=str)
            else:
                data_display = str(message_data)
            workflow_info += f"""\n\n**Structured Data:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        with Live(console=console) as live_log:
            status = Status("Starting async workflow...\n", spinner="dots")
            live_log.update(status)

            try:
                # Execute workflow and get the response directly
                workflow_response: WorkflowRunResponse = await self.arun(
                    message=message,
                    message_data=message_data,
                    selector=selector,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                )

                response_timer.stop()

                # Show individual task responses if available
                if show_task_details and workflow_response.task_responses:
                    for i, task_output in enumerate(workflow_response.task_responses):
                        if task_output.content:
                            task_panel = create_panel(
                                content=Markdown(task_output.content) if markdown else task_output.content,
                                title=f"Task {i + 1}: {task_output.task_name} (Completed)",
                                border_style="green",
                            )
                            console.print(task_panel)

                # Show final summary
                if workflow_response.extra_data:
                    status = workflow_response.status.value
                    summary_content = ""
                    if pipeline_name != "Default Pipeline":
                        summary_content += f"""\n\n**Pipeline:** {pipeline_name}"""
                    summary_content += f"""\n\n**Status:** {status}"""
                    summary_content += f"""\n\n**Tasks Completed:** {len(workflow_response.task_responses) if workflow_response.task_responses else 0}"""
                    summary_content = summary_content.strip()

                    summary_panel = create_panel(
                        content=Markdown(summary_content) if markdown else summary_content,
                        title="Execution Summary",
                        border_style="blue",
                    )
                    console.print(summary_panel)

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    async def _aprint_response_stream(
        self,
        message: str,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        selector: Optional[Union[str, Callable[..., str]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        stream_intermediate_steps: bool = False,
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with clean streaming - green task blocks displayed once"""
        from rich.console import Group
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        if console is None:
            from agno.cli.console import console

        if not self.pipelines and not self.executor:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        pipeline_name = self._get_pipeline_name(
            selector=selector, message=message, message_data=message_data, user_id=user_id, session_id=session_id
        )

        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            console.print(f"[red]Pipeline '{pipeline_name}' not found[/red]")
            return

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline_name != "Default Pipeline":
            workflow_info += f"""\n\n**Pipeline:** {pipeline_name}"""
        workflow_info += f"""\n\n**Tasks:** {len(pipeline.tasks)} tasks"""
        if message:
            workflow_info += f"""\n\n**Message:** {message}"""
        if message_data:
            if isinstance(message_data, BaseModel):
                data_display = message_data.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(message_data, dict):
                import json

                data_display = json.dumps(message_data, indent=2, default=str)
            else:
                data_display = str(message_data)
            workflow_info += f"""\n\n**Structured Data:**\n```json\n{data_display}\n```"""
        if user_id:
            workflow_info += f"""\n\n**User ID:** {user_id}"""
        if session_id:
            workflow_info += f"""\n\n**Session ID:** {session_id}"""
        workflow_info = workflow_info.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer
        response_timer = Timer()
        response_timer.start()

        # Streaming execution variables
        current_task_content = ""
        current_task_name = ""
        current_task_index = 0
        task_responses = []
        task_started_printed = False

        with Live(console=console, refresh_per_second=10) as live_log:
            status = Status("Starting async workflow...", spinner="dots")
            live_log.update(status)

            try:
                async for response in await self.arun(
                    message=message,
                    message_data=message_data,
                    selector=selector,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    stream=True,
                    stream_intermediate_steps=stream_intermediate_steps,
                ):
                    # Handle the new event types
                    if isinstance(response, WorkflowStartedEvent):
                        status.update("Workflow started...")
                        live_log.update(status)

                    elif isinstance(response, TaskStartedEvent):
                        current_task_name = response.task_name or "Unknown"
                        current_task_index = response.task_index or 0
                        current_task_content = ""
                        task_started_printed = False
                        status.update(f"Starting task {current_task_index + 1}: {current_task_name}...")
                        live_log.update(status)

                    elif isinstance(response, TaskCompletedEvent):
                        task_name = response.task_name or "Unknown"
                        task_index = response.task_index or 0

                        status.update(f"Completed task {task_index + 1}: {task_name}")

                        if response.content:
                            task_responses.append(
                                {
                                    "task_name": task_name,
                                    "task_index": task_index,
                                    "content": response.content,
                                    "event": response.event,
                                }
                            )

                        # Print the final task result in green (only once)
                        if show_task_details and current_task_content and not task_started_printed:
                            live_log.update(status, refresh=True)

                            final_task_panel = create_panel(
                                content=Markdown(current_task_content) if markdown else current_task_content,
                                title=f"Task {task_index + 1}: {task_name} (Completed)",
                                border_style="green",
                            )
                            console.print(final_task_panel)
                            task_started_printed = True

                    elif isinstance(response, WorkflowCompletedEvent):
                        status.update("Workflow completed!")
                        live_log.update(status, refresh=True)

                        # Show final summary
                        if response.extra_data:
                            status = response.status
                            summary_content = ""
                            if pipeline_name != "Default Pipeline":
                                summary_content += f"""\n\n**Pipeline:** {pipeline_name}"""
                            summary_content += f"""\n\n**Status:** {status}"""
                            summary_content += f"""\n\n**Tasks Completed:** {len(response.task_responses) if response.task_responses else 0}"""
                            summary_content = summary_content.strip()

                            summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title="Execution Summary",
                                border_style="blue",
                            )
                            console.print(summary_panel)

                    else:
                        response_str = None

                        if isinstance(response, str):
                            response_str = response
                        else:
                            from agno.run.response import RunResponseContentEvent

                            # Check if this is a streaming content event from agent or team
                            if isinstance(
                                response,
                                (RunResponseContentEvent, WorkflowRunResponseEvent),
                            ):
                                # Extract the content from the streaming event
                                response_str = response.content
                            else:
                                continue

                        # Filter out empty responses and add to current task content
                        if response_str and response_str.strip():
                            current_task_content += response_str

                            # Live update the task panel with streaming content
                            if show_task_details and not task_started_printed:
                                # Show the streaming content live in green panel
                                live_task_panel = create_panel(
                                    content=Markdown(current_task_content) if markdown else current_task_content,
                                    title=f"Task {current_task_index + 1}: {current_task_name} (Streaming...)",
                                    border_style="green",
                                )

                                # Create group with status and current task content
                                group = Group(status, live_task_panel)
                                live_log.update(group)

                response_timer.stop()

                # Final completion message
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
                )
                console.print(error_panel)

    def add_pipeline(self, pipeline: Pipeline) -> None:
        """Add a pipeline to the workflow"""
        self.pipelines.append(pipeline)

    def remove_pipelines(self, pipeline_name: str) -> bool:
        """Remove a pipeline by name"""
        for i, pipeline in enumerate(self.pipelines):
            if pipeline.name == pipeline_name:
                del self.pipelines[i]
                return True
        return False

    def get_pipeline(self, pipeline_name: str) -> Optional[Pipeline]:
        """Get a pipeline by name"""
        for pipeline in self.pipelines:
            if pipeline.name == pipeline_name:
                return pipeline
        return None

    def list_pipelines(self) -> List[str]:
        """List all pipeline names"""
        return [pipeline.name for pipeline in self.pipelines]

    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary representation"""
        return {
            "name": self.name,
            "workflow_id": self.workflow_id,
            "description": self.description,
            "pipelines": [
                {
                    "name": p.name,
                    "description": p.description,
                    "tasks": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "executor_type": t.executor_type,
                        }
                        for t in p.tasks
                    ],
                }
                for p in self.pipelines
            ],
            "session_id": self.session_id,
        }

    def _collect_workflow_session_state_from_agents_and_teams(self):
        """Collect updated workflow_session_state from agents after task execution"""
        log_debug("Collecting workflow session state from agents and teams")

        if self.workflow_session_state is None:
            self.workflow_session_state = {}
            log_debug("Initialized empty workflow session state")

        # Collect state from all agents in all pipelines
        for pipeline in self.pipelines:
            log_debug(f"Collecting state from pipeline: {pipeline.name}")
            for task in pipeline.tasks:
                executor = task.active_executor
                if hasattr(executor, "workflow_session_state") and executor.workflow_session_state:
                    merge_dictionaries(self.workflow_session_state, executor.workflow_session_state)
                    log_debug("Merged executor session state into workflow")

                # If it's a team, collect from all members
                if hasattr(executor, "members"):
                    log_debug(f"Collecting state from {len(executor.members)} team members")
                    for member in executor.members:
                        if hasattr(member, "workflow_session_state") and member.workflow_session_state:
                            log_debug(
                                f"Found session state in team member {type(member).__name__}: {list(member.workflow_session_state.keys())}"
                            )
                            merge_dictionaries(self.workflow_session_state, member.workflow_session_state)
                            log_debug("Merged team member session state into workflow")
