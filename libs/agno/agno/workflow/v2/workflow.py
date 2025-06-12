from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union
from typing import Sequence as TypingSequence
from uuid import uuid4

from pydantic import BaseModel

from agno.media import Audio, Image, Video
from agno.run.v2.workflow import (
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowRunEvent,
    WorkflowRunResponse,
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

    def execute_pipeline(self, pipeline_name: str, inputs: Dict[str, Any]) -> Iterator[WorkflowRunResponse]:
        """Execute a specific pipeline by name synchronously"""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")

        # Initialize execution
        self.run_id = str(uuid4())
        execution_start = datetime.now()

        log_debug(f"Starting workflow execution: {self.run_id}")

        # Create execution context
        context = {
            "workflow_id": self.workflow_id,
            "workflow_name": self.name,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "execution_start": execution_start,
        }

        # Update agents and teams with workflow session info
        self.update_agents_and_teams_session_info()

        # Collect complete workflow run instead of individual events
        workflow_run_responses = []

        try:
            # Execute the pipeline synchronously
            for response in pipeline.execute(inputs, context):
                # Collect all responses
                workflow_run_responses.append(response)
                yield response

            # Store only the complete workflow run (not individual events)
            if self.workflow_session and workflow_run_responses:
                # Store only the final completed workflow response
                final_response = workflow_run_responses[-1]
                if isinstance(final_response, WorkflowCompletedEvent):
                    # Convert to WorkflowRunResponse for storage compatibility
                    storage_response = WorkflowRunResponse(
                        event=final_response.event,
                        content=final_response.content,
                        workflow_id=final_response.workflow_id,
                        workflow_name=final_response.workflow_name,
                        pipeline_name=final_response.pipeline_name,
                        run_id=final_response.run_id,
                        session_id=final_response.session_id,
                        task_responses=final_response.task_responses,
                        extra_data=final_response.extra_data,
                        created_at=final_response.created_at,
                    )
                    self.workflow_session.add_run(storage_response)

            # Save to storage after complete execution
            self.write_to_storage()

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")

            error_response = WorkflowErrorEvent(
                run_id=self.run_id or "",
                content=f"Workflow execution failed: {e}",
                error=str(e),
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline_name,
                session_id=self.session_id,
            )

            # Store error response (convert to WorkflowRunResponse for storage)
            if self.workflow_session:
                storage_response = WorkflowRunResponse(
                    event=error_response.event,
                    content=error_response.content,
                    workflow_id=error_response.workflow_id,
                    workflow_name=error_response.workflow_name,
                    pipeline_name=error_response.pipeline_name,
                    run_id=error_response.run_id,
                    session_id=error_response.session_id,
                    created_at=error_response.created_at,
                )
                self.workflow_session.add_run(storage_response)
            self.write_to_storage()

            yield error_response

    async def aexecute_pipeline(self, pipeline_name: str, inputs: Dict[str, Any]) -> AsyncIterator[WorkflowRunResponse]:
        """Execute a specific pipeline by name asynchronously"""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")

        # Initialize execution
        self.run_id = str(uuid4())
        execution_start = datetime.now()

        log_debug(f"Starting async workflow execution: {self.run_id}")

        # Create execution context
        context = {
            "workflow_id": self.workflow_id,
            "workflow_name": self.name,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "execution_start": execution_start,
        }

        # Update agents and teams with workflow session info
        self.update_agents_and_teams_session_info()

        # Collect complete workflow run instead of individual events
        workflow_run_responses = []

        try:
            # Execute the pipeline asynchronously
            async for response in pipeline.aexecute(inputs, context):
                # Collect all responses
                workflow_run_responses.append(response)
                yield response

            # Store only the complete workflow run (not individual events)
            if self.workflow_session and workflow_run_responses:
                # Store only the final completed workflow response
                # The workflow_completed event
                final_response = workflow_run_responses[-1]
                if final_response.event == WorkflowRunEvent.workflow_completed:
                    self.workflow_session.add_run(final_response)

            # Save to storage after complete execution
            self.write_to_storage()

        except Exception as e:
            logger.error(f"Async workflow execution failed: {e}")

            error_response = WorkflowRunResponse(
                content=f"Workflow execution failed: {e}",
                event=WorkflowRunEvent.workflow_error,
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                pipeline_name=pipeline_name,
                session_id=self.session_id,
                run_id=self.run_id,
            )

            # Store error response
            if self.workflow_session:
                self.workflow_session.add_run(error_response)
            self.write_to_storage()

            yield error_response

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
    ) -> Iterator[WorkflowRunResponse]:
        """Execute the workflow synchronously"""
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

        # Execute the selected pipeline synchronously
        for response in self.execute_pipeline(selected_pipeline_name, inputs):
            yield response

    async def arun(
        self,
        query: Optional[str] = None,
        message: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
    ) -> AsyncIterator[WorkflowRunResponse]:
        """Execute the workflow asynchronously"""
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

        # Primary input (query or message)
        primary_input = query or message
        if primary_input is not None:
            inputs["query"] = primary_input
            inputs["message"] = primary_input

        # Add media inputs
        if audio is not None:
            inputs["audio"] = list(audio)
        if images is not None:
            inputs["images"] = list(images)
        if videos is not None:
            inputs["videos"] = list(videos)

        # Execute the selected pipeline asynchronously
        async for response in self.aexecute_pipeline(selected_pipeline_name, inputs):
            yield response

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
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with rich formatting

        Args:
            query: The main query/input for the workflow
            pipeline_name: Name of the pipeline to execute (defaults to first pipeline)
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_task_details: Whether to show individual task outputs
            console: Rich console instance (optional)
        """
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
            console.print("[red]Either 'query' or 'message' must be provided[/red]")
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

        # Show workflow info once at the beginning
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
            """.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer before execution
        response_timer = Timer()
        response_timer.start()

        # Execute and show results
        task_responses = []

        with Live(console=console) as live_log:
            status = Status("Starting workflow...", spinner="dots")
            live_log.update(status)

            try:
                for response in self.run(
                    query=primary_input,
                    pipeline_name=pipeline_name,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                ):
                    if response.event == WorkflowRunEvent.workflow_started:
                        status.update("Workflow started...")

                    elif response.event == WorkflowRunEvent.task_started:
                        task_name = response.task_name or "Unknown"
                        task_index = response.task_index or 0
                        status.update(f"Starting task {task_index + 1}: {task_name}...")

                    elif response.event == WorkflowRunEvent.task_completed:
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

                        # Print the task panel immediately after completion
                        if show_task_details and response.content:
                            task_panel = create_panel(
                                content=Markdown(response.content) if markdown else response.content,
                                title=f"Task {task_index + 1}: {task_name}",
                                border_style="green",
                            )
                            console.print(task_panel)

                    elif response.event == WorkflowRunEvent.workflow_completed:
                        status.update("Workflow completed!")

                        # Show final summary
                        if response.extra_data:
                            final_output = response.extra_data
                            summary_content = f"""
                                **Pipeline:** {pipeline_name}
                                **Status:** {final_output.get("status", "Unknown")}
                                **Tasks Completed:** {len(task_responses)}
                            """.strip()

                            summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title="Execution Summary",
                                border_style="blue",
                            )
                            console.print(summary_panel)

                    elif response.event == WorkflowRunEvent.workflow_error:
                        status.update("Workflow failed!")
                        error_panel = create_panel(content=response.content, title="Error", border_style="red")
                        console.print(error_panel)

                    # Update live display with just status
                    live_log.update(status)

                response_timer.stop()

                # Final completion message with time
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
        message: Optional[str] = None,
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
        """Print workflow execution with rich formatting asynchronously

        Args:
            query: The main query/input for the workflow
            message: Alternative to query (same as query)
            pipeline_name: Name of the pipeline to execute (defaults to first pipeline)
            user_id: User ID for the workflow execution
            session_id: Session ID for the workflow execution
            audio: Audio inputs for the workflow
            images: Image inputs for the workflow
            videos: Video inputs for the workflow
            files: File inputs for the workflow
            markdown: Whether to render content as markdown
            show_time: Whether to show execution time
            show_task_details: Whether to show individual task outputs
            console: Rich console instance (optional)
        """
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        from agno.utils.response import create_panel
        from agno.utils.timer import Timer

        self._auto_create_pipeline_from_tasks()

        if console is None:
            from agno.cli.console import console

        pipeline_name = self._auto_create_pipeline_from_tasks()

        # Process message_data and combine with query
        primary_input = self._prepare_primary_input(query, message_data)
        
        if primary_input is None:
            console.print("[red]Either 'query' or 'message' must be provided[/red]")
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
                f"[yellow]Trigger type '{self.trigger.trigger_type.value}' not yet supported in aprint_response[/yellow]"
            )
            return

        # Show workflow info once at the beginning
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
            """.strip()

        workflow_panel = create_panel(
            content=Markdown(workflow_info) if markdown else workflow_info,
            title="Workflow Information",
            border_style="cyan",
        )
        console.print(workflow_panel)

        # Start timer before execution
        response_timer = Timer()
        response_timer.start()

        # Execute and show results
        task_responses = []

        with Live(console=console) as live_log:
            status = Status("Starting workflow...", spinner="dots")
            live_log.update(status)

            try:
                async for response in self.arun(
                    query=primary_input,
                    message=message,
                    pipeline_name=pipeline_name,
                    user_id=user_id,
                    session_id=session_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                ):
                    if response.event == WorkflowRunEvent.workflow_started:
                        status.update("Workflow started...")

                    elif response.event == WorkflowRunEvent.task_started:
                        task_name = response.task_name or "Unknown"
                        task_index = response.task_index or 0
                        status.update(f"Starting task {task_index + 1}: {task_name}...")

                    elif response.event == WorkflowRunEvent.task_completed:
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

                        # Print the task panel immediately after completion
                        if show_task_details and response.content:
                            task_panel = create_panel(
                                content=Markdown(response.content) if markdown else response.content,
                                title=f"Task {task_index + 1}: {task_name}",
                                border_style="green",
                            )
                            console.print(task_panel)

                    elif response.event == WorkflowRunEvent.workflow_completed:
                        status.update("Workflow completed!")

                        # Show final summary
                        if response.extra_data:
                            final_output = response.extra_data
                            summary_content = f"""
                                **Pipeline:** {pipeline_name}
                                **Status:** {final_output.get("status", "Unknown")}
                                **Tasks Completed:** {len(task_responses)}
                            """.strip()

                            summary_panel = create_panel(
                                content=Markdown(summary_content) if markdown else summary_content,
                                title="Execution Summary",
                                border_style="blue",
                            )
                            console.print(summary_panel)

                    elif response.event == WorkflowRunEvent.workflow_error:
                        status.update("Workflow failed!")
                        error_panel = create_panel(content=response.content, title="Error", border_style="red")
                        console.print(error_panel)

                    # Update live display with just status
                    live_log.update(status)

                response_timer.stop()

                # Final completion message with time
                if show_time:
                    completion_text = Text(f"Completed in {response_timer.elapsed:.1f}s", style="bold green")
                    console.print(completion_text)

            except Exception as e:
                response_timer.stop()
                error_panel = create_panel(
                    content=f"Async workflow execution failed: {str(e)}", title="Execution Error", border_style="red"
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
