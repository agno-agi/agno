"""Shared orchestration logic for Agent and Team classes."""

from collections import defaultdict
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Type,
    Union,
    cast,
    get_args,
)
from dataclasses import asdict
from pydantic import BaseModel
from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run.messages import RunMessages
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.response import format_tool_calls
from agno.banavo.memory import Memory
from agno.banavo.run.response import RunResponse, RunResponseEvent
from agno.banavo.run.team import TeamRunResponse, TeamRunResponseEvent
from agno.banavo.utils.events import (
    create_reasoning_completed_event,
    create_reasoning_started_event,
    create_reasoning_step_event,
    create_run_response_content_event,
    create_team_run_response_content_event,
    create_tool_call_completed_event,
    create_team_tool_call_completed_event,
    create_tool_call_started_event,
    create_team_tool_call_started_event,
)


# Compatibility stubs — AgentMemory/AgentRun removed from agno 2.x; Banavo uses Memory instead
class AgentMemory:
    """Stub — agno.memory.agent.AgentMemory removed in agno 2.x."""

    create_user_memories: bool = False
    create_session_summary: bool = False


class AgentRun:
    """Stub — agno.memory.agent.AgentRun removed in agno 2.x."""

    def __init__(self, response=None, **kwargs):
        self.response = response


class AgentTeamBase:
    """Base class for Agent and Team with shared orchestration logic.

    This class consolidates common methods between Agent and Team classes
    to reduce code duplication and maintain a single source of truth for
    shared functionality.
    """

    def _add_reasoning_metrics_to_extra_data(
        self, reasoning_time_taken: float, run_response: Optional[Any] = None
    ) -> None:
        """Add reasoning time metrics to the run response's extra data.

        Args:
            reasoning_time_taken: Time taken for reasoning in seconds
            run_response: Optional run response object (for Team), uses self.run_response if not provided
        """
        try:
            # Use provided run_response if available (Team case), otherwise use self.run_response (Agent case)
            response = run_response if run_response is not None else getattr(self, "run_response", None)

            if response is not None:
                if response.extra_data is None:
                    from agno.banavo.run.response import RunResponseExtraData

                    response.extra_data = RunResponseExtraData()

                # Initialize reasoning_messages if it doesn't exist
                if response.extra_data.reasoning_messages is None:
                    response.extra_data.reasoning_messages = []

                metrics_message = Message(
                    role="assistant",
                    content=response.reasoning_content if hasattr(response, "reasoning_content") else "",
                    metrics={"time": reasoning_time_taken},
                )

                # Add the metrics message to the reasoning_messages
                response.extra_data.reasoning_messages.append(metrics_message)

        except Exception as e:
            # Log the error but don't crash
            log_error(f"Failed to add reasoning metrics to extra_data: {str(e)}")

    def _add_reasoning_step_to_extra_data(self, reasoning_step: Any, run_response: Optional[Any] = None) -> None:
        """Add a reasoning step to the run response's extra data.

        Args:
            reasoning_step: The reasoning step to add
            run_response: Optional run response object (for Team), uses self.run_response if not provided
        """
        try:
            # Use provided run_response if available (Team case), otherwise use self.run_response (Agent case)
            response = run_response if run_response is not None else getattr(self, "run_response", None)

            if response is not None:
                if response.extra_data is None:
                    from agno.banavo.run.response import RunResponseExtraData

                    response.extra_data = RunResponseExtraData()

                # Initialize reasoning_steps if it doesn't exist
                if response.extra_data.reasoning_steps is None:
                    response.extra_data.reasoning_steps = []

                # Add the reasoning step
                response.extra_data.reasoning_steps.append(reasoning_step)

        except Exception as e:
            log_error(f"Failed to add reasoning step to extra_data: {str(e)}")

    def _initialize_session_state(self, user_id: Optional[str] = None, session_id: Optional[str] = None) -> None:
        """Initialize the session state from user and session IDs.

        Args:
            user_id: The user ID
            session_id: The session ID
        """
        self.session_state = self.session_state or {}

        log_debug(f"Initializing session state from user id: {user_id} and session_id: {session_id}")

        if user_id is not None and session_id is not None:
            self.session_state[user_id] = self.session_state.get(user_id, {})
            self.session_state[user_id][session_id] = self.session_state[user_id].get(session_id, {})
        elif user_id is not None:
            self.session_state[user_id] = self.session_state.get(user_id, {})

    def _get_effective_filters(self, knowledge_filters: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Determine which knowledge filters to use, with priority to run-level filters.

        Args:
            knowledge_filters: Filters passed at run time

        Returns:
            The effective filters to use, with run-level filters taking priority
        """
        effective_filters = None

        # If agent/team has filters, use those as a base
        if hasattr(self, "knowledge_filters") and self.knowledge_filters:
            effective_filters = self.knowledge_filters.copy()

        # If run has filters, they override agent/team filters
        if knowledge_filters:
            if effective_filters:
                # Merge filters, with run filters taking priority
                effective_filters.update(knowledge_filters)
            else:
                effective_filters = knowledge_filters

        if effective_filters:
            log_debug(f"Using knowledge filters: {effective_filters}")

        return effective_filters

    def add_to_session_state(self, key: str, value: Any, user_id: Optional[str] = None) -> None:
        """Add a value to the session state.

        Args:
            key: The key to add
            value: The value to add
            user_id: Optional user ID for scoping
        """
        if not hasattr(self, "session_state"):
            self.session_state = {}

        if user_id:
            if user_id not in self.session_state:
                self.session_state[user_id] = {}
            self.session_state[user_id][key] = value
        else:
            self.session_state[key] = value

    def get_session_state(self, key: Optional[str] = None, user_id: Optional[str] = None) -> Any:
        """Get a value from the session state.

        Args:
            key: Optional key to retrieve. If None, returns entire state.
            user_id: Optional user ID for scoping

        Returns:
            The requested value or entire state
        """
        if not hasattr(self, "session_state"):
            self.session_state = {}

        if user_id:
            if user_id not in self.session_state:
                return None
            state = self.session_state[user_id]
        else:
            state = self.session_state

        if key:
            return state.get(key)
        else:
            return state

    def is_streamable(self) -> bool:
        """Check if the response can be streamed.

        Returns:
            True if streamable, False otherwise
        """
        # Check if response_model is set (non-streamable if set)
        if hasattr(self, "response_model") and self.response_model is not None:
            return False

        # Otherwise, assume streamable
        return True

    def _append_to_reasoning_content(self, content: str) -> None:
        """Append content to the reasoning output.

        Args:
            content: The content to append
        """
        if not hasattr(self, "reasoning_content"):
            self.reasoning_content = ""

        self.reasoning_content += content

    def add_image(self, image: Any) -> None:
        """Add an image to the agent/team.

        Args:
            image: The image artifact to add
        """
        if self.images is None:
            self.images = []
        self.images.append(image)
        if self.run_response is not None:
            if self.run_response.images is None:
                self.run_response.images = []
            self.run_response.images.append(image)

    def add_video(self, video: Any) -> None:
        """Add a video to the agent/team.

        Args:
            video: The video artifact to add
        """
        if self.videos is None:
            self.videos = []
        self.videos.append(video)
        if self.run_response is not None:
            if self.run_response.videos is None:
                self.run_response.videos = []
            self.run_response.videos.append(video)

    def add_audio(self, audio: Any) -> None:
        """Add audio to the agent/team.

        Args:
            audio: The audio artifact to add
        """
        if self.audio is None:
            self.audio = []
        self.audio.append(audio)
        if self.run_response is not None:
            if self.run_response.audio is None:
                self.run_response.audio = []
            self.run_response.audio.append(audio)

    def get_images(self) -> Optional[List[Any]]:
        """Get images from the agent/team.

        Returns:
            List of image artifacts or None
        """
        return self.images

    def get_videos(self) -> Optional[List[Any]]:
        """Get videos from the agent/team.

        Returns:
            List of video artifacts or None
        """
        return self.videos

    def get_audio(self) -> Optional[List[Any]]:
        """Get audio from the agent/team.

        Returns:
            List of audio artifacts or None
        """
        return self.audio

    def _create_run_data(self) -> Dict[str, Any]:
        """Create and return the run data dictionary.

        Returns:
            Dictionary containing run metadata including functions and metrics
        """
        run_response_format = "text"
        if self.response_model is not None:
            run_response_format = "json"
        elif self.markdown:
            run_response_format = "markdown"

        functions = {}
        if self._functions_for_model:
            functions = {
                f_name: func.to_dict()
                for f_name, func in self._functions_for_model.items()
                if isinstance(func, getattr(self, "_function_class", object))
            }

        run_data: Dict[str, Any] = {
            "functions": functions,
            "metrics": getattr(self.run_response, "metrics", {}) if self.run_response else {},
        }

        if getattr(self, "monitoring", False):
            run_data.update(
                {
                    "run_input": getattr(self, "run_input", None),
                    "run_response": self.run_response.to_dict() if self.run_response else {},
                    "run_response_format": run_response_format,
                }
            )

        return run_data

    def _format_reasoning_step_content(self, reasoning_step: Any, run_response: Optional[Any] = None) -> str:
        """Format content for a reasoning step.

        Args:
            reasoning_step: The reasoning step to format
            run_response: Optional run response object (for Team), uses self.run_response if not provided

        Returns:
            Formatted reasoning step content as string
        """
        step_content = ""
        if reasoning_step.title:
            step_content += f"## {reasoning_step.title}\n"
        if reasoning_step.reasoning:
            step_content += f"{reasoning_step.reasoning}\n"
        if reasoning_step.action:
            step_content += f"Action: {reasoning_step.action}\n"
        if reasoning_step.result:
            step_content += f"Result: {reasoning_step.result}\n"
        step_content += "\n"

        # Get the current reasoning_content and append this step
        response = run_response if run_response is not None else getattr(self, "run_response", None)
        current_reasoning_content = ""
        if response and hasattr(response, "reasoning_content") and response.reasoning_content:
            current_reasoning_content = response.reasoning_content

        # Create updated reasoning_content
        updated_reasoning_content = current_reasoning_content + step_content

        return updated_reasoning_content

    def get_user_memories(self, user_id: Optional[str] = None) -> Optional[List[Any]]:
        """Get the user memories for the given user ID.

        Args:
            user_id: The user ID to get memories for

        Returns:
            List of user memories or None
        """
        if not hasattr(self, "memory") or self.memory is None:
            return None
        user_id = user_id if user_id is not None else getattr(self, "user_id", None)
        if user_id is None:
            user_id = "default"

        from agno.banavo.memory import Memory

        if isinstance(self.memory, Memory):
            return self.memory.get_user_memories(user_id=user_id)
        else:
            raise ValueError(f"Memory type {type(self.memory)} not supported for get_user_memories")

    # Method: _get_agentic_or_user_search_filters
    def _get_agentic_or_user_search_filters(
        self, filters: Optional[Dict[str, Any]], effective_filters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Helper function to determine the final filters to use for the search.

        Args:
            filters: Filters passed by the agent.
            effective_filters: Filters passed by user.

        Returns:
            Dict[str, Any]: The final filters to use for the search.
        """
        search_filters = {}

        # If agentic filters exist and manual filters (passed by user) do not, use agentic filters
        if filters and not effective_filters:
            search_filters = filters

        # If both agentic filters exist and manual filters (passed by user) exist, use manual filters (give priority to user and override)
        if filters and effective_filters:
            search_filters = effective_filters

        log_info(f"Filters used by Agent: {search_filters}")
        return search_filters

    # Method: search_knowledge_base_function
    def search_knowledge_base_function(
        self, knowledge_filters: Optional[Dict[str, Any]] = None, async_mode: bool = False
    ) -> Callable:
        """Factory function to create a search_knowledge_base function with filters."""

        def search_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """

            # Get the relevant documents from the knowledge base, passing filters
            self.run_response = cast(RunResponse, self.run_response)
            retrieval_timer = Timer()
            retrieval_timer.start()
            docs_from_knowledge = self.get_relevant_docs_from_knowledge(query=query, filters=knowledge_filters)
            if docs_from_knowledge is not None:
                references = MessageReferences(
                    query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
                )
                # Add the references to the run_response
                if self.run_response.extra_data is None:
                    self.run_response.extra_data = RunResponseExtraData()
                if self.run_response.extra_data.references is None:
                    self.run_response.extra_data.references = []
                self.run_response.extra_data.references.append(references)
            retrieval_timer.stop()
            from agno.utils.log import log_debug

            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if docs_from_knowledge is None:
                return "No documents found"
            return self.convert_documents_to_string(docs_from_knowledge)

        async def asearch_knowledge_base(query: str) -> str:
            """Use this function to search the knowledge base for information about a query asynchronously.

            Args:
                query: The query to search for.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            self.run_response = cast(RunResponse, self.run_response)
            retrieval_timer = Timer()
            retrieval_timer.start()
            docs_from_knowledge = await self.aget_relevant_docs_from_knowledge(query=query, filters=knowledge_filters)
            if docs_from_knowledge is not None:
                references = MessageReferences(
                    query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
                )
                if self.run_response.extra_data is None:
                    self.run_response.extra_data = RunResponseExtraData()
                if self.run_response.extra_data.references is None:
                    self.run_response.extra_data.references = []
                self.run_response.extra_data.references.append(references)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if docs_from_knowledge is None:
                return "No documents found"
            return self.convert_documents_to_string(docs_from_knowledge)

        if async_mode:
            return asearch_knowledge_base
        else:
            return search_knowledge_base

    # Method: search_knowledge_base_with_agentic_filters_function
    def search_knowledge_base_with_agentic_filters_function(
        self, knowledge_filters: Optional[Dict[str, Any]] = None, async_mode: bool = False
    ) -> Callable:
        """Factory function to create a search_knowledge_base function with filters."""

        def search_knowledge_base(query: str, filters: Optional[Dict[str, Any]] = None) -> str:
            """Use this function to search the knowledge base for information about a query.

            Args:
                query: The query to search for.
                filters: The filters to apply to the search. This is a dictionary of key-value pairs.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            search_filters = self._get_agentic_or_user_search_filters(filters, knowledge_filters)

            # Get the relevant documents from the knowledge base, passing filters
            self.run_response = cast(RunResponse, self.run_response)
            retrieval_timer = Timer()
            retrieval_timer.start()
            docs_from_knowledge = self.get_relevant_docs_from_knowledge(query=query, filters=search_filters)
            if docs_from_knowledge is not None:
                references = MessageReferences(
                    query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
                )
                # Add the references to the run_response
                if self.run_response.extra_data is None:
                    self.run_response.extra_data = RunResponseExtraData()
                if self.run_response.extra_data.references is None:
                    self.run_response.extra_data.references = []
                self.run_response.extra_data.references.append(references)
            retrieval_timer.stop()
            from agno.utils.log import log_debug

            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if docs_from_knowledge is None:
                return "No documents found"
            return self.convert_documents_to_string(docs_from_knowledge)

        async def asearch_knowledge_base(query: str, filters: Optional[Dict[str, Any]] = None) -> str:
            """Use this function to search the knowledge base for information about a query asynchronously.

            Args:
                query: The query to search for.
                filters: The filters to apply to the search. This is a dictionary of key-value pairs.

            Returns:
                str: A string containing the response from the knowledge base.
            """
            search_filters = self._get_agentic_or_user_search_filters(filters, knowledge_filters)

            self.run_response = cast(RunResponse, self.run_response)
            retrieval_timer = Timer()
            retrieval_timer.start()
            docs_from_knowledge = await self.aget_relevant_docs_from_knowledge(query=query, filters=search_filters)
            if docs_from_knowledge is not None:
                references = MessageReferences(
                    query=query, references=docs_from_knowledge, time=round(retrieval_timer.elapsed, 4)
                )
                if self.run_response.extra_data is None:
                    self.run_response.extra_data = RunResponseExtraData()
                if self.run_response.extra_data.references is None:
                    self.run_response.extra_data.references = []
                self.run_response.extra_data.references.append(references)
            retrieval_timer.stop()
            log_debug(f"Time to get references: {retrieval_timer.elapsed:.4f}s")

            if docs_from_knowledge is None:
                return "No documents found"
            return self.convert_documents_to_string(docs_from_knowledge)

        if async_mode:
            return asearch_knowledge_base
        else:
            return search_knowledge_base

    # Method: _handle_model_response_chunk
    def _handle_model_response_chunk(
        self,
        run_response: RunResponse,
        model_response: ModelResponse,
        model_response_event: Union[ModelResponse, RunResponseEvent, TeamRunResponseEvent],
        reasoning_state: Dict[str, Any],
        stream_intermediate_steps: bool = False,
    ) -> Iterator[RunResponseEvent]:
        if isinstance(model_response_event, tuple(get_args(RunResponseEvent))) or isinstance(
            model_response_event, tuple(get_args(TeamRunResponseEvent))
        ):
            # We just bubble the event up
            yield model_response_event  # type: ignore
        else:
            model_response_event = cast(ModelResponse, model_response_event)
            # If the model response is an assistant_response, yield a RunResponse
            if (
                hasattr(model_response_event, "event")
                and model_response_event.event == ModelResponseEvent.assistant_response.value
            ):
                # Process content and thinking
                if model_response_event.content is not None:
                    model_response.content = (model_response.content or "") + model_response_event.content
                    run_response.content = model_response.content

                # agno 2.x renamed thinking → reasoning_content
                _mre_thinking = getattr(model_response_event, "reasoning_content", None) or getattr(
                    model_response_event, "thinking", None
                )
                _mre_redacted = getattr(model_response_event, "redacted_reasoning_content", None) or getattr(
                    model_response_event, "redacted_thinking", None
                )

                if _mre_thinking is not None:
                    _cur = getattr(model_response, "reasoning_content", None) or getattr(
                        model_response, "thinking", None
                    )
                    model_response.reasoning_content = (_cur or "") + _mre_thinking
                    run_response.thinking = model_response.reasoning_content

                if _mre_redacted is not None:
                    _cur_r = getattr(model_response, "redacted_reasoning_content", None) or getattr(
                        model_response, "redacted_thinking", None
                    )
                    model_response.redacted_reasoning_content = (_cur_r or "") + _mre_redacted
                    run_response.thinking = model_response.redacted_reasoning_content

                if model_response_event.citations is not None:
                    # We get citations in one chunk
                    run_response.citations = model_response_event.citations

                # Only yield if we have content or thinking to show
                if (
                    model_response_event.content is not None
                    or _mre_thinking is not None
                    or _mre_redacted is not None
                    or model_response_event.citations is not None
                ):
                    if isinstance(run_response, TeamRunResponse):
                        yield create_team_run_response_content_event(
                            from_run_response=run_response,
                            content=model_response_event.content,
                            thinking=_mre_thinking,
                            redacted_thinking=_mre_redacted,
                            citations=model_response_event.citations,
                        )
                    else:
                        yield create_run_response_content_event(
                            from_run_response=run_response,
                            content=model_response_event.content,
                            thinking=_mre_thinking,
                            redacted_thinking=_mre_redacted,
                            citations=model_response_event.citations,
                        )

                # Process audio
                if model_response_event.audio is not None:
                    if model_response.audio is None:
                        model_response.audio = AudioResponse(id=str(uuid4()), content="", transcript="")

                    if model_response_event.audio.id is not None:
                        model_response.audio.id = model_response_event.audio.id  # type: ignore
                    if model_response_event.audio.content is not None:
                        model_response.audio.content += model_response_event.audio.content  # type: ignore
                    if model_response_event.audio.transcript is not None:
                        model_response.audio.transcript += model_response_event.audio.transcript  # type: ignore
                    if model_response_event.audio.expires_at is not None:
                        model_response.audio.expires_at = model_response_event.audio.expires_at  # type: ignore
                    if model_response_event.audio.mime_type is not None:
                        model_response.audio.mime_type = model_response_event.audio.mime_type  # type: ignore
                    model_response.audio.sample_rate = model_response_event.audio.sample_rate
                    model_response.audio.channels = model_response_event.audio.channels

                    # Yield the audio and transcript bit by bit
                    run_response.response_audio = AudioResponse(
                        id=model_response_event.audio.id,
                        content=model_response_event.audio.content,
                        transcript=model_response_event.audio.transcript,
                        sample_rate=model_response_event.audio.sample_rate,
                        channels=model_response_event.audio.channels,
                    )
                    run_response.created_at = model_response_event.created_at

                    if isinstance(run_response, TeamRunResponse):
                        yield create_team_run_response_content_event(
                            from_run_response=run_response,
                            response_audio=run_response.response_audio,
                        )
                    else:
                        yield create_run_response_content_event(
                            from_run_response=run_response,
                            response_audio=run_response.response_audio,
                        )

                _mre_img = getattr(model_response_event, "image", None)
                if _mre_img is None:
                    _mre_imgs = getattr(model_response_event, "images", None)
                    _mre_img = _mre_imgs[0] if _mre_imgs else None
                if _mre_img is not None:
                    self.add_image(_mre_img)

                    if isinstance(run_response, TeamRunResponse):
                        yield create_team_run_response_content_event(
                            from_run_response=run_response,
                            image=_mre_img,
                        )
                    else:
                        yield create_run_response_content_event(
                            from_run_response=run_response,
                            image=_mre_img,
                        )

            # Handle tool interruption events
            elif (
                hasattr(model_response_event, "event")
                and model_response_event.event == ModelResponseEvent.tool_call_paused.value
            ):
                # Add tool calls to the run_response
                tool_executions_list = model_response_event.tool_executions
                if tool_executions_list is not None:
                    # Add tool calls to the agent.run_response
                    if run_response.tools is None:
                        run_response.tools = tool_executions_list
                    else:
                        run_response.tools.extend(tool_executions_list)

                    # Format tool calls whenever new ones are added during streaming
                    run_response.formatted_tool_calls = format_tool_calls(run_response.tools)
            # If the model response is a tool_call_started, add the tool call to the run_response
            elif (
                hasattr(model_response_event, "event")
                and model_response_event.event == ModelResponseEvent.tool_call_started.value
            ):  # Add tool calls to the run_response
                tool_executions_list = model_response_event.tool_executions
                if tool_executions_list is not None:
                    # Add tool calls to the agent.run_response
                    if run_response.tools is None:
                        run_response.tools = tool_executions_list
                    else:
                        run_response.tools.extend(tool_executions_list)

                    # Format tool calls whenever new ones are added during streaming
                    run_response.formatted_tool_calls = format_tool_calls(run_response.tools)

                    # Yield each tool call started event
                    for tool in tool_executions_list:
                        if isinstance(run_response, TeamRunResponse):
                            yield create_team_tool_call_started_event(from_run_response=run_response, tool=tool)
                        else:
                            yield create_tool_call_started_event(from_run_response=run_response, tool=tool)

            # If the model response is a tool_call_completed, update the existing tool call in the run_response
            elif (
                hasattr(model_response_event, "event")
                and model_response_event.event == ModelResponseEvent.tool_call_completed.value
            ):
                reasoning_step: Optional[ReasoningStep] = None

                tool_executions_list = model_response_event.tool_executions
                if tool_executions_list is not None:
                    # Update the existing tool call in the run_response
                    if run_response.tools:
                        # Create a mapping of tool_call_id to index
                        tool_call_index_map = {
                            tc.tool_call_id: i for i, tc in enumerate(run_response.tools) if tc.tool_call_id is not None
                        }
                        # Process tool calls
                        for tool_call_dict in tool_executions_list:
                            tool_call_id = tool_call_dict.tool_call_id or ""
                            index = tool_call_index_map.get(tool_call_id)
                            if index is not None:
                                run_response.tools[index] = tool_call_dict
                    else:
                        run_response.tools = tool_executions_list

                    # Only iterate through new tool calls
                    for tool_call in tool_executions_list:
                        tool_name = tool_call.tool_name or ""
                        if tool_name.lower() in ["think", "analyze"]:
                            tool_args = tool_call.tool_args or {}

                            reasoning_step = self.update_reasoning_content_from_tool_call(tool_name, tool_args)

                            metrics = tool_call.metrics
                            if metrics is not None and metrics.time is not None:
                                reasoning_state["reasoning_time_taken"] = reasoning_state[
                                    "reasoning_time_taken"
                                ] + float(metrics.time)
                        if isinstance(run_response, TeamRunResponse):
                            yield create_team_tool_call_completed_event(
                                from_run_response=run_response, tool=tool_call, content=model_response_event.content
                            )
                        else:
                            yield create_tool_call_completed_event(
                                from_run_response=run_response, tool=tool_call, content=model_response_event.content
                            )

                if stream_intermediate_steps:
                    if reasoning_step is not None:
                        if not reasoning_state["reasoning_started"]:
                            yield create_reasoning_started_event(from_run_response=run_response)
                            reasoning_state["reasoning_started"] = True

                        yield create_reasoning_step_event(
                            from_run_response=run_response,
                            reasoning_step=reasoning_step,
                            reasoning_content=run_response.reasoning_content or "",
                        )

    # Method: _get_response_format
    def _get_response_format(self, model: Optional[Model] = None) -> Optional[Union[Dict, Type[BaseModel]]]:
        self.model = cast(Model, model or self.model)
        if self.response_model is None:
            return None
        else:
            json_response_format = {"type": "json_object"}

            if self.model.supports_native_structured_outputs:
                if not self.use_json_mode or self.structured_outputs:
                    log_debug("Setting Model.response_format to Agent.response_model")
                    return self.response_model
                else:
                    log_debug(
                        "Model supports native structured outputs but it is not enabled. Using JSON mode instead."
                    )
                    return json_response_format

            elif self.model.supports_json_schema_outputs:
                if self.use_json_mode or (not self.structured_outputs):
                    log_debug("Setting Model.response_format to JSON response mode")
                    return {
                        "type": "json_schema",
                        "json_schema": {
                            "name": self.response_model.__name__,
                            "schema": self.response_model.model_json_schema(),
                        },
                    }
                else:
                    return None

            else:
                log_debug("Model does not support structured or JSON schema outputs.")
                return json_response_format

    # Method: get_messages_for_parser_model
    def get_messages_for_parser_model(
        self, model_response: ModelResponse, response_format: Optional[Union[Dict, Type[BaseModel]]]
    ) -> List[Message]:
        """Get the messages for the parser model."""
        system_content = (
            self.parser_model_prompt
            if self.parser_model_prompt is not None
            else "You are tasked with creating a structured output from the provided data."
        )

        if response_format == {"type": "json_object"} and self.response_model is not None:
            system_content += f"{get_json_output_prompt(self.response_model)}"  # type: ignore

        return [
            Message(role="system", content=system_content),
            Message(role="user", content=model_response.content),
        ]

    # Method: get_system_message
    def get_system_message(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
    ) -> Optional[Message]:
        """Return the system message for the Agent.

        1. If the system_message is provided, use that.
        2. If create_default_system_message is False, return None.
        3. Build and return the default system message for the Agent.
        """

        # 1. If the system_message is provided, use that.
        if self.system_message is not None:
            if isinstance(self.system_message, Message):
                return self.system_message

            sys_message_content: str = ""
            if isinstance(self.system_message, str):
                sys_message_content = self.system_message
            elif callable(self.system_message):
                sys_message_content = self.system_message(agent=self)
                if not isinstance(sys_message_content, str):
                    raise Exception("system_message must return a string")

            # Format the system message with the session state variables
            if self.add_state_in_messages:
                sys_message_content = self.format_message_with_state_variables(sys_message_content)

            # Add the JSON output prompt if response_model is provided and the model does not support native structured outputs or JSON schema outputs
            # or if use_json_mode is True
            if (
                self.model is not None
                and self.parser_model is None
                and self.response_model is not None
                and not (
                    (self.model.supports_native_structured_outputs or self.model.supports_json_schema_outputs)
                    and (not self.use_json_mode or self.structured_outputs is True)
                )
            ):
                sys_message_content += f"\n{get_json_output_prompt(self.response_model)}"  # type: ignore

            # type: ignore
            return Message(role=self.system_message_role, content=sys_message_content)

        # 2. If create_default_system_message is False, return None.
        if not self.create_default_system_message:
            return None

        if self.model is None:
            raise Exception("model not set")

        # 3. Build and return the default system message for the Agent.
        # 3.1 Build the list of instructions for the system message
        instructions: List[str] = []
        if self.instructions is not None:
            _instructions = self.instructions
            if callable(self.instructions):
                _instructions = self.instructions(agent=self)

            if isinstance(_instructions, str):
                instructions.append(_instructions)
            elif isinstance(_instructions, list):
                instructions.extend(_instructions)
        # 3.1.1 Add instructions from the Model
        _model_instructions = self.model.get_instructions_for_model(self._tools_for_model)
        if _model_instructions is not None:
            instructions.extend(_model_instructions)

        # 3.2 Build a list of additional information for the system message
        additional_information: List[str] = []
        # 3.2.1 Add instructions for using markdown
        if self.markdown and self.response_model is None:
            additional_information.append("Use markdown to format your answers.")
        # 3.2.2 Add the current datetime
        if self.add_datetime_to_instructions:
            from datetime import datetime

            tz = None

            if self.timezone_identifier:
                try:
                    from zoneinfo import ZoneInfo

                    tz = ZoneInfo(self.timezone_identifier)
                except Exception:
                    log_warning("Invalid timezone identifier")

            time = datetime.now(tz) if tz else datetime.now()

            additional_information.append(f"The current time is {time}.")

        # 3.2.3 Add the current location
        if self.add_location_to_instructions:
            from agno.utils.location import get_location

            location = get_location()
            if location:
                location_str = ", ".join(
                    filter(None, [location.get("city"), location.get("region"), location.get("country")])
                )
                if location_str:
                    additional_information.append(f"Your approximate location is: {location_str}.")

        # 3.2.4 Add agent name if provided
        if self.name is not None and self.add_name_to_instructions:
            additional_information.append(f"Your name is: {self.name}.")

        # 3.2.5 Add information about agentic filters if enabled
        if self.knowledge is not None and self.enable_agentic_knowledge_filters:
            valid_filters = getattr(self.knowledge, "valid_metadata_filters", None)
            if valid_filters:
                valid_filters_str = ", ".join(valid_filters)
                additional_information.append(
                    dedent(
                        f"""
                    The knowledge base contains documents with these metadata filters: {valid_filters_str}.
                    Always use filters when the user query indicates specific metadata.

                    Examples:
                    1. If the user asks about a specific person like "Jordan Mitchell", you MUST use the search_knowledge_base tool with the filters parameter set to {{'<valid key like user_id>': '<valid value based on the user query>'}}.
                    2. If the user asks about a specific document type like "contracts", you MUST use the search_knowledge_base tool with the filters parameter set to {{'document_type': 'contract'}}.
                    4. If the user asks about a specific location like "documents from New York", you MUST use the search_knowledge_base tool with the filters parameter set to {{'<valid key like location>': 'New York'}}.

                    General Guidelines:
                    - Always analyze the user query to identify relevant metadata.
                    - Use the most specific filter(s) possible to narrow down results.
                    - If multiple filters are relevant, combine them in the filters parameter (e.g., {{'name': 'Jordan Mitchell', 'document_type': 'contract'}}).
                    - Ensure the filter keys match the valid metadata filters: {valid_filters_str}.

                    You can use the search_knowledge_base tool to search the knowledge base and get the most relevant documents. Make sure to pass the filters as [Dict[str: Any]] to the tool. FOLLOW THIS STRUCTURE STRICTLY.
                """
                    )
                )

        # 3.3 Build the default system message for the Agent.
        system_message_content: str = ""
        # 3.3.1 First add the Agent description if provided
        if self.description is not None:
            system_message_content += f"{self.description}\n"
        # 3.3.2 Then add the Agent goal if provided
        if self.goal is not None:
            system_message_content += f"\n<your_goal>\n{self.goal}\n</your_goal>\n\n"
        # 3.3.3 Then add the Agent role if provided
        if self.role is not None:
            system_message_content += f"\n<your_role>\n{self.role}\n</your_role>\n\n"
        # 3.3.4 Then add instructions for transferring tasks to team members
        if self.has_team and self.add_transfer_instructions:
            system_message_content += (
                "<agent_team>\n"
                "You are the leader of a team of AI Agents:\n"
                "- You can either respond directly or transfer tasks to other Agents in your team depending on the tools available to them.\n"
                "- If you transfer a task to another Agent, make sure to include:\n"
                "  - task_description (str): A clear description of the task.\n"
                "  - expected_output (str): The expected output.\n"
                "  - additional_information (str): Additional information that will help the Agent complete the task.\n"
                "- You must always validate the output of the other Agents before responding to the user.\n"
                "- You can re-assign the task if you are not satisfied with the result.\n"
                "</agent_team>\n\n"
            )
        # 3.3.5 Then add instructions for the Agent
        if len(instructions) > 0:
            system_message_content += "<instructions>"
            if len(instructions) > 1:
                for _upi in instructions:
                    system_message_content += f"\n- {_upi}"
            else:
                system_message_content += "\n" + instructions[0]
            system_message_content += "\n</instructions>\n\n"
        # 3.3.6 Add additional information
        if len(additional_information) > 0:
            system_message_content += "<additional_information>"
            for _ai in additional_information:
                system_message_content += f"\n- {_ai}"
            system_message_content += "\n</additional_information>\n\n"
        # 3.3.7 Then add instructions for the tools
        if self._tool_instructions is not None:
            for _ti in self._tool_instructions:
                system_message_content += f"{_ti}\n"

        # Format the system message with the session state variables
        if self.add_state_in_messages:
            system_message_content = self.format_message_with_state_variables(system_message_content)

        # 3.3.7 Then add the expected output
        if self.expected_output is not None:
            system_message_content += f"<expected_output>\n{self.expected_output.strip()}\n</expected_output>\n\n"
        # 3.3.8 Then add additional context
        if self.additional_context is not None:
            system_message_content += f"{self.additional_context}\n"
        # 3.3.9 Then add information about the team members
        if self.has_team and self.add_transfer_instructions:
            system_message_content += (
                f"<transfer_instructions>\n{self.get_transfer_instructions().strip()}\n</transfer_instructions>\n\n"
            )
        if self.success_criteria:
            system_message_content += "Your task is successful when the following criteria is met:\n"
            system_message_content += "<success_criteria>\n"
            system_message_content += f"{self.success_criteria}\n"
            system_message_content += "</success_criteria>\n"
            system_message_content += "Stop running when the success_criteria is met.\n\n"
        # 3.3.10 Then add memories to the system prompt
        if self.memory:
            if isinstance(self.memory, AgentMemory) and self.memory.create_user_memories:
                if self.memory.memories and len(self.memory.memories) > 0:
                    system_message_content += (
                        "You have access to memories from previous interactions with the user that you can use:\n\n"
                    )
                    system_message_content += "<memories_from_previous_interactions>"
                    for _memory in self.memory.memories:
                        system_message_content += f"\n- {_memory.memory}"
                    system_message_content += "\n</memories_from_previous_interactions>\n\n"
                    system_message_content += (
                        "Note: this information is from previous interactions and may be updated in this conversation. "
                        "You should always prefer information from this conversation over the past memories.\n\n"
                    )
                else:
                    system_message_content += (
                        "You have the capability to retain memories from previous interactions with the user, "
                        "but have not had any interactions with the user yet.\n"
                    )
                system_message_content += (
                    "You can add new memories using the `update_memory` tool.\n"
                    "If you use the `update_memory` tool, remember to pass on the response to the user.\n\n"
                )
            elif isinstance(self.memory, Memory) and self.add_memory_references:
                if not user_id:
                    user_id = "default"
                user_memories = self.memory.get_user_memories(user_id=user_id)  # type: ignore
                if user_memories and len(user_memories) > 0:
                    system_message_content += (
                        "You have access to memories from previous interactions with the user that you can use:\n\n"
                    )
                    system_message_content += "<memories_from_previous_interactions>"
                    for _memory in user_memories:  # type: ignore
                        system_message_content += f"\n- {_memory.memory}"
                    system_message_content += "\n</memories_from_previous_interactions>\n\n"
                    system_message_content += (
                        "Note: this information is from previous interactions and may be updated in this conversation. "
                        "You should always prefer information from this conversation over the past memories.\n"
                    )
                else:
                    system_message_content += (
                        "You have the capability to retain memories from previous interactions with the user, "
                        "but have not had any interactions with the user yet.\n"
                    )

                if self.enable_agentic_memory:
                    system_message_content += (
                        "\n<updating_user_memories>\n"
                        "- You have access to the `update_user_memory` tool that you can use to add new memories, update existing memories, delete memories, or clear all memories.\n"
                        "- If the user's message includes information that should be captured as a memory, use the `update_user_memory` tool to update your memory database.\n"
                        "- Memories should include details that could personalize ongoing interactions with the user.\n"
                        "- Use this tool to add new memories or update existing memories that you identify in the conversation.\n"
                        "- Use this tool if the user asks to update their memory, delete a memory, or clear all memories.\n"
                        "- If you use the `update_user_memory` tool, remember to pass on the response to the user.\n"
                        "</updating_user_memories>\n\n"
                    )

            # 3.3.11 Then add a summary of the interaction to the system prompt
            if isinstance(self.memory, AgentMemory) and self.memory.create_session_summary:
                if self.memory.summary is not None:
                    system_message_content += "Here is a brief summary of your previous interactions:\n\n"
                    system_message_content += "<summary_of_previous_interactions>\n"
                    system_message_content += str(self.memory.summary)
                    system_message_content += "\n</summary_of_previous_interactions>\n\n"
                    system_message_content += (
                        "Note: this information is from previous interactions and may be outdated. "
                        "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
                    )
            elif isinstance(self.memory, Memory) and self.add_session_summary_references:
                if not user_id:
                    user_id = "default"
                session_summary: SessionSummary = self.memory.summaries.get(user_id, {}).get(session_id, None)  # type: ignore
                if session_summary is not None:
                    system_message_content += "Here is a brief summary of your previous interactions:\n\n"
                    system_message_content += "<summary_of_previous_interactions>\n"
                    system_message_content += session_summary.summary
                    system_message_content += "\n</summary_of_previous_interactions>\n\n"
                    system_message_content += (
                        "Note: this information is from previous interactions and may be outdated. "
                        "You should ALWAYS prefer information from this conversation over the past summary.\n\n"
                    )

        # 3.3.12 Add the system message from the Model
        system_message_from_model = self.model.get_system_message_for_model(self._tools_for_model)
        if system_message_from_model is not None:
            system_message_content += system_message_from_model

        # 3.3.13 Add the JSON output prompt if response_model is provided and the model does not support native structured outputs or JSON schema outputs
        # or if use_json_mode is True
        if (
            self.response_model is not None
            and self.parser_model is None
            and not (
                (self.model.supports_native_structured_outputs or self.model.supports_json_schema_outputs)
                and (not self.use_json_mode or self.structured_outputs is True)
            )
        ):
            system_message_content += f"{get_json_output_prompt(self.response_model)}"  # type: ignore

        # 3.3.14 Add the response model format prompt if response_model is provided
        if self.response_model is not None and self.parser_model is not None:
            system_message_content += f"{get_response_model_format_prompt(self.response_model)}"

        # Return the system message
        return (
            Message(role=self.system_message_role, content=system_message_content.strip())  # type: ignore
            if system_message_content
            else None
        )

    # Method: get_update_user_memory_function
    def get_update_user_memory_function(self, user_id: Optional[str] = None, async_mode: bool = False) -> Callable:
        def update_user_memory(task: str) -> str:
            """Use this function to submit a task to modify the Agent's memory.
            Describe the task in detail and be specific.
            The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

            Args:
                task: The task to update the memory. Be specific and describe the task in detail.

            Returns:
                str: A string indicating the status of the task.
            """
            self.memory = cast(Memory, self.memory)
            response = self.memory.update_memory_task(task=task, user_id=user_id)

            return response

        async def aupdate_user_memory(task: str) -> str:
            """Use this function to update the Agent's memory of a user.
            Describe the task in detail and be specific.
            The task can include adding a memory, updating a memory, deleting a memory, or clearing all memories.

            Args:
                task: The task to update the memory. Be specific and describe the task in detail.

            Returns:
                str: A string indicating the status of the task.
            """
            self.memory = cast(Memory, self.memory)
            response = await self.memory.aupdate_memory_task(task=task, user_id=user_id)
            return response

        if async_mode:
            return aupdate_user_memory
        else:
            return update_user_memory

    # Method: get_messages_for_session
    def get_messages_for_session(self, session_id: Optional[str] = None) -> List[Message]:
        """Get messages for a session"""
        _session_id = session_id or self.session_id
        if _session_id is None:
            log_warning("Session ID is not set, cannot get messages for session")
            return []

        if self.memory is None:
            self.read_from_storage(session_id=_session_id)

        if self.memory is None:
            return []

        if isinstance(self.memory, AgentMemory):
            return self.memory.messages
        elif isinstance(self.memory, Memory):
            return self.memory.get_messages_from_last_n_runs(session_id=_session_id, agent_id=self.agent_id)
        else:
            return []

    ###########################################################################
    # Handle images, videos and audio
    ###########################################################################

    ###########################################################################
    # Reasoning
    ###########################################################################

    # Method: _add_run_to_memory
    def _add_run_to_memory(
        self,
        run_response: RunResponse,
        run_messages: RunMessages,
        session_id: str,
        messages: Optional[Sequence[Union[Dict, Message]]] = None,
        index_of_last_user_message: int = 0,
    ):
        if isinstance(self.memory, AgentMemory):
            self.memory = cast(AgentMemory, self.memory)
        else:
            self.memory = cast(Memory, self.memory)

        if isinstance(self.memory, AgentMemory):
            # Add the system message to the memory
            if run_messages.system_message is not None:
                self.memory.add_system_message(
                    run_messages.system_message, system_message_role=self.system_message_role
                )

            # Build a list of messages that should be added to the AgentMemory
            messages_for_memory: List[Message] = (
                [run_messages.user_message] if run_messages.user_message is not None else []
            )
            # Add messages from messages_for_run after the last user message
            for _rm in run_messages.messages[index_of_last_user_message:]:
                if _rm.add_to_agent_memory:
                    messages_for_memory.append(_rm)
            if len(messages_for_memory) > 0:
                self.memory.add_messages(messages=messages_for_memory)

            # Create an AgentRun object to add to memory
            agent_run = AgentRun(response=run_response)
            agent_run.message = run_messages.user_message

            if messages is not None and len(messages) > 0:
                for _im in messages:
                    # Parse the message and convert to a Message object if possible
                    mp = None
                    if isinstance(_im, Message):
                        mp = _im
                    elif isinstance(_im, dict):
                        try:
                            mp = Message(**_im)
                        except Exception as e:
                            log_warning(f"Failed to validate message: {e}")
                    else:
                        log_warning(f"Unsupported message type: {type(_im)}")
                        continue

                    # Add the message to the AgentRun
                    if mp:
                        if agent_run.messages is None:
                            agent_run.messages = []
                        agent_run.messages.append(mp)
                    else:
                        log_warning("Unable to add message to memory")

            # Add AgentRun to memory
            self.memory.add_run(agent_run)

        elif isinstance(self.memory, Memory):
            # Add AgentRun to memory
            self.memory.add_run(session_id=session_id, run=run_response)

    # Method: get_relevant_docs_from_knowledge
    def get_relevant_docs_from_knowledge(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Optional[List[Union[Dict[str, Any], str]]]:
        """Get relevant docs from the knowledge base to answer a query.

        Args:
            query (str): The query to search for.
            num_documents (Optional[int]): Number of documents to return.
            filters (Optional[Dict[str, Any]]): Filters to apply to the search.
            **kwargs: Additional keyword arguments.

        Returns:
            Optional[List[Dict[str, Any]]]: List of relevant document dicts.
        """
        from agno.document import Document

        # Validate the filters against known valid filter keys
        if self.knowledge is not None:
            valid_filters, invalid_keys = self.knowledge.validate_filters(filters)  # type: ignore

            # Warn about invalid filter keys
            if invalid_keys:
                # type: ignore
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")
                log_info(f"Valid filter keys are: {self.knowledge.valid_metadata_filters}")  # type: ignore

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

        if self.retriever is not None and callable(self.retriever):
            from inspect import signature

            try:
                sig = signature(self.retriever)
                retriever_kwargs: Dict[str, Any] = {}
                if "agent" in sig.parameters:
                    retriever_kwargs = {"agent": self}
                if "filters" in sig.parameters:
                    retriever_kwargs["filters"] = filters
                retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})
                return self.retriever(**retriever_kwargs)
            except Exception as e:
                log_warning(f"Retriever failed: {e}")
                raise e

        # Use knowledge base search
        try:
            if self.knowledge is None or (
                getattr(self.knowledge, "vector_db", None) is None
                and getattr(self.knowledge, "retriever", None) is None
            ):
                return None

            if num_documents is None:
                num_documents = self.knowledge.num_documents

            log_debug(f"Searching knowledge base with filters: {filters}")
            relevant_docs: List[Document] = self.knowledge.search(
                query=query, num_documents=num_documents, filters=filters
            )

            if not relevant_docs or len(relevant_docs) == 0:
                log_debug("No relevant documents found for query")
                return None

            return [doc.to_dict() for doc in relevant_docs]
        except Exception as e:
            log_warning(f"Error searching knowledge base: {e}")
            raise e

    async def aget_relevant_docs_from_knowledge(
        self, query: str, num_documents: Optional[int] = None, filters: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Optional[List[Union[Dict[str, Any], str]]]:
        """Get relevant documents from knowledge base asynchronously."""
        from agno.document import Document

        # Validate the filters against known valid filter keys
        if self.knowledge is not None:
            valid_filters, invalid_keys = self.knowledge.validate_filters(filters)  # type: ignore

            # Warn about invalid filter keys
            if invalid_keys:  # type: ignore
                log_warning(f"Invalid filter keys provided: {invalid_keys}. These filters will be ignored.")
                log_info(f"Valid filter keys are: {self.knowledge.valid_metadata_filters}")  # type: ignore

                # Only use valid filters
                filters = valid_filters
                if not filters:
                    log_warning("No valid filters remain after validation. Search will proceed without filters.")

        if self.retriever is not None and callable(self.retriever):
            from inspect import isawaitable, signature

            try:
                sig = signature(self.retriever)
                retriever_kwargs: Dict[str, Any] = {}
                if "agent" in sig.parameters:
                    retriever_kwargs = {"agent": self}
                if "filters" in sig.parameters:
                    retriever_kwargs["filters"] = filters
                retriever_kwargs.update({"query": query, "num_documents": num_documents, **kwargs})
                result = self.retriever(**retriever_kwargs)

                if isawaitable(result):
                    result = await result

                return result
            except Exception as e:
                log_warning(f"Retriever failed: {e}")
                raise e

        # Use knowledge base search
        try:
            if self.knowledge is None or (
                getattr(self.knowledge, "vector_db", None) is None
                and getattr(self.knowledge, "retriever", None) is None
            ):
                return None

            if num_documents is None:
                num_documents = self.knowledge.num_documents

            log_debug(f"Searching knowledge base with filters: {filters}")
            relevant_docs: List[Document] = await self.knowledge.async_search(
                query=query, num_documents=num_documents, filters=filters
            )

            if not relevant_docs or len(relevant_docs) == 0:
                log_debug("No relevant documents found for query")
                return None

            return [doc.to_dict() for doc in relevant_docs]
        except Exception as e:
            log_warning(f"Error searching knowledge base: {e}")
            raise e

    # Method: _handle_model_response_stream
    def _handle_model_response_stream(
        self,
        run_response: RunResponse,
        run_messages: RunMessages,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_intermediate_steps: bool = False,
    ) -> Iterator[RunResponseEvent]:
        self.model = cast(Model, self.model)

        reasoning_state = {
            "reasoning_started": False,
            "reasoning_time_taken": 0.0,
        }
        model_response = ModelResponse(content="")

        for model_response_event in self.model.response_stream(
            messages=run_messages.messages,
            response_format=response_format,
            tools=self._tools_for_model,
            functions=self._functions_for_model,
            tool_choice=self.tool_choice,
            tool_call_limit=self.tool_call_limit,
        ):
            yield from self._handle_model_response_chunk(
                run_response=run_response,
                model_response=model_response,
                model_response_event=model_response_event,
                stream_intermediate_steps=stream_intermediate_steps,
                reasoning_state=reasoning_state,
            )

        # Determine reasoning completed
        if stream_intermediate_steps and reasoning_state["reasoning_started"]:
            all_reasoning_steps: List[ReasoningStep] = []
            if run_response and run_response.extra_data and hasattr(run_response.extra_data, "reasoning_steps"):
                all_reasoning_steps = cast(List[ReasoningStep], run_response.extra_data.reasoning_steps)

            if all_reasoning_steps:
                self._add_reasoning_metrics_to_extra_data(reasoning_state["reasoning_time_taken"])
                yield create_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                )

        # Update RunResponse
        # Build a list of messages that should be added to the RunResponse
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunResponse messages
        run_response.messages = messages_for_run_response
        # Update the RunResponse metrics
        run_response.metrics = self.aggregate_metrics_from_messages(messages_for_run_response)

        # Update the run_response audio if streaming
        if model_response.audio is not None:
            run_response.response_audio = model_response.audio

    async def _ahandle_model_response_stream(
        self,
        run_response: RunResponse,
        run_messages: RunMessages,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        stream_intermediate_steps: bool = False,
    ) -> AsyncIterator[RunResponseEvent]:
        self.model = cast(Model, self.model)

        reasoning_state = {
            "reasoning_started": False,
            "reasoning_time_taken": 0.0,
        }
        model_response = ModelResponse(content="")

        model_response_stream = self.model.aresponse_stream(
            messages=run_messages.messages,
            response_format=response_format,
            tools=self._tools_for_model,
            functions=self._functions_for_model,
            tool_choice=self.tool_choice,
            tool_call_limit=self.tool_call_limit,
        )  # type: ignore

        async for model_response_event in model_response_stream:  # type: ignore
            for event in self._handle_model_response_chunk(
                run_response=run_response,
                model_response=model_response,
                model_response_event=model_response_event,
                stream_intermediate_steps=stream_intermediate_steps,
                reasoning_state=reasoning_state,
            ):
                yield event

        if stream_intermediate_steps and reasoning_state["reasoning_started"]:
            all_reasoning_steps: List[ReasoningStep] = []
            if run_response and run_response.extra_data and hasattr(run_response.extra_data, "reasoning_steps"):
                all_reasoning_steps = cast(List[ReasoningStep], run_response.extra_data.reasoning_steps)

            if all_reasoning_steps:
                self._add_reasoning_metrics_to_extra_data(reasoning_state["reasoning_time_taken"])
                yield create_reasoning_completed_event(
                    from_run_response=run_response,
                    content=ReasoningSteps(reasoning_steps=all_reasoning_steps),
                    content_type=ReasoningSteps.__name__,
                )

        # Update RunResponse
        # Build a list of messages that should be added to the RunResponse
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunResponse messages
        run_response.messages = messages_for_run_response
        # Update the RunResponse metrics
        run_response.metrics = self.aggregate_metrics_from_messages(messages_for_run_response)

        # Update the run_response audio if streaming
        if model_response.audio is not None:
            run_response.response_audio = model_response.audio

    # Method: _convert_response_to_structured_format
    def _convert_response_to_structured_format(self, run_response: RunResponse):
        # Convert the response to the structured format if needed
        if self.response_model is not None and not isinstance(run_response.content, self.response_model):
            if isinstance(run_response.content, str) and self.parse_response:
                try:
                    structured_output = parse_response_model_str(run_response.content, self.response_model)

                    # Update RunResponse
                    if structured_output is not None:
                        run_response.content = structured_output
                        run_response.content_type = self.response_model.__name__
                    else:
                        log_warning("Failed to convert response to response_model")
                except Exception as e:
                    log_warning(f"Failed to convert response to output model: {e}")
            else:
                log_warning("Something went wrong. Run response content is not a string")

    # Method: _update_run_response
    def _update_run_response(self, model_response: ModelResponse, run_response: RunResponse, run_messages: RunMessages):
        # Format tool calls if they exist
        if model_response.tool_executions:
            run_response.formatted_tool_calls = format_tool_calls(model_response.tool_executions)

        # Handle structured outputs
        if self.response_model is not None and model_response.parsed is not None:
            # We get native structured outputs from the model
            if self._model_should_return_structured_output():
                # Update the run_response content with the structured output
                run_response.content = model_response.parsed
                # Update the run_response content_type with the structured output class name
                run_response.content_type = self.response_model.__name__
        else:
            # Update the run_response content with the model response content
            run_response.content = model_response.content

        # Update the run_response thinking with the model response thinking (agno 2.x: reasoning_content)
        _ag_thinking = getattr(model_response, "reasoning_content", None) or getattr(model_response, "thinking", None)
        _ag_redacted = getattr(model_response, "redacted_reasoning_content", None) or getattr(
            model_response, "redacted_thinking", None
        )
        if _ag_thinking is not None:
            run_response.thinking = _ag_thinking
        if _ag_redacted is not None:
            if run_response.thinking is None:
                run_response.thinking = _ag_redacted
            else:
                run_response.thinking += _ag_redacted

        # Update the run_response citations with the model response citations
        if model_response.citations is not None:
            run_response.citations = model_response.citations

        # Update the run_response tools with the model response tool_executions
        if model_response.tool_executions is not None:
            if run_response.tools is None:
                run_response.tools = model_response.tool_executions
            else:
                run_response.tools.extend(model_response.tool_executions)

            # For Reasoning/Thinking/Knowledge Tools update reasoning_content in RunResponse
            for tool_call in model_response.tool_executions:
                tool_name = tool_call.tool_name or ""
                if tool_name.lower() in ["think", "analyze"]:
                    tool_args = tool_call.tool_args or {}
                    self.update_reasoning_content_from_tool_call(tool_name, tool_args)

        # Update the run_response audio with the model response audio
        if model_response.audio is not None:
            run_response.response_audio = model_response.audio

        _ag_image = getattr(model_response, "image", None)
        if _ag_image is None:
            _ag_imgs = getattr(model_response, "images", None)
            _ag_image = _ag_imgs[0] if _ag_imgs else None
        if _ag_image is not None:
            self.add_image(_ag_image)

        # Update the run_response messages with the messages
        run_response.messages = run_messages.messages
        # Update the run_response created_at with the model response created_at
        run_response.created_at = model_response.created_at

        # Build a list of messages that should be added to the RunResponse
        messages_for_run_response = [m for m in run_messages.messages if m.add_to_agent_memory]
        # Update the RunResponse messages
        run_response.messages = messages_for_run_response
        # Update the RunResponse metrics
        run_response.metrics = self.aggregate_metrics_from_messages(messages_for_run_response)

    # Method: print_response
    def print_response(
        self,
        message: Optional[Union[List, Dict, str, Message]] = None,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        messages: Optional[List[Union[Dict, Message]]] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream: Optional[bool] = None,
        stream_intermediate_steps: bool = False,
        markdown: bool = False,
        show_message: bool = True,
        show_reasoning: bool = True,
        show_full_reasoning: bool = False,
        console: Optional[Any] = None,
        # Add tags to include in markdown content
        tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
        knowledge_filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        import json

        from rich.console import Group
        from rich.json import JSON
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        if markdown:
            self.markdown = True

        if self.response_model is not None:
            self.markdown = False
            stream = False

        stream_intermediate_steps = stream_intermediate_steps or self.stream_intermediate_steps
        stream = stream or self.stream or False
        if stream:
            _response_content: str = ""
            _response_thinking: str = ""
            reasoning_steps: List[ReasoningStep] = []

            with Live(console=console) as live_log:
                status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
                live_log.update(status)
                response_timer = Timer()
                response_timer.start()
                # Flag which indicates if the panels should be rendered
                render = False
                # Panels to be rendered
                panels = [status]
                # First render the message panel if the message is not None
                if message and show_message:
                    render = True
                    # Convert message to a panel
                    message_content = get_text_from_message(message)
                    message_panel = create_panel(
                        content=Text(message_content, style="green"),
                        title="Message",
                        border_style="cyan",
                    )
                    panels.append(message_panel)
                if render:
                    live_log.update(Group(*panels))

                for resp in self.run(
                    message=message,
                    messages=messages,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    stream=True,
                    stream_intermediate_steps=stream_intermediate_steps,
                    knowledge_filters=knowledge_filters,
                    **kwargs,
                ):
                    if isinstance(resp, tuple(get_args(RunResponseEvent))):
                        if resp.is_paused:
                            resp = cast(RunResponsePausedEvent, resp)
                            response_panel = create_paused_run_response_panel(resp)
                            panels.append(response_panel)
                            live_log.update(Group(*panels))
                            break
                        if resp.event == RunEvent.run_response_content:
                            if hasattr(resp, "content") and isinstance(resp.content, str):
                                _response_content += resp.content
                            if hasattr(resp, "thinking") and resp.thinking is not None:
                                _response_thinking += resp.thinking
                        if (
                            hasattr(resp, "extra_data")
                            and resp.extra_data is not None
                            and resp.extra_data.reasoning_steps is not None
                        ):
                            reasoning_steps = resp.extra_data.reasoning_steps

                    response_content_stream: Union[str, Markdown] = _response_content

                    # Escape special tags before markdown conversion
                    if self.markdown:
                        escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                        response_content_stream = Markdown(escaped_content)
                    panels = [status]

                    if message and show_message:
                        render = True
                        # Convert message to a panel
                        message_content = get_text_from_message(message)
                        message_panel = create_panel(
                            content=Text(message_content, style="green"),
                            title="Message",
                            border_style="cyan",
                        )
                        panels.append(message_panel)
                    if render:
                        live_log.update(Group(*panels))

                    if len(reasoning_steps) > 0 and show_reasoning:
                        render = True
                        # Create panels for reasoning steps
                        for i, step in enumerate(reasoning_steps, 1):
                            # Build step content
                            step_content = Text.assemble()
                            if step.title is not None:
                                step_content.append(f"{step.title}\n", "bold")
                            if step.action is not None:
                                step_content.append(
                                    Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim")
                                )
                            if step.result is not None:
                                step_content.append(Text.from_markup(step.result, style="dim"))

                            if show_full_reasoning:
                                # Add detailed reasoning information if available
                                if step.reasoning is not None:
                                    step_content.append(
                                        Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim")
                                    )
                                if step.confidence is not None:
                                    step_content.append(
                                        Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim")
                                    )
                            reasoning_panel = create_panel(
                                content=step_content, title=f"Reasoning step {i}", border_style="green"
                            )
                            panels.append(reasoning_panel)
                    if render:
                        live_log.update(Group(*panels))

                    if len(_response_thinking) > 0:
                        render = True
                        # Create panel for thinking
                        thinking_panel = create_panel(
                            content=Text(_response_thinking),
                            title=f"Thinking ({response_timer.elapsed:.1f}s)",
                            border_style="green",
                        )
                        panels.append(thinking_panel)
                    if render:
                        live_log.update(Group(*panels))

                    # Add tool calls panel if available
                    if (
                        self.show_tool_calls
                        and self.run_response is not None
                        and self.run_response.formatted_tool_calls
                    ):
                        render = True
                        # Create bullet points for each tool call
                        tool_calls_content = Text()
                        for formatted_tool_call in self.run_response.formatted_tool_calls:
                            tool_calls_content.append(f"• {formatted_tool_call}\n")

                        tool_calls_panel = create_panel(
                            content=tool_calls_content.plain.rstrip(),
                            title="Tool Calls",
                            border_style="yellow",
                        )
                        panels.append(tool_calls_panel)

                    if len(_response_content) > 0:
                        render = True
                        # Create panel for response
                        response_panel = create_panel(
                            content=response_content_stream,
                            title=f"Response ({response_timer.elapsed:.1f}s)",
                            border_style="blue",
                        )
                        panels.append(response_panel)
                    if render:
                        live_log.update(Group(*panels))

                    if (
                        isinstance(resp, tuple(get_args(RunResponseEvent)))
                        and hasattr(resp, "citations")
                        and resp.citations is not None
                        and resp.citations.urls is not None
                    ):
                        md_content = "\n".join(
                            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                            for i, citation in enumerate(resp.citations.urls)
                            if citation.url  # Only include citations with valid URLs
                        )
                        if md_content:  # Only create panel if there are citations
                            citations_panel = create_panel(
                                content=Markdown(md_content),
                                title="Citations",
                                border_style="green",
                            )
                            panels.append(citations_panel)
                            live_log.update(Group(*panels))

                if self.memory is not None and isinstance(self.memory, Memory):
                    if self.memory.memory_manager is not None and self.memory.memory_manager.memories_updated:
                        memory_panel = create_panel(
                            content=Text("Memories updated"),
                            title="Memories",
                            border_style="green",
                        )
                        panels.append(memory_panel)
                        live_log.update(Group(*panels))
                        self.memory.memory_manager.memories_updated = False

                    if self.memory.summary_manager is not None and self.memory.summary_manager.summary_updated:
                        summary_panel = create_panel(
                            content=Text("Session summary updated"),
                            title="Session Summary",
                            border_style="green",
                        )
                        panels.append(summary_panel)
                        live_log.update(Group(*panels))
                        self.memory.summary_manager.summary_updated = False

                response_timer.stop()

                # Final update to remove the "Thinking..." status
                panels = [p for p in panels if not isinstance(p, Status)]
                live_log.update(Group(*panels))
        else:
            with Live(console=console) as live_log:
                status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
                live_log.update(status)
                response_timer = Timer()
                response_timer.start()
                # Panels to be rendered
                panels = [status]
                # First render the message panel if the message is not None
                if message and show_message:
                    # Convert message to a panel
                    message_content = get_text_from_message(message)
                    message_panel = create_panel(
                        content=Text(message_content, style="green"),
                        title="Message",
                        border_style="cyan",
                    )
                    panels.append(message_panel)
                    live_log.update(Group(*panels))

                # Run the agent
                run_response = self.run(
                    message=message,
                    messages=messages,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    stream=False,
                    stream_intermediate_steps=stream_intermediate_steps,
                    knowledge_filters=knowledge_filters,
                    **kwargs,
                )
                response_timer.stop()

                reasoning_steps = []

                if isinstance(run_response, RunResponse) and run_response.is_paused:
                    response_panel = create_paused_run_response_panel(run_response)
                    panels.append(response_panel)
                    live_log.update(Group(*panels))
                    return

                if (
                    isinstance(run_response, RunResponse)
                    and run_response.extra_data is not None
                    and run_response.extra_data.reasoning_steps is not None
                ):
                    reasoning_steps = run_response.extra_data.reasoning_steps

                if len(reasoning_steps) > 0 and show_reasoning:
                    # Create panels for reasoning steps
                    for i, step in enumerate(reasoning_steps, 1):
                        # Build step content
                        step_content = Text.assemble()
                        if step.title is not None:
                            step_content.append(f"{step.title}\n", "bold")
                        if step.action is not None:
                            step_content.append(Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim"))
                        if step.result is not None:
                            step_content.append(Text.from_markup(step.result, style="dim"))

                        if show_full_reasoning:
                            # Add detailed reasoning information if available
                            if step.reasoning is not None:
                                step_content.append(
                                    Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim")
                                )
                            if step.confidence is not None:
                                step_content.append(
                                    Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim")
                                )
                        reasoning_panel = create_panel(
                            content=step_content, title=f"Reasoning step {i}", border_style="green"
                        )
                        panels.append(reasoning_panel)
                    live_log.update(Group(*panels))

                if isinstance(run_response, RunResponse) and run_response.thinking is not None:
                    # Create panel for thinking
                    thinking_panel = create_panel(
                        content=Text(run_response.thinking),
                        title=f"Thinking ({response_timer.elapsed:.1f}s)",
                        border_style="green",
                    )
                    panels.append(thinking_panel)
                    live_log.update(Group(*panels))

                # Add tool calls panel if available
                if self.show_tool_calls and isinstance(run_response, RunResponse) and run_response.formatted_tool_calls:
                    # Create bullet points for each tool call
                    tool_calls_content = Text()
                    for formatted_tool_call in run_response.formatted_tool_calls:
                        tool_calls_content.append(f"• {formatted_tool_call}\n")

                    tool_calls_panel = create_panel(
                        content=tool_calls_content.plain.rstrip(),
                        title="Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(tool_calls_panel)
                    live_log.update(Group(*panels))

                response_content_batch: Union[str, JSON, Markdown] = ""
                if isinstance(run_response, RunResponse):
                    if isinstance(run_response.content, str):
                        if self.markdown:
                            escaped_content = escape_markdown_tags(run_response.content, tags_to_include_in_markdown)
                            response_content_batch = Markdown(escaped_content)
                        else:
                            response_content_batch = run_response.get_content_as_string(indent=4)
                    elif self.response_model is not None and isinstance(run_response.content, BaseModel):
                        try:
                            response_content_batch = JSON(
                                run_response.content.model_dump_json(exclude_none=True), indent=2
                            )
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    else:
                        try:
                            response_content_batch = JSON(json.dumps(run_response.content), indent=4)
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")

                # Create panel for response
                response_panel = create_panel(
                    content=response_content_batch,
                    title=f"Response ({response_timer.elapsed:.1f}s)",
                    border_style="blue",
                )
                panels.append(response_panel)

                if (
                    isinstance(run_response, RunResponse)
                    and run_response.citations is not None
                    and run_response.citations.urls is not None
                ):
                    md_content = "\n".join(
                        f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                        for i, citation in enumerate(run_response.citations.urls)
                        if citation.url  # Only include citations with valid URLs
                    )
                    if md_content:  # Only create panel if there are citations
                        citations_panel = create_panel(
                            content=Markdown(md_content),
                            title="Citations",
                            border_style="green",
                        )
                        panels.append(citations_panel)
                        live_log.update(Group(*panels))

                if self.memory is not None and isinstance(self.memory, Memory):
                    if self.memory.memory_manager is not None and self.memory.memory_manager.memories_updated:
                        memory_panel = create_panel(
                            content=Text("Memories updated"),
                            title="Memories",
                            border_style="green",
                        )
                        panels.append(memory_panel)
                        live_log.update(Group(*panels))
                        self.memory.memory_manager.memories_updated = False

                    if self.memory.summary_manager is not None and self.memory.summary_manager.summary_updated:
                        summary_panel = create_panel(
                            content=Text("Session summary updated"),
                            title="Session Summary",
                            border_style="green",
                        )
                        panels.append(summary_panel)
                        live_log.update(Group(*panels))
                        self.memory.summary_manager.summary_updated = False

                # Final update to remove the "Thinking..." status
                panels = [p for p in panels if not isinstance(p, Status)]
                live_log.update(Group(*panels))

    async def aprint_response(
        self,
        message: Optional[Union[List, Dict, str, Message]] = None,
        *,
        messages: Optional[List[Union[Dict, Message]]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream: Optional[bool] = None,
        stream_intermediate_steps: bool = False,
        markdown: bool = False,
        show_message: bool = True,
        show_reasoning: bool = True,
        show_full_reasoning: bool = False,
        console: Optional[Any] = None,
        # Add tags to include in markdown content
        tags_to_include_in_markdown: Set[str] = {"think", "thinking"},
        knowledge_filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        import json

        from rich.console import Group
        from rich.json import JSON
        from rich.live import Live
        from rich.markdown import Markdown
        from rich.status import Status
        from rich.text import Text

        if markdown:
            self.markdown = True

        if self.response_model is not None:
            self.markdown = False
            stream = False

        stream_intermediate_steps = stream_intermediate_steps or self.stream_intermediate_steps
        stream = stream or self.stream or False
        if stream:
            _response_content: str = ""
            _response_thinking: str = ""
            reasoning_steps: List[ReasoningStep] = []

            with Live(console=console) as live_log:
                status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
                live_log.update(status)
                response_timer = Timer()
                response_timer.start()
                # Flag which indicates if the panels should be rendered
                render = False
                # Panels to be rendered
                panels = [status]
                # First render the message panel if the message is not None
                if message and show_message:
                    render = True
                    # Convert message to a panel
                    message_content = get_text_from_message(message)
                    message_panel = create_panel(
                        content=Text(message_content, style="green"),
                        title="Message",
                        border_style="cyan",
                    )
                    panels.append(message_panel)
                if render:
                    live_log.update(Group(*panels))

                result = await self.arun(
                    message=message,
                    messages=messages,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    stream=True,
                    stream_intermediate_steps=stream_intermediate_steps,
                    knowledge_filters=knowledge_filters,
                    **kwargs,
                )

                async for resp in result:
                    if isinstance(resp, tuple(get_args(RunResponseEvent))):
                        if resp.is_paused:
                            response_panel = create_paused_run_response_panel(resp)
                            panels.append(response_panel)
                            live_log.update(Group(*panels))
                            break

                        if resp.event == RunEvent.run_response_content:
                            if isinstance(resp.content, str):
                                _response_content += resp.content
                            if resp.thinking is not None:
                                _response_thinking += resp.thinking

                        if (
                            hasattr(resp, "extra_data")
                            and resp.extra_data is not None
                            and resp.extra_data.reasoning_steps is not None
                        ):
                            reasoning_steps = resp.extra_data.reasoning_steps

                    response_content_stream: Union[str, Markdown] = _response_content
                    # Escape special tags before markdown conversion
                    if self.markdown:
                        escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                        response_content_stream = Markdown(escaped_content)

                    panels = [status]

                    if message and show_message:
                        render = True
                        # Convert message to a panel
                        message_content = get_text_from_message(message)
                        message_panel = create_panel(
                            content=Text(message_content, style="green"),
                            title="Message",
                            border_style="cyan",
                        )
                        panels.append(message_panel)
                    if render:
                        live_log.update(Group(*panels))

                    if len(reasoning_steps) > 0 and (show_reasoning or show_full_reasoning):
                        render = True
                        # Create panels for reasoning steps
                        for i, step in enumerate(reasoning_steps, 1):
                            # Build step content
                            step_content = Text.assemble()
                            if step.title is not None:
                                step_content.append(f"{step.title}\n", "bold")
                            if step.action is not None:
                                step_content.append(
                                    Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim")
                                )
                            if step.result is not None:
                                step_content.append(Text.from_markup(step.result, style="dim"))

                            if show_full_reasoning:
                                # Add detailed reasoning information if available
                                if step.reasoning is not None:
                                    step_content.append(
                                        Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim")
                                    )
                                if step.confidence is not None:
                                    step_content.append(
                                        Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim")
                                    )
                            reasoning_panel = create_panel(
                                content=step_content, title=f"Reasoning step {i}", border_style="green"
                            )
                            panels.append(reasoning_panel)
                    if render:
                        live_log.update(Group(*panels))

                    if len(_response_thinking) > 0:
                        render = True
                        # Create panel for thinking
                        thinking_panel = create_panel(
                            content=Text(_response_thinking),
                            title=f"Thinking ({response_timer.elapsed:.1f}s)",
                            border_style="green",
                        )
                        panels.append(thinking_panel)
                    if render:
                        live_log.update(Group(*panels))

                    # Add tool calls panel if available
                    if (
                        self.show_tool_calls
                        and self.run_response is not None
                        and self.run_response.formatted_tool_calls
                    ):
                        render = True
                        # Create bullet points for each tool call
                        tool_calls_content = Text()
                        for formatted_tool_call in self.run_response.formatted_tool_calls:
                            tool_calls_content.append(f"• {formatted_tool_call}\n")

                        tool_calls_panel = create_panel(
                            content=tool_calls_content.plain.rstrip(),
                            title="Tool Calls",
                            border_style="yellow",
                        )
                        panels.append(tool_calls_panel)
                        live_log.update(Group(*panels))

                    if len(_response_content) > 0:
                        render = True
                        # Create panel for response
                        response_panel = create_panel(
                            content=response_content_stream,
                            title=f"Response ({response_timer.elapsed:.1f}s)",
                            border_style="blue",
                        )
                        panels.append(response_panel)
                    if render:
                        live_log.update(Group(*panels))

                    if (
                        isinstance(resp, tuple(get_args(RunResponseEvent)))
                        and hasattr(resp, "citations")
                        and resp.citations is not None
                        and resp.citations.urls is not None
                    ):
                        md_content = "\n".join(
                            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                            for i, citation in enumerate(resp.citations.urls)
                            if citation.url  # Only include citations with valid URLs
                        )
                        if md_content:  # Only create panel if there are citations
                            citations_panel = create_panel(
                                content=Markdown(md_content),
                                title="Citations",
                                border_style="green",
                            )
                            panels.append(citations_panel)
                            live_log.update(Group(*panels))

                if self.memory is not None and isinstance(self.memory, Memory):
                    if self.memory.memory_manager is not None and self.memory.memory_manager.memories_updated:
                        memory_panel = create_panel(
                            content=Text("Memories updated"),
                            title="Memories",
                            border_style="green",
                        )
                        panels.append(memory_panel)
                        live_log.update(Group(*panels))
                        self.memory.memory_manager.memories_updated = False

                    if self.memory.summary_manager is not None and self.memory.summary_manager.summary_updated:
                        summary_panel = create_panel(
                            content=Text("Session summary updated"),
                            title="Session Summary",
                            border_style="green",
                        )
                        panels.append(summary_panel)
                        live_log.update(Group(*panels))
                        self.memory.summary_manager.summary_updated = False

                response_timer.stop()

                # Final update to remove the "Thinking..." status
                panels = [p for p in panels if not isinstance(p, Status)]
                live_log.update(Group(*panels))
        else:
            with Live(console=console) as live_log:
                status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
                live_log.update(status)
                response_timer = Timer()
                response_timer.start()
                # Panels to be rendered
                panels = [status]
                # First render the message panel if the message is not None
                if message and show_message:
                    # Convert message to a panel
                    message_content = get_text_from_message(message)
                    message_panel = create_panel(
                        content=Text(message_content, style="green"),
                        title="Message",
                        border_style="cyan",
                    )
                    panels.append(message_panel)
                    live_log.update(Group(*panels))

                # Run the agent
                run_response = await self.arun(
                    message=message,
                    messages=messages,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    stream=False,
                    stream_intermediate_steps=stream_intermediate_steps,
                    knowledge_filters=knowledge_filters,
                    **kwargs,
                )
                response_timer.stop()

                if isinstance(run_response, RunResponse) and run_response.is_paused:
                    response_panel = create_paused_run_response_panel(run_response)
                    panels.append(response_panel)
                    live_log.update(Group(*panels))
                    return

                reasoning_steps = []
                if (
                    isinstance(run_response, RunResponse)
                    and run_response.extra_data is not None
                    and run_response.extra_data.reasoning_steps is not None
                ):
                    reasoning_steps = run_response.extra_data.reasoning_steps

                if len(reasoning_steps) > 0 and show_reasoning:
                    # Create panels for reasoning steps
                    for i, step in enumerate(reasoning_steps, 1):
                        # Build step content
                        step_content = Text.assemble()
                        if step.title is not None:
                            step_content.append(f"{step.title}\n", "bold")
                        if step.action is not None:
                            step_content.append(Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim"))
                        if step.result is not None:
                            step_content.append(Text.from_markup(step.result, style="dim"))

                        if show_full_reasoning:
                            # Add detailed reasoning information if available
                            if step.reasoning is not None:
                                step_content.append(
                                    Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim")
                                )
                            if step.confidence is not None:
                                step_content.append(
                                    Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim")
                                )
                        reasoning_panel = create_panel(
                            content=step_content, title=f"Reasoning step {i}", border_style="green"
                        )
                        panels.append(reasoning_panel)
                    live_log.update(Group(*panels))

                if isinstance(run_response, RunResponse) and run_response.thinking is not None:
                    # Create panel for thinking
                    thinking_panel = create_panel(
                        content=Text(run_response.thinking),
                        title=f"Thinking ({response_timer.elapsed:.1f}s)",
                        border_style="green",
                    )
                    panels.append(thinking_panel)
                    live_log.update(Group(*panels))

                if self.show_tool_calls and isinstance(run_response, RunResponse) and run_response.formatted_tool_calls:
                    tool_calls_content = Text()
                    for formatted_tool_call in run_response.formatted_tool_calls:
                        tool_calls_content.append(f"• {formatted_tool_call}\n")

                    tool_calls_panel = create_panel(
                        content=tool_calls_content.plain.rstrip(),
                        title="Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(tool_calls_panel)
                    live_log.update(Group(*panels))

                response_content_batch: Union[str, JSON, Markdown] = ""
                if isinstance(run_response, RunResponse):
                    if isinstance(run_response.content, str):
                        if self.markdown:
                            escaped_content = escape_markdown_tags(run_response.content, tags_to_include_in_markdown)
                            response_content_batch = Markdown(escaped_content)
                        else:
                            response_content_batch = run_response.get_content_as_string(indent=4)
                    elif self.response_model is not None and isinstance(run_response.content, BaseModel):
                        try:
                            response_content_batch = JSON(
                                run_response.content.model_dump_json(exclude_none=True), indent=2
                            )
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    else:
                        try:
                            response_content_batch = JSON(json.dumps(run_response.content), indent=4)
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")

                # Create panel for response
                response_panel = create_panel(
                    content=response_content_batch,
                    title=f"Response ({response_timer.elapsed:.1f}s)",
                    border_style="blue",
                )
                panels.append(response_panel)

                if (
                    isinstance(run_response, RunResponse)
                    and run_response.citations is not None
                    and run_response.citations.urls is not None
                ):
                    md_content = "\n".join(
                        f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                        for i, citation in enumerate(run_response.citations.urls)
                        if citation.url  # Only include citations with valid URLs
                    )
                    if md_content:  # Only create panel if there are citations
                        citations_panel = create_panel(
                            content=Markdown(md_content),
                            title="Citations",
                            border_style="green",
                        )
                        panels.append(citations_panel)
                        live_log.update(Group(*panels))

                if self.memory is not None and isinstance(self.memory, Memory):
                    if self.memory.memory_manager is not None and self.memory.memory_manager.memories_updated:
                        memory_panel = create_panel(
                            content=Text("Memories updated"),
                            title="Memories",
                            border_style="green",
                        )
                        panels.append(memory_panel)
                        live_log.update(Group(*panels))
                        self.memory.memory_manager.memories_updated = False

                    if self.memory.summary_manager is not None and self.memory.summary_manager.summary_updated:
                        summary_panel = create_panel(
                            content=Text("Session summary updated"),
                            title="Session Summary",
                            border_style="green",
                        )
                        panels.append(summary_panel)
                        live_log.update(Group(*panels))
                        self.memory.summary_manager.summary_updated = False

                # Final update to remove the "Thinking..." status
                panels = [p for p in panels if not isinstance(p, Status)]
                live_log.update(Group(*panels))

    # Method: aggregate_metrics_from_messages
    def aggregate_metrics_from_messages(self, messages: List[Message]) -> Dict[str, Any]:
        aggregated_metrics: Dict[str, Any] = defaultdict(list)
        assistant_message_role = self.model.assistant_message_role if self.model is not None else "assistant"
        for m in messages:
            if m.role == assistant_message_role and m.metrics is not None and m.from_history is False:
                for k, v in asdict(m.metrics).items():
                    if k == "timer":
                        continue
                    if v is not None:
                        aggregated_metrics[k].append(v)
        if aggregated_metrics is not None:
            aggregated_metrics = dict(aggregated_metrics)
        return aggregated_metrics
