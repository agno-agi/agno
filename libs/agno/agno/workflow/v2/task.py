from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, Optional, Union, List
from pydantic import BaseModel

from agno.agent import Agent
from agno.media import Image, ImageArtifact, Video, VideoArtifact
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.run.v2.workflow import (
    WorkflowRunResponseEvent,
)
from agno.team import Team
from agno.utils.log import log_debug, logger
from agno.workflow.v2.types import TaskInput, TaskOutput

TaskExecutor = Callable[
    [TaskInput],
    Union[
        TaskOutput,
        Iterator[TaskOutput],
        Iterator[Any],
        Awaitable[TaskOutput],
        Awaitable[Any],
        AsyncIterator[TaskOutput],
        AsyncIterator[Any],
    ],
]


@dataclass
class Task:
    """A single unit of work in a workflow pipeline"""

    name: Optional[str] = None

    # Executor options - only one should be provided
    agent: Optional[Agent] = None
    team: Optional[Team] = None
    executor: Optional[TaskExecutor] = None

    task_id: Optional[str] = None
    description: Optional[str] = None

    # Task configuration
    max_retries: int = 3
    timeout_seconds: Optional[int] = None

    skip_on_failure: bool = False

    # Input validation mode
    # If False, only warn about missing inputs
    strict_input_validation: bool = False

    _retry_count: int = 0

    def __init__(
        self,
        name: Optional[str] = None,
        agent: Optional[Agent] = None,
        team: Optional[Team] = None,
        executor: Optional[TaskExecutor] = None,
        task_id: Optional[str] = None,
        description: Optional[str] = None,
        max_retries: int = 3,
        timeout_seconds: Optional[int] = None,
        skip_on_failure: bool = False,
        strict_input_validation: bool = False,
    ):
        self.name = name
        self.agent = agent
        self.team = team
        self.executor = executor

        # Validate executor configuration
        self._validate_executor_config()

        self.task_id = task_id
        self.description = description
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.skip_on_failure = skip_on_failure
        self.strict_input_validation = strict_input_validation

        # Set the active executor
        self._set_active_executor()

    @property
    def executor_name(self) -> str:
        """Get the name of the current executor"""
        if hasattr(self.active_executor, "name"):
            return self.active_executor.name
        elif self._executor_type == "function":
            return getattr(self.active_executor, "__name__", "anonymous_function")
        else:
            return f"{self._executor_type}_executor"

    @property
    def executor_type(self) -> str:
        """Get the type of the current executor"""
        return self._executor_type

    def _validate_executor_config(self):
        """Validate that only one executor type is provided"""
        executor_count = sum(
            [
                self.agent is not None,
                self.team is not None,
                self.executor is not None,
            ]
        )

        if executor_count == 0:
            raise ValueError(f"Task '{self.name}' must have one executor: agent=, team=, or executor=")

        if executor_count > 1:
            provided_executors = []
            if self.agent is not None:
                provided_executors.append("agent")
            if self.team is not None:
                provided_executors.append("team")
            if self.executor is not None:
                provided_executors.append("executor")

            raise ValueError(
                f"Task '{self.name}' can only have one executor type. "
                f"Provided: {', '.join(provided_executors)}. "
                f"Please use only one of: agent=, team=, or executor="
            )

    def _set_active_executor(self):
        """Set the active executor based on what was provided"""
        if self.agent is not None:
            self.active_executor = self.agent
            self._executor_type = "agent"
        elif self.team is not None:
            self.active_executor = self.team
            self._executor_type = "team"
        elif self.executor is not None:
            self.active_executor = self.executor
            self._executor_type = "function"

    def execute(
        self,
        task_input: TaskInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
    ) -> Union[TaskOutput, Iterator[WorkflowRunResponseEvent]]:
        """Execute the task with TaskInput, with optional streaming support"""
        log_debug(f"Task Execute Start: {self.name}", center=True)

        if stream:
            return self._execute_task_stream(
                task_input=task_input,
                session_id=session_id,
                user_id=user_id,
                stream_intermediate_steps=stream_intermediate_steps,
            )
        else:
            return self._execute_task(task_input=task_input, session_id=session_id, user_id=user_id)

    def _execute_task(
        self, task_input: TaskInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> TaskOutput:
        """Execute the task with TaskInput, returning final TaskOutput (non-streaming)"""
        log_debug(f"Executor type: {self._executor_type}")

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                log_debug(f"Task {self.name} attempt {attempt + 1}/{self.max_retries + 1}")
                if self._executor_type == "function":
                    # Execute function directly with TaskInput
                    result = self.active_executor(task_input)  # type: ignore

                    # If function returns TaskOutput, use it directly
                    if isinstance(result, TaskOutput):
                        return result

                    # Otherwise, wrap in TaskOutput
                    response = TaskOutput(content=str(result))
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(task_input.message, task_input.message_data)

                    # Execute agent or team with media
                    if self._executor_type in ["agent", "team"]:
                        images = self._convert_image_artifacts_to_images(task_input.images) if task_input.images else None
                        videos = self._convert_video_artifacts_to_videos(task_input.videos) if task_input.videos else None
                        response = self.active_executor.run(
                            message=message,
                            images=images,
                            videos=videos,
                            audio=task_input.audio,
                            session_id=session_id,
                            user_id=user_id,
                        )
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # Create TaskOutput from response
                task_output = self._create_task_output(response)

                log_debug(f"Task {self.name} completed successfully on attempt {attempt + 1}")
                log_debug(f"Task Execute End: {self.name}", center=True, symbol="*")

                logger.info(f"Task {self.name} completed successfully")
                return task_output

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Task {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        logger.info(f"Task {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty TaskOutput for skipped task
                        return TaskOutput(content=f"Task {self.name} failed but skipped", success=False, error=str(e))
                    else:
                        raise e

    def _execute_task_stream(
        self,
        task_input: TaskInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[Union[WorkflowRunResponseEvent, TaskOutput]]:
        """Execute the task with event-driven streaming support"""
        # Execute with retries and streaming
        for attempt in range(self.max_retries + 1):
            try:
                log_debug(f"Task {self.name} streaming attempt {attempt + 1}/{self.max_retries + 1}")
                final_response = None

                if self._executor_type == "function":
                    log_debug(f"Executing function executor for task: {self.name}")
                    # Handle custom function streaming
                    result = self.active_executor(task_input)  # type: ignore

                    if hasattr(result, "__iter__") and not isinstance(result, (str, bytes, dict, TaskOutput)):
                        log_debug(f"Function returned iterable, streaming events")
                        try:
                            for event in result:
                                if isinstance(event, TaskOutput):
                                    final_response = event
                                    log_debug(f"Received final TaskOutput from function")
                                else:
                                    log_debug(f"Yielding event from function: {type(event).__name__}")
                                    yield event
                        except StopIteration as e:
                            if hasattr(e, "value") and isinstance(e.value, TaskOutput):
                                final_response = e.value
                        except TypeError:
                            if isinstance(result, TaskOutput):
                                final_response = result
                            else:
                                final_response = TaskOutput(content=str(result))
                    else:
                        if isinstance(result, TaskOutput):
                            final_response = result
                        else:
                            final_response = TaskOutput(content=str(result))
                        log_debug(f"Function returned non-iterable, created TaskOutput")
                else:
                    message = self._prepare_message(task_input.message, task_input.message_data)

                    if self._executor_type in ["agent", "team"]:
                        images = self._convert_image_artifacts_to_images(task_input.images) if task_input.images else None
                        videos = self._convert_video_artifacts_to_videos(task_input.videos) if task_input.videos else None
                        response_stream = self.active_executor.run(
                            message=message,
                            images=images,
                            videos=videos,
                            audio=task_input.audio,
                            session_id=session_id,
                            user_id=user_id,
                            stream=True,
                            stream_intermediate_steps=stream_intermediate_steps,
                        )

                        for event in response_stream:
                            log_debug(f"Received event from agent: {type(event).__name__}")
                            yield event
                        final_response = self._create_task_output(self.active_executor.run_response)

                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # If we didn't get a final response, create one
                if final_response is None:
                    final_response = TaskOutput(content="")
                    log_debug(f"Created empty TaskOutput as fallback")

                logger.info(f"Task {self.name} completed successfully with streaming")
                yield final_response
                return

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Task {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        logger.info(f"Task {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty TaskOutput for skipped task
                        task_output = TaskOutput(
                            content=f"Task {self.name} failed but skipped", success=False, error=str(e)
                        )
                        yield task_output
                        return
                    else:
                        raise e

    async def aexecute(
        self,
        task_input: TaskInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream: bool = False,
        stream_intermediate_steps: bool = False,
    ) -> Union[TaskOutput, AsyncIterator[WorkflowRunResponseEvent]]:
        """Execute the task with TaskInput, with optional streaming support"""
        log_debug(f"Async Task Execute Start: {self.name}", center=True)

        if stream:
            return self._aexecute_task_stream(
                task_input=task_input,
                session_id=session_id,
                user_id=user_id,
                stream_intermediate_steps=stream_intermediate_steps,
            )
        else:
            return await self._aexecute_task(task_input=task_input, session_id=session_id, user_id=user_id)

    async def _aexecute_task(
        self, task_input: TaskInput, session_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> TaskOutput:
        """Execute the task with TaskInput, returning final TaskOutput (non-streaming)"""
        log_debug(f"Executing async task (non-streaming): {self.name}")
        log_debug(f"Executor type: {self._executor_type}")

        # Execute with retries
        for attempt in range(self.max_retries + 1):
            try:
                if self._executor_type == "function":
                    import inspect

                    if inspect.iscoroutinefunction(self.active_executor):
                        result = await self.active_executor(task_input)  # type: ignore
                    else:
                        result = self.active_executor(task_input)  # type: ignore

                    # If function returns TaskOutput, use it directly
                    if isinstance(result, TaskOutput):
                        return result

                    # Otherwise, wrap in TaskOutput
                    response = TaskOutput(content=str(result))
                else:
                    # For agents and teams, prepare message with context
                    message = self._prepare_message(task_input.message, task_input.message_data)

                    # Execute agent or team with media
                    if self._executor_type in ["agent", "team"]:
                        images = self._convert_image_artifacts_to_images(task_input.images) if task_input.images else None
                        videos = self._convert_video_artifacts_to_videos(task_input.videos) if task_input.videos else None
                        response = await self.active_executor.arun(
                            message=message,
                            images=images,
                            videos=videos,
                            audio=task_input.audio,
                            session_id=session_id,
                            user_id=user_id,
                        )
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # Create TaskOutput from response
                task_output = self._create_task_output(response)

                logger.info(f"Async Task {self.name} completed successfully")
                return task_output

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Task {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        logger.info(f"Task {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty TaskOutput for skipped task
                        return TaskOutput(content=f"Task {self.name} failed but skipped", success=False, error=str(e))
                    else:
                        raise e

    async def _aexecute_task_stream(
        self,
        task_input: TaskInput,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[Union[WorkflowRunResponseEvent, TaskOutput]]:
        """Execute the task with event-driven streaming support"""
        # Execute with retries and streaming
        for attempt in range(self.max_retries + 1):
            try:
                log_debug(f"Async task {self.name} streaming attempt {attempt + 1}/{self.max_retries + 1}")
                final_response = None

                if self._executor_type == "function":
                    log_debug(f"Executing async function executor for task: {self.name}")
                    import inspect

                    # Check if the function is an async generator
                    if inspect.isasyncgenfunction(self.active_executor):
                        # It's an async generator - iterate over it
                        async for event in self.active_executor(task_input):
                            if isinstance(event, TaskOutput):
                                final_response = event
                                log_debug(f"Received final TaskOutput from async generator")
                            else:
                                log_debug(f"Yielding event from async generator: {type(event).__name__}")
                                yield event
                    elif inspect.iscoroutinefunction(self.active_executor):
                        # It's a regular async function - await it
                        result = await self.active_executor(task_input)
                        if isinstance(result, TaskOutput):
                            final_response = result
                        else:
                            final_response = TaskOutput(content=str(result))
                    elif inspect.isgeneratorfunction(self.active_executor):
                        # It's a regular generator function - iterate over it
                        for event in self.active_executor(task_input):
                            if isinstance(event, TaskOutput):
                                final_response = event
                            else:
                                yield event
                    else:
                        # It's a regular function - call it directly
                        result = self.active_executor(task_input)  # type: ignore
                        if isinstance(result, TaskOutput):
                            final_response = result
                        else:
                            final_response = TaskOutput(content=str(result))
                else:
                    message = self._prepare_message(task_input.message, task_input.message_data)
                    if self._executor_type in ["agent", "team"]:
                        images = self._convert_image_artifacts_to_images(task_input.images) if task_input.images else None
                        videos = self._convert_video_artifacts_to_videos(task_input.videos) if task_input.videos else None
                        response_stream = await self.active_executor.arun(  # type: ignore
                            message=message,
                            images=images,
                            videos=videos,
                            audio=task_input.audio,
                            session_id=session_id,
                            user_id=user_id,
                            stream=True,
                            stream_intermediate_steps=stream_intermediate_steps,
                        )

                        async for event in response_stream:
                            log_debug(f"Received async event from agent: {type(event).__name__}")
                            yield event
                        final_response = self._create_task_output(self.active_executor.run_response)  # type: ignore
                    else:
                        raise ValueError(f"Unsupported executor type: {self._executor_type}")

                # If we didn't get a final response, create one
                if final_response is None:
                    final_response = TaskOutput(content="")

                logger.info(f"Task {self.name} completed successfully with streaming")
                yield final_response
                return

            except Exception as e:
                self.retry_count = attempt + 1
                logger.warning(f"Task {self.name} failed (attempt {attempt + 1}): {e}")

                if attempt == self.max_retries:
                    if self.skip_on_failure:
                        logger.info(f"Task {self.name} failed but continuing due to skip_on_failure=True")
                        # Create empty TaskOutput for skipped task
                        task_output = TaskOutput(
                            content=f"Task {self.name} failed but skipped", success=False, error=str(e)
                        )
                        yield task_output
                        return
                    else:
                        raise e

    def _parse_message_data(self, message_data: Optional[Union[BaseModel, Dict[str, Any]]]) -> Optional[str]:
        """Parse the message data into a string"""
        data_str = None
        if message_data is not None:
            if isinstance(message_data, BaseModel):
                data_str = message_data.model_dump_json(indent=2, exclude_none=True)
            elif isinstance(message_data, dict):
                import json

                data_str = json.dumps(message_data, indent=2, default=str)
            else:
                data_str = str(message_data)
        return data_str

    def _prepare_message(
        self, message: Optional[str], message_data: Optional[Union[BaseModel, Dict[str, Any]]]
    ) -> Optional[str]:
        """Prepare the primary input by combining message and message_data"""

        # Convert message_data to string if provided
        data_str = self._parse_message_data(message_data)
        # Combine message and data
        if message and data_str:
            return f"{message}\n\n--- Structured Data ---\n{data_str}"
        elif message:
            return message
        elif data_str:
            return f"Process the following data:\n{data_str}"
        else:
            return None

    def _create_task_output(self, response: Union[RunResponse, TeamRunResponse, TaskOutput]) -> TaskOutput:
        """Create TaskOutput from execution response"""
        log_debug(f"Creating TaskOutput for task: {self.name}")
        log_debug(f"Response type: {type(response).__name__}")

        if isinstance(response, TaskOutput):
            response.task_name = self.name
            response.task_id = self.task_id
            response.executor_type = self._executor_type
            response.executor_name = self.executor_name

            return response

        # Extract media from response
        images = getattr(response, "images", None)
        videos = getattr(response, "videos", None)
        audio = getattr(response, "audio", None)

        return TaskOutput(
            task_name=self.name,
            task_id=self.task_id,
            executor_type=self._executor_type,
            executor_name=self.executor_name,
            content=response.content,
            response=response,
            images=images,
            videos=videos,
            audio=audio,
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

    def _convert_image_artifacts_to_images(self, image_artifacts: List[ImageArtifact]) -> List[Image]:
        """
        Convert ImageArtifact objects to Image objects with proper content handling.

        Args:
            image_artifacts: List of ImageArtifact objects to convert

        Returns:
            List of Image objects ready for agent processing
        """
        import base64

        images = []
        for i, img_artifact in enumerate(image_artifacts):
            # Create Image object with proper data from ImageArtifact
            if img_artifact.url:
                images.append(Image(url=img_artifact.url))

            elif img_artifact.content:
                # Handle the case where content is base64-encoded bytes from OpenAI tools
                try:
                    # Try to decode as base64 first (for images from OpenAI tools)
                    if isinstance(img_artifact.content, bytes):
                        # Decode bytes to string, then decode base64 to get actual image bytes
                        base64_string = img_artifact.content.decode("utf-8")
                        actual_image_bytes = base64.b64decode(base64_string)
                        logger.info(f"Decoded base64 content to {len(actual_image_bytes)} bytes")
                    else:
                        # If it's already actual image bytes
                        actual_image_bytes = img_artifact.content

                    # Create Image object with proper format
                    image_kwargs = {"content": actual_image_bytes}
                    if img_artifact.mime_type:
                        # Convert mime_type to format (e.g., "image/png" -> "png")
                        if "/" in img_artifact.mime_type:
                            format_from_mime = img_artifact.mime_type.split("/")[-1]
                            image_kwargs["format"] = format_from_mime
                            logger.info(f"Setting format from mime_type: {format_from_mime}")

                    images.append(Image(**image_kwargs))

                except Exception as e:
                    logger.error(f"Failed to process image content: {e}")
                    # Skip this image if we can't process it
                    continue

            else:
                # Skip images that have neither URL nor content
                logger.warning(f"Skipping ImageArtifact {i} with no URL or content: {img_artifact}")
                continue

        return images

    def _convert_video_artifacts_to_videos(self, video_artifacts: List[VideoArtifact]) -> List[Video]:
        """
        Convert VideoArtifact objects to Video objects with proper content handling.

        Args:
            video_artifacts: List of VideoArtifact objects to convert

        Returns:
            List of Video objects ready for agent processing
        """
        videos = []
        for i, video_artifact in enumerate(video_artifacts):
            # Create Image object with proper data from ImageArtifact
            if video_artifact.url:
                videos.append(Video(url=video_artifact.url))

            elif video_artifact.content:
                videos.append(Video(content=video_artifact.content))

            else:
                # Skip images that have neither URL nor content
                logger.warning(f"Skipping VideoArtifact {i} with no URL or content: {video_artifact}")
                continue

        return videos
