from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional
from uuid import uuid4

from agno.media import AudioArtifact, ImageArtifact, VideoArtifact
from agno.run.base import RunStatus
from agno.run.v2.workflow import (
    TaskCompletedEvent,
    TaskStartedEvent,
    WorkflowCompletedEvent,
    WorkflowRunResponse,
    WorkflowRunResponseEvent,
    WorkflowStartedEvent,
)
from agno.utils.log import logger
from agno.workflow.v2.task import Task, TaskInput, TaskOutput


@dataclass
class PipelineInput:
    """Input data for a task execution"""

    message: Optional[str] = None

    # Media inputs
    images: Optional[List[ImageArtifact]] = None
    videos: Optional[List[VideoArtifact]] = None
    audio: Optional[List[AudioArtifact]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "message": self.message,
            "images": [img.to_dict() for img in self.images] if self.images else None,
            "videos": [vid.to_dict() for vid in self.videos] if self.videos else None,
            "audio": [aud.to_dict() for aud in self.audio] if self.audio else None,
        }


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
            self.pipeline_id = str(uuid4())

    def execute(self, pipeline_input: PipelineInput, workflow_run_response: WorkflowRunResponse):
        """Execute all tasks in the pipeline using TaskInput/TaskOutput (non-streaming)"""
        logger.info(f"Starting pipeline: {self.name}")

        # Update pipeline info in the response
        workflow_run_response.pipeline_name = self.name

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []

        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        task_message = pipeline_input.message

        # Execute tasks sequentially
        for i, task in enumerate(self.tasks):
            logger.info(f"Executing task {i + 1}/{len(self.tasks)}: {task.name}")

            # Create TaskInput for this task
            task_input = TaskInput(
                message=task_message,
                images=pipeline_images,
                videos=pipeline_videos,
                audio=pipeline_audio,
            )

            # Execute the task (non-streaming)
            task_output = task.execute(task_input)

            # Collect the task output
            if task_output is None:
                raise RuntimeError(f"Task {task.name} did not return a TaskOutput")

            # Update the input for the next task
            task_message = task_output.content
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

        # Update the workflow_run_response with completion data
        workflow_run_response.content = task_message  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.extra_data = final_output
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.status = RunStatus.completed

    def execute_stream(
        self,
        pipeline_input: PipelineInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[WorkflowRunResponseEvent]:
        """Execute the pipeline with event-driven streaming support"""
        logger.info(f"Executing pipeline with streaming: {self.name}")

        # Update pipeline info in the response
        workflow_run_response.pipeline_name = self.name

        # Yield workflow started event
        yield WorkflowStartedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name,
            pipeline_name=self.name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
        )

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []
        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        task_message = pipeline_input.message

        # Execute tasks in pipeline with streaming
        for task_index, task in enumerate(self.tasks):
            # Create TaskInput for this task
            task_input = TaskInput(
                message=task_message,
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
                stream=True,
                stream_intermediate_steps=stream_intermediate_steps,
            ):
                if isinstance(event, TaskOutput):
                    # This is the final task output
                    task_output = event

                    # Collect the task output
                    collected_task_outputs.append(task_output)

                    pipeline_images.extend(task_output.images or [])
                    pipeline_videos.extend(task_output.videos or [])
                    pipeline_audio.extend(task_output.audio or [])

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

        workflow_run_response.content = collected_task_outputs[
            -1
        ].content  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.extra_data = final_output
        workflow_run_response.status = RunStatus.completed

        # Yield workflow completed event
        yield WorkflowCompletedEvent(
            run_id=workflow_run_response.run_id or "",
            content=workflow_run_response.content,
            workflow_name=workflow_run_response.workflow_name,
            pipeline_name=self.name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
            task_responses=collected_task_outputs,
            extra_data=final_output,
        )

    async def aexecute(self, pipeline_input: PipelineInput, workflow_run_response: WorkflowRunResponse):
        """Execute all tasks in the pipeline using TaskInput/TaskOutput (non-streaming)"""
        logger.info(f"Starting pipeline: {self.name}")

        # Update pipeline info in the response
        workflow_run_response.pipeline_name = self.name

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []

        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        task_message = pipeline_input.message

        for i, task in enumerate(self.tasks):
            logger.info(f"Executing task {i + 1}/{len(self.tasks)}: {task.name}")

            # Create TaskInput for this task
            task_input = TaskInput(
                message=task_message,
                images=pipeline_images,
                videos=pipeline_videos,
                audio=pipeline_audio,
            )

            # Execute the task (non-streaming) - pass workflow_run_response
            task_output = await task.aexecute(task_input)

            # Collect the task output
            if task_output is None:
                raise RuntimeError(f"Task {task.name} did not return a TaskOutput")

            # Update the input for the next task
            task_message = task_output.content
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

        # Update the workflow_run_response with completion data
        workflow_run_response.content = task_message  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.extra_data = final_output
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.status = RunStatus.completed

    async def aexecute_stream(
        self,
        pipeline_input: PipelineInput,
        workflow_run_response: WorkflowRunResponse,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[WorkflowRunResponseEvent]:
        """Execute the pipeline with event-driven streaming support"""
        logger.info(f"Executing pipeline with streaming: {self.name}")

        # Yield workflow started event
        yield WorkflowStartedEvent(
            run_id=workflow_run_response.run_id or "",
            workflow_name=workflow_run_response.workflow_name,
            pipeline_name=self.name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
        )

        # Track outputs from each task for chaining
        collected_task_outputs: List[TaskOutput] = []
        pipeline_images = pipeline_input.images or []
        pipeline_videos = pipeline_input.videos or []
        pipeline_audio = pipeline_input.audio or []
        task_message = pipeline_input.message

        # Execute tasks in pipeline with streaming
        for task_index, task in enumerate(self.tasks):
            # Create TaskInput for this task
            task_input = TaskInput(
                message=task_message,
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
                stream=True,
                stream_intermediate_steps=stream_intermediate_steps,
            )

            async for event in task_stream:
                if isinstance(event, TaskOutput):
                    # This is the final task output
                    task_output = event

                    # Collect the task output
                    collected_task_outputs.append(task_output)

                    pipeline_images.extend(task_output.images or [])
                    pipeline_videos.extend(task_output.videos or [])
                    pipeline_audio.extend(task_output.audio or [])

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

        workflow_run_response.content = collected_task_outputs[
            -1
        ].content  # Final workflow response output is the last task's output
        workflow_run_response.task_responses = collected_task_outputs
        workflow_run_response.images = pipeline_images
        workflow_run_response.videos = pipeline_videos
        workflow_run_response.audio = pipeline_audio
        workflow_run_response.extra_data = final_output
        workflow_run_response.status = RunStatus.completed

        # Yield workflow completed event
        yield WorkflowCompletedEvent(
            run_id=workflow_run_response.run_id or "",
            content=workflow_run_response.content,
            workflow_name=workflow_run_response.workflow_name,
            pipeline_name=self.name,
            workflow_id=workflow_run_response.workflow_id,
            session_id=workflow_run_response.session_id,
            task_responses=collected_task_outputs,
            extra_data=final_output,
        )

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
