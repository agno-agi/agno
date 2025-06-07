from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Sequence as TypingSequence
from uuid import uuid4

from agno.media import Audio, Image, Video
from agno.run.workflow import WorkflowRunEvent, WorkflowRunResponse
from agno.storage.base import Storage
from agno.storage.session.workflow import WorkflowSessionV2
from agno.utils.log import log_debug, logger
from agno.workflow.v2.sequence import Sequence
from agno.workflow.v2.trigger import ManualTrigger, Trigger, TriggerType


@dataclass
class Workflow:
    """Workflow 2.0 - Sequence-based workflow execution"""

    # Workflow identification - make name optional with default
    name: Optional[str] = None
    workflow_id: Optional[str] = None
    description: Optional[str] = None
    version: str = "2.0"

    # Workflow configuration
    trigger: Trigger = field(default_factory=ManualTrigger)
    sequences: List[Sequence] = field(default_factory=list)
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

        if hasattr(self.__class__, "sequences") and not self.sequences:
            class_sequences = getattr(self.__class__, "sequences", [])
            if class_sequences:
                self.sequences = class_sequences.copy()

        if self.workflow_id is None:
            self.workflow_id = str(uuid4())

        if self.session_id is None:
            self.session_id = str(uuid4())

        # Set storage mode to workflow_v2
        self.set_storage_mode()

    def set_storage_mode(self):
        """Set storage mode to workflow_v2"""
        if self.storage is not None:
            self.storage.mode = "workflow_v2"

    def execute_sequence(self, sequence_name: str, inputs: Dict[str, Any]) -> Iterator[WorkflowRunResponse]:
        """Execute a specific sequence by name synchronously"""
        sequence = self.get_sequence(sequence_name)
        if not sequence:
            raise ValueError(f"Sequence '{sequence_name}' not found")

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
            # Execute the sequence synchronously
            for response in sequence.execute(inputs, context):
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
            logger.error(f"Workflow execution failed: {e}")

            error_response = WorkflowRunResponse(
                content=f"Workflow execution failed: {e}",
                event=WorkflowRunEvent.workflow_error,
                workflow_id=self.workflow_id,
                workflow_name=self.name,
                sequence_name=sequence_name,
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
        # Update all agents in sequences
        for sequence in self.sequences:
            for task in sequence.tasks:
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
        sequence_name: Optional[str] = None,
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

        # Determine sequence based on trigger type and parameters
        if self.trigger.trigger_type == TriggerType.MANUAL:
            if not self.sequences:
                raise ValueError("No sequences available in this workflow")

            # If sequence_name is provided, use that specific sequence
            if sequence_name:
                target_sequence = self.get_sequence(sequence_name)
                if not target_sequence:
                    available_sequences = [seq.name for seq in self.sequences]
                    raise ValueError(
                        f"Sequence '{sequence_name}' not found. Available sequences: {available_sequences}"
                    )
                selected_sequence_name = sequence_name
            else:
                # Default to first sequence if no sequence_name specified
                selected_sequence_name = self.sequences[0].name
        else:
            raise ValueError(
                f"Sequence selection for trigger type '{self.trigger.trigger_type.value}' not yet implemented"
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
            
        # Execute the selected sequence synchronously
        for response in self.execute_sequence(selected_sequence_name, inputs):
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
                "version": self.version,
                "trigger": self.trigger.trigger_type.value,
                "sequences": [
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
                    for seq in self.sequences
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
        query: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[TypingSequence[Audio]] = None,
        images: Optional[TypingSequence[Image]] = None,
        videos: Optional[TypingSequence[Video]] = None,
        sequence_name: Optional[str] = None,
        markdown: bool = True,
        show_time: bool = True,
        show_task_details: bool = True,
        console: Optional[Any] = None,
    ) -> None:
        """Print workflow execution with rich formatting

        Args:
            query: The main query/input for the workflow
            sequence_name: Name of the sequence to execute (defaults to first sequence)
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

        # Use query or message as primary input
        primary_input = query
        if primary_input is None:
            console.print("[red]Either 'query' or 'message' must be provided[/red]")
            return

        # Validate sequence configuration based on trigger type
        if self.trigger.trigger_type == TriggerType.MANUAL:
            if not self.sequences:
                console.print("[red]No sequences available in this workflow[/red]")
                return

            # Determine which sequence to use
            if sequence_name:
                sequence = self.get_sequence(sequence_name)
                if not sequence:
                    available_sequences = [seq.name for seq in self.sequences]
                    console.print(
                        f"[red]Sequence '{sequence_name}' not found. Available sequences: {available_sequences}[/red]"
                    )
                    return
            else:
                # Default to first sequence
                sequence = self.sequences[0]
                sequence_name = sequence.name
        else:
            # For other trigger types, we'll implement sequence selection logic later
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
            **Sequence:** {sequence.name}
            **Description:** {sequence.description or "No description"}
            **Tasks:** {len(sequence.tasks)} tasks
            **Available Sequences:** {", ".join([seq.name for seq in self.sequences])}
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
                    query=query,
                    sequence_name=sequence_name,
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
                                **Sequence:** {sequence_name}
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

    def add_sequence(self, sequence: Sequence) -> None:
        """Add a sequence to the workflow"""
        self.sequences.append(sequence)

    def remove_sequences(self, sequence_name: str) -> bool:
        """Remove a sequence by name"""
        for i, sequence in enumerate(self.sequences):
            if sequence.name == sequence_name:
                del self.sequences[i]
                return True
        return False

    def get_sequence(self, sequence_name: str) -> Optional[Sequence]:
        """Get a sequence by name"""
        for sequence in self.sequences:
            if sequence.name == sequence_name:
                return sequence
        return None

    def list_sequences(self) -> List[str]:
        """List all sequence names"""
        return [sequence.name for sequence in self.sequences]

    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary representation"""
        return {
            "name": self.name,
            "workflow_id": self.workflow_id,
            "description": self.description,
            "version": self.version,
            "trigger": {"trigger_type": self.trigger.trigger_type.value, "config": self.trigger.__dict__},
            "sequences": [
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
                for p in self.sequences
            ],
            "session_id": self.session_id,
        }
