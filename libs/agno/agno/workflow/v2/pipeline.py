from dataclasses import dataclass
from typing import AsyncIterator, Iterator, List, Optional
from uuid import uuid4

from agno.run.base import RunStatus
from agno.run.v2.workflow import (
    TaskCompletedEvent,
    TaskStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
)
from agno.utils.log import log_debug, logger
from agno.workflow.v2.task import Task
from agno.workflow.v2.types import TaskInput, TaskOutput, WorkflowExecutionInput


@dataclass
class Pipeline:
    """A pipeline of tasks that execute in order"""

    # Pipeline_name identification
    name: Optional[str] = None
    pipeline_id: Optional[str] = None
    description: Optional[str] = None

    # Tasks to execute
    tasks: Optional[List[Task]] = None

    def __init__(
        self, name: Optional[str] = None, description: Optional[str] = None, tasks: Optional[List[Task]] = None
    ):
        self.name = name
        self.description = description
        self.tasks = tasks if tasks else []

    def initialize(self):
        if self.pipeline_id is None:
            log_debug(f"Initializing pipeline ID for {self.name}")
            self.pipeline_id = str(uuid4())

    def execute(
        self,
        pipeline_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Execute all tasks in the pipeline using TaskInput/TaskOutput (non-streaming)"""
        log_debug(f"Pipeline Execution Start: {self.name}", center=True)
        log_debug(f"Pipeline ID: {self.pipeline_id}")
        log_debug(f"Total tasks: {len(self.tasks)}")

        logger.info(f"Starting pipeline: {self.name}")

        # Update pipeline info in the response
        workflow_run_response.pipeline_name = self.name

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []

        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        previous_task_content = None

        # Execute tasks sequentially
        for i, task in enumerate(self.tasks):
            log_debug(f"Executing task {i + 1}/{len(self.tasks)}: {task.name}")
            log_debug(f"Task ID: {task.task_id}")

            logger.info(f"Executing task {i + 1}/{len(self.tasks)}: {task.name}")

            # Create TaskInput for this task
            log_debug(f"Created TaskInput for task {task.name}")
            task_input = TaskInput(
                message=pipeline_input.message,
                message_data=pipeline_input.message_data,
                previous_task_content=previous_task_content,
                images=pipeline_images,
                videos=pipeline_videos,
                audio=pipeline_audio,
            )

            # Execute the task (non-streaming)
            task_output = task.execute(task_input, session_id=session_id, user_id=user_id)

            # Collect the task output
            if task_output is None:
                raise RuntimeError(f"Task {task.name} did not return a TaskOutput")

            # Update the input for the next task
            previous_task_content = task_output.content
            pipeline_images.extend(task_output.images or [])
            pipeline_videos.extend(task_output.videos or [])
            pipeline_audio.extend(task_output.audio or [])

            # Collect the TaskOutput for storage
            collected_task_outputs.append(task_output)

        # Create final output data
        final_output = {
            "pipeline_id": self.pipeline_id,
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

        log_debug(f"Pipeline Execution End: {self.name}", center=True, symbol="*")

        # Update the workflow_run_response with completion data
        workflow_run_response.content = collected_task_outputs[
            -1
        ].content  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.extra_data = final_output
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.status = RunStatus.completed

    def execute_stream(
        self,
        pipeline_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[WorkflowRunResponseEvent]:
        """Execute the pipeline with event-driven streaming support"""
        log_debug(f"Pipeline Streaming Execution Start: {self.name}", center=True)
        log_debug(f"Pipeline ID: {self.pipeline_id}")
        log_debug(f"Stream intermediate steps: {stream_intermediate_steps}")
        log_debug(f"Total tasks: {len(self.tasks)}")

        logger.info(f"Executing pipeline with streaming: {self.name}")

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []
        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        previous_task_content = None

        # Execute tasks in pipeline with streaming
        for task_index, task in enumerate(self.tasks):
            log_debug(f"Streaming task {task_index + 1}/{len(self.tasks)}: {task.name}")

            # Create TaskInput for this task
            task_input = TaskInput(
                message=pipeline_input.message,
                message_data=pipeline_input.message_data,
                previous_task_content=previous_task_content,
                images=pipeline_images,
                videos=pipeline_videos,
                audio=pipeline_audio,
            )

            # Yield task started event
            yield TaskStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name,
                pipeline_name=workflow_run_response.pipeline_name,
                task_name=task.name,
                task_index=task_index,
                workflow_id=workflow_run_response.workflow_id,
                session_id=workflow_run_response.session_id,
            )

            # Execute task with streaming and yield all events
            for event in task.execute(
                task_input,
                session_id=session_id,
                user_id=user_id,
                stream=True,
                stream_intermediate_steps=stream_intermediate_steps,
            ):
                if isinstance(event, TaskOutput):
                    # This is the final task output
                    task_output = event
                    log_debug(f"Received final TaskOutput from {task.name}")

                    # Collect the task output
                    collected_task_outputs.append(task_output)

                    pipeline_images.extend(task_output.images or [])
                    pipeline_videos.extend(task_output.videos or [])
                    pipeline_audio.extend(task_output.audio or [])
                    previous_task_content = task_output.content

                    # Yield task completed event
                    yield TaskCompletedEvent(
                        run_id=workflow_run_response.run_id or "",
                        content=task_output.content,
                        workflow_name=workflow_run_response.workflow_name,
                        pipeline_name=self.name,
                        task_name=task.name,
                        task_index=task_index,
                        workflow_id=workflow_run_response.workflow_id,
                        session_id=workflow_run_response.session_id,
                        images=task_output.images,
                        videos=task_output.videos,
                        audio=task_output.audio,
                        task_response=task_output,
                    )
                    log_debug(f"Yielding TaskCompletedEvent for task: {task.name}")
                else:
                    yield event

        # Create final output data
        final_output = {
            "pipeline_id": self.pipeline_id,
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

        workflow_run_response.content = collected_task_outputs[
            -1
        ].content  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.extra_data = final_output
        workflow_run_response.status = RunStatus.completed

    async def aexecute(
        self,
        pipeline_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """Execute all tasks in the pipeline using TaskInput/TaskOutput (non-streaming)"""
        log_debug(f"Async Pipeline Execution Start: {self.name}", center=True)
        log_debug(f"Pipeline ID: {self.pipeline_id}")
        log_debug(f"Total tasks: {len(self.tasks)}")

        logger.info(f"Starting pipeline: {self.name}")

        # Update pipeline info in the response
        workflow_run_response.pipeline_name = self.name

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []

        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        previous_task_content = None

        for i, task in enumerate(self.tasks):
            log_debug(f"Executing async task {i + 1}/{len(self.tasks)}: {task.name}")
            log_debug(f"Task ID: {task.task_id}")

            logger.info(f"Executing task {i + 1}/{len(self.tasks)}: {task.name}")

            # Create TaskInput for this task
            task_input = TaskInput(
                message=pipeline_input.message,
                message_data=pipeline_input.message_data,
                previous_task_content=previous_task_content,
                images=pipeline_images,
                videos=pipeline_videos,
                audio=pipeline_audio,
            )

            # Execute the task (non-streaming) - pass workflow_run_response
            task_output = await task.aexecute(task_input, session_id=session_id, user_id=user_id)

            # Collect the task output
            if task_output is None:
                raise RuntimeError(f"Task {task.name} did not return a TaskOutput")

            # Update the input for the next task
            previous_task_content = task_output.content
            pipeline_images.extend(task_output.images or [])
            pipeline_videos.extend(task_output.videos or [])
            pipeline_audio.extend(task_output.audio or [])

            # Collect the TaskOutput for storage
            collected_task_outputs.append(task_output)

        # Create final output data
        final_output = {
            "pipeline_id": self.pipeline_id,
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

        log_debug(f"Async Pipeline Execution End: {self.name}", center=True, symbol="*")

        # Update the workflow_run_response with completion data
        workflow_run_response.content = collected_task_outputs[
            -1
        ].content  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.extra_data = final_output
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.status = RunStatus.completed

    async def aexecute_stream(
        self,
        pipeline_input: WorkflowExecutionInput,
        workflow_run_response: WorkflowRunResponse,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[WorkflowRunResponseEvent]:
        """Execute the pipeline with event-driven streaming support"""
        log_debug(f"Async Pipeline Streaming Execution Start: {self.name}", center=True)
        log_debug(f"Pipeline ID: {self.pipeline_id}")
        log_debug(f"Stream intermediate steps: {stream_intermediate_steps}")
        log_debug(f"Total tasks: {len(self.tasks)}")

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []
        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        previous_task_content = None

        # Execute tasks in pipeline with streaming
        for task_index, task in enumerate(self.tasks):
            log_debug(f"Async streaming task {task_index + 1}/{len(self.tasks)}: {task.name}")

            # Create TaskInput for this task
            task_input = TaskInput(
                message=pipeline_input.message,
                message_data=pipeline_input.message_data,
                previous_task_content=previous_task_content,
                images=pipeline_images,
                videos=pipeline_videos,
                audio=pipeline_audio,
            )

            # Yield task started event
            yield TaskStartedEvent(
                run_id=workflow_run_response.run_id or "",
                workflow_name=workflow_run_response.workflow_name,
                pipeline_name=workflow_run_response.pipeline_name,
                task_name=task.name,
                task_index=task_index,
                workflow_id=workflow_run_response.workflow_id,
                session_id=workflow_run_response.session_id,
            )

            task_stream = await task.aexecute(
                task_input,
                session_id=session_id,
                user_id=user_id,
                stream=True,
                stream_intermediate_steps=stream_intermediate_steps,
            )

            async for event in task_stream:
                log_debug(f"Received async event from task {task.name}: {type(event).__name__}")

                if isinstance(event, TaskOutput):
                    # This is the final task output
                    task_output = event
                    log_debug(f"Received final async TaskOutput from {task.name}")

                    # Collect the task output
                    collected_task_outputs.append(task_output)

                    log_debug(f"Updated previous outputs with async streaming task {task.name} results")
                    pipeline_images.extend(task_output.images or [])
                    pipeline_videos.extend(task_output.videos or [])
                    pipeline_audio.extend(task_output.audio or [])
                    previous_task_content = task_output.content
                    log_debug(f"Yielding async TaskCompletedEvent for task: {task.name}")
                    # Yield task completed event
                    yield TaskCompletedEvent(
                        run_id=workflow_run_response.run_id or "",
                        content=task_output.content,
                        workflow_name=workflow_run_response.workflow_name,
                        pipeline_name=self.name,
                        task_name=task.name,
                        task_index=task_index,
                        workflow_id=workflow_run_response.workflow_id,
                        session_id=workflow_run_response.session_id,
                        images=task_output.images,
                        videos=task_output.videos,
                        audio=task_output.audio,
                        task_response=task_output,
                    )
                else:
                    yield event

        # Create final output data
        final_output = {
            "pipeline_id": self.pipeline_id,
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

        log_debug(f"Async Pipeline Streaming Execution End: {self.name}", center=True, symbol="*")
        workflow_run_response.content = collected_task_outputs[
            -1
        ].content  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.extra_data = final_output
        workflow_run_response.status = RunStatus.completed

    def add_task(self, task: Task) -> None:
        """Add a task to the pipeline"""
        self.tasks.append(task)

    def remove_task(self, task_name: str) -> bool:
        """Remove a task from the pipeline by name"""
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
