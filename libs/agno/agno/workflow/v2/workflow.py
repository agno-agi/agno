from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union
from typing import Sequence as TypingSequence
from uuid import uuid4

from pydantic import BaseModel

from agno.media import Audio, Image, Video
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
from agno.utils.log import log_debug, log_info, logger
from agno.workflow.v2.pipeline import Pipeline
from agno.workflow.v2.task import Task
from agno.workflow.v2.trigger import ManualTrigger, Trigger, TriggerType


@dataclass
class Workflow:
    """Workflow 2.0 - Pipeline-based workflow execution"""

    # Workflow identification - make name optional with default
    name: Optional[str] = None
    workflow_id: Optional[str] = None
    description: Optional[str] = None

    # Workflow configuration
    trigger: Trigger = field(default_factory=ManualTrigger)
    pipelines: List[Pipeline] = field(default_factory=list)
    tasks: Optional[List[Task]] = field(default_factory=list)
    storage: Optional[Storage] = None

    # Session management
    session_id: Optional[str] = None
    workflow_session_id: Optional[str] = None
    user_id: Optional[str] = None

    # Runtime state
    run_id: Optional[str] = None

    # Workflow session for storage
    workflow_session: Optional[WorkflowSessionV2] = None

    def __post_init__(self):
        # Handle inheritance - get name from class attribute if not provided
        if self.name is None:
            self.name = getattr(self.__class__, "name", self.__class__.__name__)

        # Handle other class attributes
        if hasattr(self.__class__, "description") and self.description is None:
            self.description = getattr(self.__class__, "description", None)

        # Handle trigger from class attribute
        if hasattr(self.__class__, "trigger"):
            class_trigger = getattr(self.__class__, "trigger")
            if isinstance(class_trigger, Trigger):
                self.trigger = class_trigger

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

    def _auto_create_pipeline_from_tasks(self):
        """Auto-create a pipeline from tasks for manual triggers"""
        # Only auto-create for manual triggers and when tasks are provided but no pipelines
        if self.trigger.trigger_type == TriggerType.MANUAL and self.tasks and not self.pipelines:
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

    def execute_pipeline(self, pipeline_name: str, inputs: Dict[str, Any]) -> WorkflowRunResponse:
        """Execute a specific pipeline by name synchronously"""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")

        # Initialize execution
        self.run_id = str(uuid4())
        execution_start = datetime.now()

        log_debug(f"Starting workflow execution: {self.run_id}")

        # Create WorkflowRunResponse object to pass down (instead of context dict)
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            pipeline_name=pipeline_name,
            event=WorkflowRunEvent.workflow_started,
            created_at=int(execution_start.timestamp()),
        )

        # Update agents and teams with workflow session info
        self.update_agents_and_teams_session_info()

        try:
            # Execute the pipeline synchronously - pass WorkflowRunResponse instead of context
            final_response = pipeline.execute(inputs, workflow_run_response, stream=False)

            # Store the completed workflow response
            if self.workflow_session:
                self.workflow_session.add_run(final_response)

            # Save to storage after complete execution
            self.write_to_storage()

            return final_response

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            error_response = WorkflowRunResponse(
                event=WorkflowRunEvent.workflow_error,
                content=f"Workflow execution failed: {e}",
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline_name,
                run_id=self.run_id or "",
                session_id=self.session_id,
            )

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(error_response)
            self.write_to_storage()

            return error_response

    def execute_pipeline_stream(
        self,
        pipeline_name: str,
        inputs: Dict[str, Any],
        stream_intermediate_steps: bool = False,
        workflow_run_response: WorkflowRunResponse = None,
    ) -> Iterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")

        log_debug(f"Starting workflow execution with streaming: {self.run_id}")

        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            pipeline_name=pipeline_name,
            event=WorkflowRunEvent.workflow_started,
            created_at=int(datetime.now().timestamp()),
        )

        # Update agents and teams with workflow session info
        self.update_agents_and_teams_session_info()

        try:
            # Execute the pipeline with streaming and yield all events
            for event in pipeline._execute_stream(inputs, workflow_run_response, stream_intermediate_steps):
                # Store completed workflow response when we get the final event
                if isinstance(event, WorkflowCompletedEvent):
                    # Update the workflow_run_response with final data
                    workflow_run_response.content = event.content
                    workflow_run_response.task_responses = event.task_responses
                    workflow_run_response.extra_data = event.extra_data
                    workflow_run_response.event = WorkflowRunEvent.workflow_completed

                    # Store the completed workflow response
                    if self.workflow_session:
                        self.workflow_session.add_run(workflow_run_response)

                    # Save to storage after complete execution
                    self.write_to_storage()

                yield event

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            from agno.run.v2.workflow import WorkflowErrorEvent

            error_event = WorkflowErrorEvent(
                run_id=self.run_id or "",
                content=f"Workflow execution failed: {e}",
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline_name,
                session_id=self.session_id,
                error=str(e),
            )

            # Update workflow_run_response with error
            workflow_run_response.content = error_event.content
            workflow_run_response.event = WorkflowRunEvent.workflow_error

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
            self.write_to_storage()

            yield error_event

    async def aexecute_pipeline(self, pipeline_name: str, inputs: Dict[str, Any]) -> WorkflowRunResponse:
        """Execute a specific pipeline by name synchronously"""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")

        # Initialize execution
        self.run_id = str(uuid4())
        execution_start = datetime.now()

        log_debug(f"Starting workflow execution: {self.run_id}")

        # Create WorkflowRunResponse object to pass down (instead of context dict)
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            pipeline_name=pipeline_name,
            event=WorkflowRunEvent.workflow_started,
            created_at=int(execution_start.timestamp()),
        )

        # Update agents and teams with workflow session info
        self.update_agents_and_teams_session_info()

        try:
            # Execute the pipeline asynchronously - pass WorkflowRunResponse instead of context
            final_response = await pipeline.aexecute(inputs, workflow_run_response, stream=False)

            # Store the completed workflow response
            if self.workflow_session:
                self.workflow_session.add_run(final_response)

            # Save to storage after complete execution
            self.write_to_storage()

            return final_response

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            error_response = WorkflowRunResponse(
                event=WorkflowRunEvent.workflow_error,
                content=f"Workflow execution failed: {e}",
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline_name,
                run_id=self.run_id or "",
                session_id=self.session_id,
            )

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(error_response)
            self.write_to_storage()

            return error_response

    async def aexecute_pipeline_stream(
        self,
        pipeline_name: str,
        inputs: Dict[str, Any],
        stream_intermediate_steps: bool = False,
        workflow_run_response: WorkflowRunResponse = None,
    ) -> AsyncIterator[WorkflowRunResponseEvent]:
        """Execute a specific pipeline by name with event streaming"""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")

        log_debug(f"Starting workflow execution with streaming: {self.run_id}")

        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            pipeline_name=pipeline_name,
            event=WorkflowRunEvent.workflow_started,
            created_at=int(datetime.now().timestamp()),
        )

        # Update agents and teams with workflow session info
        self.update_agents_and_teams_session_info()

        try:
            # Execute the pipeline with streaming and yield all events
            async for event in pipeline._aexecute_stream(inputs, workflow_run_response, stream_intermediate_steps):
                # Store completed workflow response when we get the final event
                if isinstance(event, WorkflowCompletedEvent):
                    # Update the workflow_run_response with final data
                    workflow_run_response.content = event.content
                    workflow_run_response.task_responses = event.task_responses
                    workflow_run_response.extra_data = event.extra_data
                    workflow_run_response.event = WorkflowRunEvent.workflow_completed

                    # Store the completed workflow response
                    if self.workflow_session:
                        self.workflow_session.add_run(workflow_run_response)

                    # Save to storage after complete execution
                    self.write_to_storage()

                yield event

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            from agno.run.v2.workflow import WorkflowErrorEvent

            error_event = WorkflowErrorEvent(
                run_id=self.run_id or "",
                content=f"Workflow execution failed: {e}",
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline_name,
                session_id=self.session_id,
                error=str(e),
            )

            # Update workflow_run_response with error
            workflow_run_response.content = error_event.content
            workflow_run_response.event = WorkflowRunEvent.workflow_error

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(workflow_run_response)
            self.write_to_storage()

            yield error_event

    def update_agents_and_teams_session_info(self):
        """Update agents and teams with workflow session information"""
        # Update all agents in pipelines
        for pipeline in self.pipelines:
            for task in pipeline.tasks:
                active_executor = task._active_executor

                if hasattr(active_executor, "workflow_session_id"):
                    active_executor.workflow_session_id = self.session_id
                if hasattr(active_executor, "workflow_id"):
                    active_executor.workflow_id = self.workflow_id

                # If it's a team, update all members
                if hasattr(active_executor, "members"):
                    for member in active_executor.members:
                        if hasattr(member, "workflow_session_id"):
                            member.workflow_session_id = self.session_id
                        if hasattr(member, "workflow_id"):
                            member.workflow_id = self.workflow_id

    def run(
        self,
        query: str = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[Union[WorkflowRunResponse, WorkflowRunResponseEvent]]:
        """Execute the workflow synchronously with optional streaming"""
        if stream:
            return self._run_stream(
                query=query,
                pipeline_name=pipeline_name,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                stream_intermediate_steps=stream_intermediate_steps,
            )
        else:
            return self._run(
                query=query,
                pipeline_name=pipeline_name,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
            )

    def _run(
        self,
        query: str = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
    ) -> WorkflowRunResponse:
        """Execute the workflow synchronously (non-streaming) - returns WorkflowRunResponse directly"""
        # Set user_id and session_id if provided
        if user_id is not None:
            self.user_id = user_id
        if session_id is not None:
            self.session_id = session_id

        # Load or create session
        self.load_session()

        # Determine pipeline based on trigger type and parameters
        if self.trigger.trigger_type == TriggerType.MANUAL:
            if not self.pipelines:
                raise ValueError("No pipelines available in this workflow")

            # If pipeline_name is provided, use that specific pipeline
            if pipeline_name:
                target_pipeline = self.get_pipeline(pipeline_name)
                if not target_pipeline:
                    available_pipelines = [seq.name for seq in self.pipelines]
                    raise ValueError(
                        f"Pipeline '{pipeline_name}' not found. Available pipelines: {available_pipelines}"
                    )
                selected_pipeline_name = pipeline_name
            else:
                # Default to first pipeline if no pipeline_name specified
                selected_pipeline_name = self.pipelines[0].name
        else:
            raise ValueError(
                f"Pipeline selection for trigger type '{self.trigger.trigger_type.value}' not yet implemented"
            )

        # Prepare inputs with media support
        inputs = {}

        # Primary input (query)
        primary_input = query
        if primary_input is not None:
            inputs["query"] = primary_input

        # Add media inputs
        if audio is not None:
            inputs["audio"] = list(audio)
        if images is not None:
            inputs["images"] = list(images)
        if videos is not None:
            inputs["videos"] = list(videos)

        # Execute the pipeline synchronously (non-streaming) - now returns WorkflowRunResponse directly
        return self.execute_pipeline(selected_pipeline_name, inputs)

    def _run_stream(
        self,
        query: str = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[WorkflowRunResponseEvent]:
        """Execute the workflow synchronously with event-driven streaming"""
        # Set user_id and session_id if provided
        if user_id is not None:
            self.user_id = user_id
        if session_id is not None:
            self.session_id = session_id

        # Load or create session
        self.load_session()

        # Initialize execution
        self.run_id = str(uuid4())
        execution_start = datetime.now()

        # Create workflow run response that will be updated by reference
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            created_at=int(execution_start.timestamp()),
        )

        # Determine pipeline based on trigger type and parameters
        if self.trigger.trigger_type == TriggerType.MANUAL:
            if not self.pipelines:
                raise ValueError("No pipelines available in this workflow")

            # If pipeline_name is provided, use that specific pipeline
            if pipeline_name:
                target_pipeline = self.get_pipeline(pipeline_name)
                if not target_pipeline:
                    available_pipelines = [seq.name for seq in self.pipelines]
                    raise ValueError(
                        f"Pipeline '{pipeline_name}' not found. Available pipelines: {available_pipelines}"
                    )
                selected_pipeline_name = pipeline_name
            else:
                # Default to first pipeline if no pipeline_name specified
                selected_pipeline_name = self.pipelines[0].name
        else:
            raise ValueError(
                f"Pipeline selection for trigger type '{self.trigger.trigger_type.value}' not yet implemented"
            )

        # Prepare inputs with media support
        inputs = {}

        # Primary input (query)
        primary_input = query
        if primary_input is not None:
            inputs["query"] = primary_input

        # Add media inputs
        if audio is not None:
            inputs["audio"] = list(audio)
        if images is not None:
            inputs["images"] = list(images)
        if videos is not None:
            inputs["videos"] = list(videos)

        # Execute the selected pipeline with event streaming
        yield from self.execute_pipeline_stream(
            pipeline_name=selected_pipeline_name,
            inputs=inputs,
            workflow_run_response=workflow_run_response,
            stream_intermediate_steps=stream_intermediate_steps,
        )

    async def arun(
        self,
        query: str = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[Union[WorkflowRunResponse, WorkflowRunResponseEvent]]:
        """Execute the workflow synchronously with optional streaming"""
        if stream:
            response_iterator = self._arun_stream(
                query=query,
                pipeline_name=pipeline_name,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
                stream_intermediate_steps=stream_intermediate_steps,
            )
            return response_iterator
        else:
            return await self._arun(
                query=query,
                pipeline_name=pipeline_name,
                user_id=user_id,
                session_id=session_id,
                audio=audio,
                images=images,
                videos=videos,
            )

    async def _arun(
        self,
        query: str = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
    ) -> WorkflowRunResponse:
        """Execute the workflow synchronously (non-streaming) - returns WorkflowRunResponse directly"""
        # Set user_id and session_id if provided
        if user_id is not None:
            self.user_id = user_id
        if session_id is not None:
            self.session_id = session_id

        # Load or create session
        self.load_session()

        # Determine pipeline based on trigger type and parameters
        if self.trigger.trigger_type == TriggerType.MANUAL:
            if not self.pipelines:
                raise ValueError("No pipelines available in this workflow")

            # If pipeline_name is provided, use that specific pipeline
            if pipeline_name:
                target_pipeline = self.get_pipeline(pipeline_name)
                if not target_pipeline:
                    available_pipelines = [seq.name for seq in self.pipelines]
                    raise ValueError(
                        f"Pipeline '{pipeline_name}' not found. Available pipelines: {available_pipelines}"
                    )
                selected_pipeline_name = pipeline_name
            else:
                # Default to first pipeline if no pipeline_name specified
                selected_pipeline_name = self.pipelines[0].name
        else:
            raise ValueError(
                f"Pipeline selection for trigger type '{self.trigger.trigger_type.value}' not yet implemented"
            )

        # Prepare inputs with media support
        inputs = {}

        # Primary input (query)
        primary_input = query
        if primary_input is not None:
            inputs["query"] = primary_input

        # Add media inputs
        if audio is not None:
            inputs["audio"] = list(audio)
        if images is not None:
            inputs["images"] = list(images)
        if videos is not None:
            inputs["videos"] = list(videos)

        # Execute the pipeline synchronously (non-streaming) - now returns WorkflowRunResponse directly
        return await self.aexecute_pipeline(selected_pipeline_name, inputs)

    async def _arun_stream(
        self,
        query: str = None,
        pipeline_name: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[WorkflowRunResponseEvent]:
        """Execute the workflow synchronously with event-driven streaming"""
        # Set user_id and session_id if provided
        if user_id is not None:
            self.user_id = user_id
        if session_id is not None:
            self.session_id = session_id

        # Load or create session
        self.load_session()

        # Initialize execution
        self.run_id = str(uuid4())
        execution_start = datetime.now()

        # Create workflow run response that will be updated by reference
        workflow_run_response = WorkflowRunResponse(
            run_id=self.run_id,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            workflow_name=self.name,
            created_at=int(execution_start.timestamp()),
        )

        # Determine pipeline based on trigger type and parameters
        if self.trigger.trigger_type == TriggerType.MANUAL:
            if not self.pipelines:
                raise ValueError("No pipelines available in this workflow")

            # If pipeline_name is provided, use that specific pipeline
            if pipeline_name:
                target_pipeline = self.get_pipeline(pipeline_name)
                if not target_pipeline:
                    available_pipelines = [seq.name for seq in self.pipelines]
                    raise ValueError(
                        f"Pipeline '{pipeline_name}' not found. Available pipelines: {available_pipelines}"
                    )
                selected_pipeline_name = pipeline_name
            else:
                # Default to first pipeline if no pipeline_name specified
                selected_pipeline_name = self.pipelines[0].name
        else:
            raise ValueError(
                f"Pipeline selection for trigger type '{self.trigger.trigger_type.value}' not yet implemented"
            )

        # Prepare inputs with media support
        inputs = {}

        # Primary input (query)
        primary_input = query
        if primary_input is not None:
            inputs["query"] = primary_input

        # Add media inputs
        if audio is not None:
            inputs["audio"] = list(audio)
        if images is not None:
            inputs["images"] = list(images)
        if videos is not None:
            inputs["videos"] = list(videos)

        # Execute the selected pipeline with event streaming
        async for event in self.aexecute_pipeline_stream(
            pipeline_name=selected_pipeline_name,
            inputs=inputs,
            workflow_run_response=workflow_run_response,
            stream_intermediate_steps=stream_intermediate_steps,
        ):
            yield event

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
                "trigger": self.trigger.trigger_type.value,
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
        if self.workflow_session is not None and not force:
            if self.session_id is not None and self.workflow_session.session_id == self.session_id:
                return self.workflow_session.session_id

        if self.storage is not None:
            # Try to load existing session
            log_debug(f"Reading WorkflowSessionV2: {self.session_id}")
            existing_session = self.read_from_storage()

            # Create new session if it doesn't exist
            if existing_session is None:
                log_debug("Creating new WorkflowSessionV2")
                self.workflow_session = WorkflowSessionV2(
                    session_id=self.session_id,
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
        self.workflow_session = None
        self.session_id = str(uuid4())
        self.load_session(force=True)

    def print_response(
        self,
        query: Optional[str] = None,
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
            query: The main query/input for the workflow
            stream: Whether to stream the response content
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_task_details: Whether to show individual task outputs
            console: Rich console instance (optional)
        """
        if stream:
            self._print_response_stream(
                query=query,
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
                query=query,
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
        query: str,
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

        # Process message_data and combine with query
        primary_input = self._prepare_primary_input(query, message_data)

        if primary_input is None:
            console.print("[red]Query must be provided[/red]")
            return

        # Validate pipeline configuration based on trigger type
        if self.trigger.trigger_type == TriggerType.MANUAL:
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
        else:
            # For other trigger types, we'll implement pipeline selection logic later
            console.print(
                f"[yellow]Trigger type '{self.trigger.trigger_type.value}' not yet supported in print_response[/yellow]"
            )
            return

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""
            **Workflow:** {self.name}
            **Pipeline:** {pipeline.name}
            **Description:** {pipeline.description or "No description"}
            **Tasks:** {len(pipeline.tasks)} tasks
            **Available pipelines:** {", ".join([seq.name for seq in self.pipelines])}
            **Query:** {primary_input}{media_str}
            **User ID:** {user_id or self.user_id or "Not set"}
            **Session ID:** {session_id or self.session_id}
            **Streaming:** Disabled
            """.strip()

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
                workflow_response: WorkflowRunResponse = self._run(
                    query=primary_input,
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
                    final_output = workflow_response.extra_data
                    summary_content = f"""
                        **Pipeline:** {pipeline_name}
                        **Status:** {final_output.get("status", "Completed")}
                        **Tasks Completed:** {len(workflow_response.task_responses) if workflow_response.task_responses else 0}
                    """.strip()

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
        query: str,
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

        # Process message_data and combine with query
        primary_input = self._prepare_primary_input(query, message_data)

        if primary_input is None:
            console.print("[red]Query must be provided[/red]")
            return

        if self.trigger.trigger_type == TriggerType.MANUAL:
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
        else:
            console.print(
                f"[yellow]Trigger type '{self.trigger.trigger_type.value}' not yet supported in streaming[/yellow]"
            )
            return

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""
            **Workflow:** {self.name}
            **Pipeline:** {pipeline.name}
            **Description:** {pipeline.description or "No description"}
            **Tasks:** {len(pipeline.tasks)} tasks
            **Query:** {primary_input}{media_str}
            **User ID:** {user_id or self.user_id or "Not set"}
            **Session ID:** {session_id or self.session_id}
            **Streaming:** Enabled
            """.strip()

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
        current_task_panel = None

        with Live(console=console, refresh_per_second=10) as live_log:
            status = Status("Starting workflow...", spinner="dots")
            live_log.update(status)

            try:
                for response in self._run_stream(
                    query=primary_input,
                    pipeline_name=pipeline_name,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
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
                            final_output = response.extra_data
                            summary_content = f"""
                                **Pipeline:** {pipeline_name}
                                **Status:** {final_output.get("status", "Unknown")}
                                **Tasks Completed:** {len(response.task_responses) if response.task_responses else 0}
                            """.strip()

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

    async def aprint_response(
        self,
        query: Optional[str] = None,
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
            query: The main query/input for the workflow
            stream: Whether to stream the response content
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_task_details: Whether to show individual task outputs
            console: Rich console instance (optional)
        """
        if stream:
            await self._aprint_response_stream(
                query=query,
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
                query=query,
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
        query: str,
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

        # Process message_data and combine with query
        primary_input = self._prepare_primary_input(query, message_data)

        if primary_input is None:
            console.print("[red]Query must be provided[/red]")
            return

        # Validate pipeline configuration based on trigger type
        if self.trigger.trigger_type == TriggerType.MANUAL:
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
        else:
            # For other trigger types, we'll implement pipeline selection logic later
            console.print(
                f"[yellow]Trigger type '{self.trigger.trigger_type.value}' not yet supported in print_response[/yellow]"
            )
            return

        # Show workflow info
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""
            **Workflow:** {self.name}
            **Pipeline:** {pipeline.name}
            **Description:** {pipeline.description or "No description"}
            **Tasks:** {len(pipeline.tasks)} tasks
            **Available pipelines:** {", ".join([seq.name for seq in self.pipelines])}
            **Query:** {primary_input}{media_str}
            **User ID:** {user_id or self.user_id or "Not set"}
            **Session ID:** {session_id or self.session_id}
            **Streaming:** Disabled (Async)
            """.strip()

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
            status = Status("Starting async workflow...", spinner="dots")
            live_log.update(status)

            try:
                # Execute workflow and get the response directly
                workflow_response: WorkflowRunResponse = await self._arun(
                    query=primary_input,
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
                    final_output = workflow_response.extra_data
                    summary_content = f"""
                        **Pipeline:** {pipeline_name}
                        **Status:** {final_output.get("status", "Completed")}
                        **Tasks Completed:** {len(workflow_response.task_responses) if workflow_response.task_responses else 0}
                    """.strip()

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
        query: str,
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

        # Process message_data and combine with query
        primary_input = self._prepare_primary_input(query, message_data)

        if primary_input is None:
            console.print("[red]Query must be provided[/red]")
            return

        if self.trigger.trigger_type == TriggerType.MANUAL:
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
        else:
            console.print(
                f"[yellow]Trigger type '{self.trigger.trigger_type.value}' not yet supported in streaming[/yellow]"
            )
            return

        # Show workflow info (same as before)
        media_info = []
        if audio:
            media_info.append(f"Audio files: {len(audio)}")
        if images:
            media_info.append(f"Images: {len(images)}")
        if videos:
            media_info.append(f"Videos: {len(videos)}")

        media_str = f" | {' | '.join(media_info)}" if media_info else ""

        workflow_info = f"""
            **Workflow:** {self.name}
            **Pipeline:** {pipeline.name}
            **Description:** {pipeline.description or "No description"}
            **Tasks:** {len(pipeline.tasks)} tasks
            **Query:** {primary_input}{media_str}
            **User ID:** {user_id or self.user_id or "Not set"}
            **Session ID:** {session_id or self.session_id}
            **Streaming:** Enabled (Async)
            """.strip()

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
                async for response in self._arun_stream(
                    query=primary_input,
                    pipeline_name=pipeline_name,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
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
                            final_output = response.extra_data
                            summary_content = f"""
                                **Pipeline:** {pipeline_name}
                                **Status:** {final_output.get("status", "Unknown")}
                                **Tasks Completed:** {len(response.task_responses) if response.task_responses else 0}
                            """.strip()

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
            "trigger": {"trigger_type": self.trigger.trigger_type.value, "config": self.trigger.__dict__},
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
        self, query: Optional[str], message_data: Optional[Union[BaseModel, Dict[str, Any]]]
    ) -> Optional[str]:
        """Prepare the primary input by combining query and message_data"""

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

        # Combine query and data
        if query and data_str:
            return f"{query}\n\n--- Structured Data ---\n{data_str}"
        elif query:
            return query
        elif data_str:
            return f"Process the following data:\n{data_str}"
        else:
            return None
