from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union
from uuid import uuid4

from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.run.workflow import WorkflowRunEvent, WorkflowRunResponse
from agno.utils.log import logger
from agno.workflow.v2.task import Task, TaskInput, TaskOutput


@dataclass
class Sequence:
    """A sequence of tasks that execute in order"""

    # Sequence identification
    name: str
    sequence_id: Optional[str] = None
    description: Optional[str] = None

    # Tasks to execute
    tasks: List[Task] = field(default_factory=list)

    def __post_init__(self):
        if self.sequence_id is None:
            self.sequence_id = str(uuid4())

    def execute(self, inputs: Dict[str, Any], context: Dict[str, Any] = None) -> Iterator[WorkflowRunResponse]:
        """Execute all tasks in the sequence sequentially using TaskInput/TaskOutput"""
        logger.info(f"Starting sequence: {self.name}")

        # Initialize sequence context
        sequence_context = context or {}
        sequence_context["sequence_name"] = self.name
        sequence_context["sequence_id"] = self.sequence_id

        # Track outputs from each task for chaining
        previous_outputs = {}
        collected_task_responses: List[Union[RunResponse, TeamRunResponse]] = []

        # Workflow started event
        yield WorkflowRunResponse(
            content=f"Sequence {self.name} started",
            event=WorkflowRunEvent.workflow_started,
            workflow_name=context.get("workflow_name") if context else None,
            sequence_name=self.name,
            workflow_id=context.get("workflow_id") if context else None,
            run_id=context.get("run_id") if context else None,
            session_id=context.get("session_id") if context else None,
        )

        for i, task in enumerate(self.tasks):
            logger.info(f"Executing task {i + 1}/{len(self.tasks)}: {task.name}")

            # Add task_index to context for the task
            task_context = sequence_context.copy()
            task_context["task_index"] = i

            # Create TaskInput for this task
            task_input = self._create_task_input(inputs, previous_outputs, context)

            # Execute the task
            task_output = None
            for event in task.execute(task_input, task_context):
                if isinstance(event, WorkflowRunResponse):
                    # Forward workflow events (like task_started)
                    yield event
                elif isinstance(event, TaskOutput):
                    # This is the final task output
                    task_output = event
                    break

            if task_output is None:
                raise RuntimeError(f"Task {task.name} did not return a TaskOutput")

            # Collect the actual task response for storage
            if task_output.response:
                collected_task_responses.append(task_output.response)

            # Update previous_outputs for next task
            self._update_previous_outputs(previous_outputs, task, task_output, i)

            # Task completed event
            yield WorkflowRunResponse(
                content=task_output.content,
                event=WorkflowRunEvent.task_completed,
                workflow_name=context.get("workflow_name") if context else None,
                sequence_name=self.name,
                task_name=task.name,
                task_index=i,
                workflow_id=context.get("workflow_id") if context else None,
                run_id=context.get("run_id") if context else None,
                session_id=context.get("session_id") if context else None,
                images=task_output.images,
                videos=task_output.videos,
                audio=task_output.audio,
                messages=getattr(task_output.response, "messages", None) if task_output.response else None,
                metrics=getattr(task_output.response, "metrics", None) if task_output.response else None,
                # Include the actual task response
                task_responses=[task_output.response] if task_output.response else [],
            )

        # Workflow completed event with all task responses
        final_output = {
            "sequence_name": self.name,
            "sequence_id": self.sequence_id,
            "status": "completed",
            "total_tasks": len(self.tasks),
            "task_summary": [
                {
                    "task_name": task.name,
                    "task_id": task.task_id,
                    "description": task.description,
                    "executor_type": task.executor_type,
                    "executor_name": task.executor_name,
                }
                for task in self.tasks
            ],
        }

        yield WorkflowRunResponse(
            content=f"Sequence {self.name} completed successfully",
            event=WorkflowRunEvent.workflow_completed,
            workflow_name=context.get("workflow_name") if context else None,
            sequence_name=self.name,
            workflow_id=context.get("workflow_id") if context else None,
            run_id=context.get("run_id") if context else None,
            session_id=context.get("session_id") if context else None,
            # Include all collected task responses
            task_responses=collected_task_responses,
            extra_data=final_output,
        )

    def _create_task_input(
        self, initial_inputs: Dict[str, Any], previous_outputs: Dict[str, Any], context: Dict[str, Any] = None
    ) -> TaskInput:
        """Create TaskInput for a task"""
        # Get primary query/message
        query = initial_inputs.get("query") or initial_inputs.get("message")

        # Extract media from initial inputs
        images = initial_inputs.get("images")
        videos = initial_inputs.get("videos")
        audio = initial_inputs.get("audio")

        return TaskInput(
            query=query,
            workflow_session_state=context,
            previous_outputs=previous_outputs.copy() if previous_outputs else None,
            images=images,
            videos=videos,
            audio=audio,
        )

    def _update_previous_outputs(
        self, previous_outputs: Dict[str, Any], task: Task, task_output: TaskOutput, task_index: int
    ):
        """Update previous_outputs with the current task's output"""
        if task_output.content:
            # Store output with multiple keys for flexibility
            previous_outputs[task.name] = task_output.content
            previous_outputs[f"{task.name}_output"] = task_output.content
            previous_outputs[f"task_{task_index}_output"] = task_output.content
            previous_outputs["output"] = task_output.content  # Latest output
            # Alias for output
            previous_outputs["result"] = task_output.content

        # Store structured data if available
        if task_output.data:
            previous_outputs[f"{task.name}_data"] = task_output.data
            previous_outputs["data"] = task_output.data  # Latest data

        # Store media outputs
        if task_output.images:
            previous_outputs[f"{task.name}_images"] = task_output.images
            previous_outputs["images"] = task_output.images  # Latest images

        if task_output.videos:
            previous_outputs[f"{task.name}_videos"] = task_output.videos
            previous_outputs["videos"] = task_output.videos  # Latest videos

        if task_output.audio:
            previous_outputs[f"{task.name}_audio"] = task_output.audio
            previous_outputs["audio"] = task_output.audio  # Latest audio

    def add_task(self, task: Task) -> None:
        """Add a task to the sequence"""
        self.tasks.append(task)

    def remove_task(self, task_name: str) -> bool:
        """Remove a task from the sequence by name"""
        for i, task in enumerate(self.tasks):
            if task.name == task_name:
                del self.tasks[i]
                return True
        return False

    def get_task(self, task_name: str) -> Optional[Task]:
        """Get a task by name"""
        for task in self.tasks:
            if task.name == task_name:
                return task
        return None
