from dataclasses import dataclass, field
from datetime import datetime
from os import getenv
from typing import Any, AsyncIterator, Dict, Iterator, List, Literal, Optional, Union, overload
from typing import Sequence as TypingSequence
from uuid import uuid4

from pydantic import BaseModel

from agno.media import Audio, Image, Video
from agno.run.base import RunStatus
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
from agno.workflow.v2.pipeline import Pipeline, PipelineInput
from agno.workflow.v2.task import Task


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

    debug_mode: bool = False

    def __post_init__(self):
        # Handle inheritance - get name from class attribute if not provided
        if self.name is None:
            self.name = getattr(self.__class__, "name", self.__class__.__name__)

        # Handle other class attributes
        if hasattr(self.__class__, "description") and self.description is None:
            self.description = getattr(self.__class__, "description", None)

        if hasattr(self.__class__, "storage") and self.storage is None:
            self.storage = getattr(self.__class__, "storage", None)

        if hasattr(self.__class__, "pipelines") and not self.pipelines:
            class_pipelines = getattr(self.__class__, "pipelines", [])
            if class_pipelines:
                self.pipelines = class_pipelines.copy()

        if hasattr(self.__class__, "tasks") and not self.tasks:
            class_tasks = getattr(self.__class__, "tasks", [])
            if class_tasks:
                self.tasks = class_tasks.copy()

        if self.workflow_id is None:
            self.workflow_id = str(uuid4())

        if self.session_id is None:
            self.session_id = str(uuid4())

        # Set storage mode to workflow_v2
        self.set_storage_mode()

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
                    if hasattr(task, "_active_executor") and task._active_executor:
                        executor = task._active_executor
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
            return pipeline_name

    def set_storage_mode(self):
        """Set storage mode to workflow_v2"""
        if self.storage is not None:
            self.storage.mode = "workflow_v2"

    def execute_pipeline(
        self, pipeline: Pipeline, pipeline_input: PipelineInput, workflow_run_response: WorkflowRunResponse
    ) -> WorkflowRunResponse:
        """Execute a specific pipeline by name synchronously"""
        self._set_debug()

        log_debug(f"Starting workflow execution: {self.run_id}")
        workflow_run_response.status = RunStatus.running

        try:
            log_debug(f"Executing pipeline '{pipeline.name}' with {len(pipeline.tasks)} tasks")

            # Execute the pipeline synchronously - pass WorkflowRunResponse instead of context
            pipeline.execute(pipeline_input=pipeline_input, workflow_run_response=workflow_run_response)

            log_debug("Pipeline execution completed successfully")

            # Collect updated workflow_session_state from agents after execution
            self._collect_workflow_session_state_from_agents_and_teams()

            workflow_run_response.status = RunStatus.completed
            log_debug(f"Workflow status set to: {workflow_run_response.status}")

            # Store the completed workflow response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
                log_debug(f"Added run to workflow session: {workflow_run_response.run_id}")

            # Save to storage after complete execution
            self.write_to_storage()
            log_debug("Workflow saved to storage")

            return workflow_run_response

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            workflow_run_response.status = RunStatus.error
            workflow_run_response.content = f"Workflow execution failed: {e}"

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
            self.write_to_storage()

            return workflow_run_response

    def execute_pipeline_stream(
        self,
        pipeline: Pipeline,
        pipeline_input: PipelineInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""
        self._set_debug()

        log_debug(f"Starting workflow execution with streaming: {self.run_id}")
        workflow_run_response.status = RunStatus.running

        try:
            log_debug(f"Executing pipeline '{pipeline.name}' with streaming")

            # Execute the pipeline with streaming and yield all events
            for event in pipeline.execute_stream(
                pipeline_input=pipeline_input,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
            ):
                log_debug(f"Yielding event: {type(event).__name__}")

                # Store completed workflow response when we get the final event
                if isinstance(event, WorkflowCompletedEvent):
                    log_debug("Received WorkflowCompletedEvent")
                    # Update the workflow_run_response with final data
                    workflow_run_response.content = event.content
                    workflow_run_response.task_responses = event.task_responses
                    workflow_run_response.extra_data = event.extra_data
                    workflow_run_response.status = RunStatus.completed
                    log_debug(f"Final workflow status: {workflow_run_response.status}")

                yield event

            log_debug("Pipeline streaming execution completed")

            # Collect updated workflow_session_state from agents after execution
            self._collect_workflow_session_state_from_agents_and_teams()

            # Store the completed workflow response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
                log_debug(f"Added streamed run to workflow session: {workflow_run_response.run_id}")

            # Save to storage after complete execution
            self.write_to_storage()
            log_debug("Streamed workflow saved to storage")

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            from agno.run.v2.workflow import WorkflowErrorEvent

            error_event = WorkflowErrorEvent(
                run_id=self.run_id or "",
                content=f"Workflow execution failed: {e}",
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline.name,
                session_id=self.session_id,
                error=str(e),
            )

            yield error_event

            # Update workflow_run_response with error
            workflow_run_response.content = error_event.content
            workflow_run_response.status = RunStatus.error

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
            self.write_to_storage()

    async def aexecute_pipeline(
        self, pipeline: Pipeline, pipeline_input: PipelineInput, workflow_run_response: WorkflowRunResponse
    ) -> WorkflowRunResponse:
        """Execute a specific pipeline by name synchronously"""
        log_debug(f"Starting async workflow execution: {self.run_id}")
        workflow_run_response.status = RunStatus.running

        try:
            log_debug(f"Executing pipeline '{pipeline.name}' with {len(pipeline.tasks)} tasks asynchronously")

            # Execute the pipeline asynchronously - pass WorkflowRunResponse instead of context
            await pipeline.aexecute(pipeline_input=pipeline_input, workflow_run_response=workflow_run_response)

            log_debug("Async pipeline execution completed successfully")

            # Collect updated workflow_session_state from agents after execution
            self._collect_workflow_session_state_from_agents_and_teams()

            workflow_run_response.status = RunStatus.completed
            log_debug(f"Async workflow status set to: {workflow_run_response.status}")

            # Store the completed workflow response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
                log_debug(f"Added async run to workflow session: {workflow_run_response.run_id}")

            # Save to storage after complete execution
            self.write_to_storage()
            log_debug("Async workflow saved to storage")

            return workflow_run_response

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            workflow_run_response.status = RunStatus.error
            workflow_run_response.content = f"Workflow execution failed: {e}"

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
            self.write_to_storage()

            return workflow_run_response

    async def aexecute_pipeline_stream(
        self,
        pipeline: Pipeline,
        pipeline_input: PipelineInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""
        log_debug(f"Starting async workflow execution with streaming: {self.run_id}")
        workflow_run_response.status = RunStatus.running

        try:
            log_debug(f"Executing pipeline '{pipeline.name}' with async streaming")

            # Execute the pipeline with streaming and yield all events
            async for event in pipeline.aexecute_stream(
                pipeline_input=pipeline_input,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
            ):
                log_debug(f"Yielding async event: {type(event).__name__}")

                # Store completed workflow response when we get the final event
                if isinstance(event, WorkflowCompletedEvent):
                    log_debug("Received async WorkflowCompletedEvent")

                    # Update the workflow_run_response with final data
                    workflow_run_response.content = event.content
                    workflow_run_response.task_responses = event.task_responses
                    workflow_run_response.extra_data = event.extra_data
                    workflow_run_response.status = RunStatus.completed
                    log_debug(f"Final async workflow status: {workflow_run_response.status}")

                yield event

            log_debug("Async pipeline streaming execution completed")

            # Collect updated workflow_session_state from agents after execution
            self._collect_workflow_session_state_from_agents_and_teams()

            # Store the completed workflow response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
                log_debug(f"Added async streamed run to workflow session: {workflow_run_response.run_id}")

            # Save to storage after complete execution
            self.write_to_storage()
            log_debug("Async streamed workflow saved to storage")

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            from agno.run.v2.workflow import WorkflowErrorEvent

            error_event = WorkflowErrorEvent(
                run_id=self.run_id or "",
                content=f"Workflow execution failed: {e}",
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline.name,
                session_id=self.session_id,
                error=str(e),
            )

            yield error_event

            # Update workflow_run_response with error
            workflow_run_response.content = error_event.content
            workflow_run_response.event = WorkflowRunEvent.workflow_error

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
            self.write_to_storage()

    def update_agents_and_teams_session_info(self):
        """Update agents and teams with workflow session information"""
        log_debug("Updating agents and teams with workflow session information")
        log_debug(f"Workflow ID: {self.workflow_id}")
        log_debug(f"Session ID: {self.session_id}")

        # Update all agents in pipelines
        for pipeline in self.pipelines:
            log_debug(f"Processing pipeline: {pipeline.name}")
            for task in pipeline.tasks:
                log_debug(f"Processing task: {task.name}")
                active_executor = task._active_executor

                if hasattr(active_executor, "workflow_session_id"):
                    active_executor.workflow_session_id = self.session_id
                    log_debug(f"Set workflow_session_id for {type(active_executor).__name__}")
                if hasattr(active_executor, "workflow_id"):
                    active_executor.workflow_id = self.workflow_id
                    log_debug(f"Set workflow_id for {type(active_executor).__name__}")

                # Set workflow_session_state on agents and teams
                self._update_executor_workflow_session_state(active_executor)

                # If it's a team, update all members
                if hasattr(active_executor, "members"):
                    log_debug(f"Processing {len(active_executor.members)} team members")
                    for member in active_executor.members:
                        if hasattr(member, "workflow_session_id"):
                            member.workflow_session_id = self.session_id
                            log_debug(f"Set workflow_session_id for team member: {type(member).__name__}")
                        if hasattr(member, "workflow_id"):
                            member.workflow_id = self.workflow_id
                            log_debug(f"Set workflow_id for team member: {type(member).__name__}")

                        # Set workflow_session_state on team members
                        self._update_executor_workflow_session_state(member)

    @overload
    def run(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream: Literal[False] = False,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> WorkflowRunResponse: ...

    @overload
    def run(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream: Literal[True] = True,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> Iterator[WorkflowRunResponseEvent]: ...

    def run(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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

        # Load or create session
        self.load_session()

        # Prepare primary input by combining message and message_data
        primary_input = self._prepare_primary_input(message, message_data)
        log_debug(f"Primary input prepared: {len(primary_input) if primary_input else 0} characters")

        self.run_id = str(uuid4())
        log_debug(f"Run ID: {self.run_id}")

        selected_pipeline_name = self._get_pipeline_name(pipeline_name)
        log_debug(f"Selected pipeline: {selected_pipeline_name}")

        pipeline = self.get_pipeline(selected_pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{selected_pipeline_name}' not found")

        log_debug(f"Pipeline found with {len(pipeline.tasks)} tasks")

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
        log_debug(f"Created workflow run response: {workflow_run_response.run_id}")

        inputs = PipelineInput(
            message=primary_input,
            workflow_session_state=self.workflow_session_state,
            audio=audio,
            images=images,
            videos=videos,
        )
        log_debug(
            f"Created pipeline input with session state keys: {list(self.workflow_session_state.keys()) if self.workflow_session_state else 'None'}"
        )

        self.update_agents_and_teams_session_info()

        if stream:
            log_debug("Starting streaming execution")
            return self.execute_pipeline_stream(
                pipeline=pipeline,
                pipeline_input=inputs,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
            )
        else:
            log_debug("Starting non-streaming execution")
            return self.execute_pipeline(
                pipeline=pipeline, pipeline_input=inputs, workflow_run_response=workflow_run_response
            )

    @overload
    async def arun(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream: Literal[False] = False,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> WorkflowRunResponse: ...

    @overload
    async def arun(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream: Literal[True] = True,
        stream_intermediate_steps: Optional[bool] = None,
    ) -> AsyncIterator[WorkflowRunResponseEvent]: ...

    async def arun(
        self,
        message: str = None,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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

        # Load or create session
        self.load_session()

        # Prepare primary input by combining message and message_data
        primary_input = self._prepare_primary_input(message, message_data)
        log_debug(f"Primary input prepared: {len(primary_input) if primary_input else 0} characters")

        # Initialize execution
        self.run_id = str(uuid4())
        log_debug(f"Run ID: {self.run_id}")

        selected_pipeline_name = self._get_pipeline_name(pipeline_name)
        pipeline = self.get_pipeline(selected_pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{selected_pipeline_name}' not found")

        log_debug(f"Pipeline found with {len(pipeline.tasks)} tasks")

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
        log_debug(f"Created async workflow run response: {workflow_run_response.run_id}")

        inputs = PipelineInput(
            message=primary_input,
            workflow_session_state=self.workflow_session_state,
            audio=audio,
            images=images,
            videos=videos,
        )
        log_debug(
            f"Created async pipeline input with session state keys: {list(self.workflow_session_state.keys()) if self.workflow_session_state else 'None'}"
        )

        self.update_agents_and_teams_session_info()

        if stream:
            log_debug("Starting async streaming execution")
            return self.aexecute_pipeline_stream(
                pipeline=pipeline,
                pipeline_input=inputs,
                workflow_run_response=workflow_run_response,
                stream_intermediate_steps=stream_intermediate_steps,
            )
        else:
            log_debug("Starting async non-streaming execution")
            return await self.aexecute_pipeline(
                pipeline=pipeline, pipeline_input=inputs, workflow_run_response=workflow_run_response
            )

    def _get_pipeline_name(self, pipeline_name: Optional[str] = None) -> str:
        # If pipeline_name is provided, use that specific pipeline
        if pipeline_name:
            target_pipeline = self.get_pipeline(pipeline_name)
            if not target_pipeline:
                available_pipelines = [seq.name for seq in self.pipelines]
                raise ValueError(f"Pipeline '{pipeline_name}' not found. Available pipelines: {available_pipelines}")
            selected_pipeline_name = pipeline_name
        else:
            # Default to first pipeline if no pipeline_name specified
            selected_pipeline_name = self.pipelines[0].name
        return selected_pipeline_name

    def get_workflow_session(self) -> WorkflowSessionV2:
        """Get a WorkflowSessionV2 object for storage"""
        return WorkflowSessionV2(
            session_id=self.session_id,
            user_id=self.user_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            runs=self.workflow_session.runs if self.workflow_session else [],
            workflow_data={
                "name": self.name,
                "description": self.description,
                "pipelines": [
                    {
                        "name": seq.name,
                        "description": seq.description,
                        "tasks": [
                            {
                                "name": task.name,
                                "description": task.description,
                                "executor_type": task.executor_type,
                            }
                            for task in seq.tasks
                        ],
                    }
                    for seq in self.pipelines
                ],
            },
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
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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
        if stream:
            self._print_response_stream(
                message=message,
                message_data=message_data,
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
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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

        pipeline_name = self._auto_create_pipeline_from_tasks()

        # Validate pipeline configuration based on trigger type
        if not self.pipelines:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        # Determine which pipeline to use
        if pipeline_name:
            pipeline = self.get_pipeline(pipeline_name)
            if not pipeline:
                available_pipelines = [seq.name for seq in self.pipelines]
                console.print(
                    f"[red]Pipeline '{pipeline_name}' not found. Available pipelines: {available_pipelines}[/red]"
                )
                return
        else:
            # Default to first pipeline
            pipeline = self.pipelines[0]
            pipeline_name = pipeline.name

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline.name != "Default Pipeline":
            workflow_info += f"""\n\n**Pipeline:** {pipeline.name}"""
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
                    message_data=message_data,
                    pipeline_name=pipeline_name,
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
                                title=f"Task {i + 1}: {getattr(task_output, 'metadata', {}).get('task_name', 'Unknown')} (Completed)",
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

    def _print_response_stream(
        self,
        message: str,
        message_data: Optional[Union[BaseModel, Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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

        pipeline_name = self._auto_create_pipeline_from_tasks()

        if not self.pipelines:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        if pipeline_name:
            pipeline = self.get_pipeline(pipeline_name)
            if not pipeline:
                available_pipelines = [seq.name for seq in self.pipelines]
                console.print(
                    f"[red]Pipelines '{pipeline_name}' not found. Available pipelines: {available_pipelines}[/red]"
                )
                return
        else:
            pipeline = self.pipelines[0]
            pipeline_name = pipeline.name

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline.name != "Default Pipeline":
            workflow_info += f"""\n\n**Pipeline:** {pipeline.name}"""
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
                    pipeline_name=pipeline_name,
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
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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
        if stream:
            await self._aprint_response_stream(
                message=message,
                message_data=message_data,
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
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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

        pipeline_name = self._auto_create_pipeline_from_tasks()

        # Validate pipeline configuration based on trigger type
        if not self.pipelines:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        # Determine which pipeline to use
        if pipeline_name:
            pipeline = self.get_pipeline(pipeline_name)
            if not pipeline:
                available_pipelines = [seq.name for seq in self.pipelines]
                console.print(
                    f"[red]Pipeline '{pipeline_name}' not found. Available pipelines: {available_pipelines}[/red]"
                )
                return
        else:
            # Default to first pipeline
            pipeline = self.pipelines[0]
            pipeline_name = pipeline.name

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline.name != "Default Pipeline":
            workflow_info += f"""\n\n**Pipeline:** {pipeline.name}"""
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
                    pipeline_name=pipeline_name,
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
                                title=f"Task {i + 1}: {getattr(task_output, 'metadata', {}).get('task_name', 'Unknown')} (Completed)",
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
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
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

        pipeline_name = self._auto_create_pipeline_from_tasks()

        if not self.pipelines:
            console.print("[red]No pipelines available in this workflow[/red]")
            return

        if pipeline_name:
            pipeline = self.get_pipeline(pipeline_name)
            if not pipeline:
                available_pipelines = [seq.name for seq in self.pipelines]
                console.print(
                    f"[red]Pipelines '{pipeline_name}' not found. Available pipelines: {available_pipelines}[/red]"
                )
                return
        else:
            pipeline = self.pipelines[0]
            pipeline_name = pipeline.name

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""**Workflow:** {self.name}"""
        if self.description:
            workflow_info += f"""\n\n**Description:** {self.description}"""
        if pipeline.name != "Default Pipeline":
            workflow_info += f"""\n\n**Pipeline:** {pipeline.name}"""
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
                    pipeline_name=pipeline_name,
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

    def _prepare_primary_input(
        self, message: Optional[str], message_data: Optional[Union[BaseModel, Dict[str, Any]]]
    ) -> Optional[str]:
        """Prepare the primary input by combining message and message_data"""

        # Convert message_data to string if provided
        data_str = None
        if message_data is not None:
            if isinstance(message_data, BaseModel):
                data_str = message_data.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(message_data, dict):
                import json

                data_str = json.dumps(message_data, indent=2, default=str)
            else:
                data_str = str(message_data)

        # Combine message and data
        if message and data_str:
            return f"{message}\n\n--- Structured Data ---\n{data_str}"
        elif message:
            return message
        elif data_str:
            return f"Process the following data:\n{data_str}"
        else:
            return None

    def _update_executor_workflow_session_state(self, executor) -> None:
        """Update executor with workflow_session_state"""
        if self.workflow_session_state is not None:
            log_debug(f"Updating executor {type(executor).__name__} with workflow session state")
            log_debug(f"Session state keys: {list(self.workflow_session_state.keys())}")

            # Initialize session_state if it doesn't exist
            if not hasattr(executor, "workflow_session_state") or executor.workflow_session_state is None:
                executor.workflow_session_state = {}
                log_debug("Initialized empty workflow_session_state for executor")

            # Update session_state with workflow_session_state
            from agno.utils.merge_dict import merge_dictionaries

            merge_dictionaries(executor.workflow_session_state, self.workflow_session_state)
            log_debug(f"Merged workflow session state into executor")

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
                log_debug(f"Collecting state from task: {task.name}")
                executor = task._active_executor
                if hasattr(executor, "workflow_session_state") and executor.workflow_session_state:
                    log_debug(
                        f"Found session state in {type(executor).__name__}: {list(executor.workflow_session_state.keys())}"
                    )
                    # Merge the agent's session state back into workflow session state
                    from agno.utils.merge_dict import merge_dictionaries

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
